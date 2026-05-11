"""Telegram webhook endpoint.

Validates the ``X-Telegram-Bot-Api-Secret-Token`` header (fail-closed),
parses the leading command, hands a channel-neutral
:class:`InboundMessage` to the :class:`Dispatcher`, and returns a
``sendMessage`` payload as the webhook response body.

When the leading token is not a recognised command and the message body
is non-empty, the heuristic classifier picks ``ENTRY`` / ``ASK`` /
``CLARIFY`` and the inbound message is tagged ``route_source="heuristic"``
(R-11).
"""

from __future__ import annotations

import contextlib
import secrets
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException

from diary_rag.adapters.embeddings import build_embedding_client
from diary_rag.adapters.telegram.client import HttpxTelegramClient, TelegramClient
from diary_rag.adapters.telegram.commands import parse_command
from diary_rag.adapters.telegram.drafts_packing import pack_drafts_into_messages
from diary_rag.adapters.telegram.models import TelegramUpdate
from diary_rag.adapters.telegram.reply import build_send_message_payload
from diary_rag.config import Settings, get_settings
from diary_rag.core.diary.models import SourceMessage
from diary_rag.core.routing import InboundMessage, RouteKind, RouteSource, lifecycle_for
from diary_rag.core.routing.classifier import classify_plain_text
from diary_rag.logging import get_logger
from diary_rag.services import DiaryService, Dispatcher, ExportService, QueryService
from diary_rag.storage.mock import MockDiaryStore
from diary_rag.storage.search_repository import HybridDiaryStore

log = get_logger(__name__)

_dispatcher: Dispatcher | None = None
_telegram_client: TelegramClient | None = None


def _build_store(settings: Settings) -> HybridDiaryStore:
    if settings.storage_backend == "postgres":
        from diary_rag.storage.postgres import PostgresDiaryStore

        return PostgresDiaryStore(settings.postgres_dsn())
    if settings.storage_backend == "sqlite":
        from diary_rag.storage.sqlite import SqliteDiaryStore

        return SqliteDiaryStore(settings.sqlite_path)
    return MockDiaryStore()


def get_dispatcher() -> Dispatcher:
    global _dispatcher
    if _dispatcher is None:
        settings = get_settings()
        store = _build_store(settings)
        embedding_client = build_embedding_client(settings)
        _dispatcher = Dispatcher(
            DiaryService(store, embedding_client=embedding_client),
            QueryService(
                store,
                embedding_client,
                top_k=settings.retrieval_top_k,
                candidate_k=settings.retrieval_candidate_k,
            ),
            ExportService(store),
            settings,
        )
        log.info(
            "dispatcher.built storage_backend=%s embedding_backend=%s "
            "embedding_model=%s embedding_dim=%d top_k=%d candidate_k=%d",
            settings.storage_backend,
            settings.embedding_backend,
            embedding_client.model_name,
            embedding_client.dimension,
            settings.retrieval_top_k,
            settings.retrieval_candidate_k,
        )
    return _dispatcher


def get_telegram_client() -> TelegramClient:
    global _telegram_client
    if _telegram_client is None:
        settings = get_settings()
        _telegram_client = HttpxTelegramClient(settings.telegram_bot_token)
    return _telegram_client


def _verify_secret(expected: str, provided: str | None) -> None:
    if not expected or provided is None:
        raise HTTPException(status_code=401, detail="invalid webhook secret")
    if not secrets.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="invalid webhook secret")


def _resolve_route(
    text: str | None,
) -> tuple[RouteKind, str, RouteSource, str | None]:
    """Return ``(route, payload, route_source, confidence)`` for the inbound text."""
    command_route, command_payload = parse_command(text)
    if command_route is not RouteKind.UNKNOWN or not text or not text.strip():
        return command_route, command_payload, "command", None
    classified = classify_plain_text(text)
    return classified.route, classified.payload, "heuristic", classified.confidence


def register_telegram_webhook(app: FastAPI) -> None:
    @app.post("/telegram/webhook")
    def telegram_webhook(
        update: TelegramUpdate,
        settings: Annotated[Settings, Depends(get_settings)],
        dispatcher: Annotated[Dispatcher, Depends(get_dispatcher)],
        telegram_client: Annotated[TelegramClient, Depends(get_telegram_client)],
        x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        _verify_secret(settings.telegram_webhook_secret, x_telegram_bot_api_secret_token)

        message = update.message
        if message is None:
            log.info("telegram.webhook update_id=%s no_message=true", update.update_id)
            return {}

        route, payload, route_source, confidence = _resolve_route(message.text)
        edit_seq = message.edit_date if message.edit_date is not None else 0
        inbound = InboundMessage(
            external_message_id=str(message.message_id),
            external_chat_id=str(message.chat.id),
            external_user_id=str(message.from_.id),
            text=message.text or "",
            route=route,
            received_at=datetime.fromtimestamp(message.date, tz=UTC),
            route_source=route_source,
            payload=payload,
            edit_seq=edit_seq,
        )

        result = dispatcher.dispatch(inbound)
        effective_path = result.metadata.get("effective_path", "n/a")
        log.info(
            "telegram.webhook update_id=%s route=%s route_source=%s "
            "confidence=%s edit_seq=%s lifecycle=%s effective_path=%s",
            update.update_id,
            result.route.value,
            route_source,
            confidence or "n/a",
            edit_seq,
            lifecycle_for(result.route),
            effective_path,
        )
        if result.document is not None:
            try:
                telegram_client.send_document(
                    chat_id=inbound.external_chat_id,
                    filename=result.document.filename,
                    content=result.document.content,
                    media_type=result.document.media_type,
                    caption=result.reply_text,
                )
            except Exception as exc:
                log.warning(
                    "export.delivery_failed chat_id=%s filename=%s error_class=%s",
                    inbound.external_chat_id,
                    result.document.filename,
                    exc.__class__.__name__,
                )
                return build_send_message_payload(
                    inbound.external_chat_id,
                    "Export generated but delivery to Telegram failed. " "Try /export json again.",
                )
            log.info(
                "export.delivered chat_id=%s filename=%s bytes=%d",
                inbound.external_chat_id,
                result.document.filename,
                len(result.document.content),
            )
            return {}
        if result.drafts is not None:
            blocks = [_render_draft_block(d) for d in result.drafts]
            messages = pack_drafts_into_messages(result.reply_text, blocks)
            total = len(messages)
            sent = 0
            for body in messages:
                try:
                    telegram_client.send_message(chat_id=inbound.external_chat_id, text=body)
                except Exception as exc:
                    log.warning(
                        "drafts.delivery_failed chat_id=%s sent=%d total=%d " "error_class=%s",
                        inbound.external_chat_id,
                        sent,
                        total,
                        exc.__class__.__name__,
                    )
                    with contextlib.suppress(Exception):
                        telegram_client.send_message(
                            chat_id=inbound.external_chat_id,
                            text=(
                                f"Couldn't deliver all drafts (sent {sent}/{total}). " "Try again."
                            ),
                        )
                    return {}
                sent += 1
            log.info(
                "drafts.delivered chat_id=%s draft_count=%d messages_sent=%d",
                inbound.external_chat_id,
                len(result.drafts),
                sent,
            )
            return {}
        return build_send_message_payload(inbound.external_chat_id, result.reply_text)


def _render_draft_block(draft: SourceMessage) -> str:
    """Render a draft as a chat block: header line + blank line + raw text."""
    short_id = draft.source_message_id[-8:]
    header = (
        f"\U0001f4dd {draft.created_at.isoformat()} · "
        f"author:{draft.author_user_id} · id:{short_id}"
    )
    return f"{header}\n\n{draft.raw_text}"
