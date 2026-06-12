"""Telegram webhook endpoint.

Validates the ``X-Telegram-Bot-Api-Secret-Token`` header (fail-closed),
parses the leading command, hands a channel-neutral
:class:`InboundMessage` to the :class:`Dispatcher`, and returns a
``sendMessage`` payload as the webhook response body.

When the leading token is not a recognised command and the message body
is non-empty, the heuristic classifier picks ``NOTE`` / ``ASK`` /
``CLARIFY`` and the inbound message is tagged ``route_source="heuristic"``
(R-11).
"""

from __future__ import annotations

import contextlib
import secrets
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException

from memory_rag.adapters.answers import build_chat_client
from memory_rag.adapters.chat_routing import (
    build_outward_rewriter,
    build_query_rewriter,
    build_route_classifier,
)
from memory_rag.adapters.embeddings import build_embedding_client
from memory_rag.adapters.knowledge import build_knowledge_source
from memory_rag.adapters.telegram.author_display import (
    AuthorDisplayInputStore,
    TelegramBackendStore,
    _resolve_source_author_display,
    render_source_block,
)
from memory_rag.adapters.telegram.client import HttpxTelegramClient, TelegramClient
from memory_rag.adapters.telegram.commands import parse_command
from memory_rag.adapters.telegram.community import resolve_community_id
from memory_rag.adapters.telegram.drafts_packing import pack_drafts_into_messages
from memory_rag.adapters.telegram.models import TelegramUpdate
from memory_rag.adapters.telegram.reply import build_send_message_payload
from memory_rag.adapters.telegram.subject import resolve_subject_id
from memory_rag.config import Settings, get_settings
from memory_rag.core.domain.models import SourceMessage
from memory_rag.core.routing import InboundMessage, RouteKind, RouteSource, lifecycle_for
from memory_rag.core.routing.classifier import classify_plain_text
from memory_rag.logging import get_logger
from memory_rag.services import (
    Dispatcher,
    DomainService,
    ExportService,
    QueryService,
    RoutedChatService,
)
from memory_rag.storage.mock import MockDomainStore

log = get_logger(__name__)

_dispatcher: Dispatcher | None = None
_store: TelegramBackendStore | None = None
_telegram_client: TelegramClient | None = None


def _build_store(settings: Settings) -> TelegramBackendStore:
    if settings.storage_backend == "postgres":
        from memory_rag.storage.postgres import PostgresDomainStore

        return PostgresDomainStore(settings.postgres_dsn())
    if settings.storage_backend == "sqlite":
        from memory_rag.storage.sqlite import SqliteDomainStore

        return SqliteDomainStore(settings.sqlite_path)
    return MockDomainStore()


def _get_store(settings: Settings) -> TelegramBackendStore:
    """Build the per-process backend store once and share it.

    The dispatcher (core ingest + retrieval seams) and the adapter-owned author
    display-input port (D-084) are both backed by this single instance, so a
    snapshot written through the port lands in the same backend the dispatcher
    persists source messages to.
    """
    global _store
    if _store is None:
        _store = _build_store(settings)
    return _store


def get_dispatcher() -> Dispatcher:
    global _dispatcher
    if _dispatcher is None:
        settings = get_settings()
        store = _get_store(settings)
        embedding_client = build_embedding_client(settings)
        chat_client = build_chat_client(settings)
        route_classifier = build_route_classifier(settings)
        query_rewriter = build_query_rewriter(settings)
        outward_rewriter = build_outward_rewriter(settings)
        knowledge_source = build_knowledge_source(settings)
        query_service = QueryService(
            store,
            store,
            embedding_client,
            chat_client,
            top_k=settings.retrieval_top_k,
            candidate_k=settings.retrieval_candidate_k,
        )
        _dispatcher = Dispatcher(
            DomainService(store, embedding_client=embedding_client),
            query_service,
            ExportService(store),
            settings,
            routed_chat=RoutedChatService(
                route_classifier,
                query_service,
                chat_client,
                store,
                rewriter=query_rewriter,
                knowledge_source=knowledge_source,
                outward_rewriter=outward_rewriter,
            ),
        )
        log.info(
            "dispatcher.built storage_backend=%s embedding_backend=%s "
            "embedding_model=%s embedding_dim=%d chat_backend=%s "
            "chat_model=%s classifier_backend=%s classifier_model=%s "
            "knowledge_backend=%s top_k=%d candidate_k=%d",
            settings.storage_backend,
            settings.embedding_backend,
            embedding_client.model_name,
            embedding_client.dimension,
            settings.chat_backend,
            chat_client.model_name,
            settings.classifier_backend,
            route_classifier.model_name,
            knowledge_source.provider_name,
            settings.retrieval_top_k,
            settings.retrieval_candidate_k,
        )
    return _dispatcher


def get_author_display_input_store() -> AuthorDisplayInputStore:
    """Adapter-owned author display-input port (D-084).

    Returns the same per-process store the dispatcher uses, typed as the
    adapter-owned port distinct from the core ``DomainRepository``. Used by the
    capture path only — least privilege: capture sees the port, not the full
    backend seam.
    """
    return _get_store(get_settings())


def get_backend_store() -> TelegramBackendStore:
    """Combined adapter-side store seam for ``/sources`` author rendering (D-086).

    The same per-process singleton, typed as the combined ``TelegramBackendStore``
    so the ``/sources`` renderer can both look the source message up
    (``get_source_message``) and read the display-input snapshot
    (``get_author_display_input``) to resolve the author display name.
    """
    return _get_store(get_settings())


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
        display_store: Annotated[AuthorDisplayInputStore, Depends(get_author_display_input_store)],
        backend_store: Annotated[TelegramBackendStore, Depends(get_backend_store)],
        x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        _verify_secret(settings.telegram_webhook_secret, x_telegram_bot_api_secret_token)

        message = update.message
        if message is None:
            log.info("telegram.webhook update_id=%s no_message=true", update.update_id)
            return {}

        route, payload, route_source, confidence = _resolve_route(message.text)
        edit_seq = message.edit_date if message.edit_date is not None else 0
        external_chat_id = str(message.chat.id)
        # Adapter-axis chat→community mapping resolved once at the edge
        # (D-093 / G-1). The core receives the opaque community_id and never
        # re-derives scope from external_chat_id (I-1).
        community_id = resolve_community_id(external_chat_id)
        # Adapter-axis community→subject mapping resolved at the edge (H-2 /
        # D-097), parallel to community resolution. Default single-subject
        # mapping returns None (community-wide); the core carries the opaque
        # subject_id through ingest and never derives it from a host field (I-1).
        subject_id = resolve_subject_id(community_id)
        inbound = InboundMessage(
            external_message_id=str(message.message_id),
            external_chat_id=external_chat_id,
            external_user_id=str(message.from_.id),
            community_id=community_id,
            text=message.text or "",
            route=route,
            received_at=datetime.fromtimestamp(message.date, tz=UTC),
            route_source=route_source,
            payload=payload,
            edit_seq=edit_seq,
            subject_id=subject_id,
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

        # Capture the adapter-owned author display-input snapshot for routes
        # that land a source message (note/draft lifecycles), keyed by the same
        # idempotency tuple (D-084). Values come straight from the raw Telegram
        # ``from_`` — never via the core ``InboundMessage`` / ``SourceMessage``.
        # Best-effort: a snapshot-write failure must not break the reply.
        if lifecycle_for(result.route) in ("note", "draft"):
            try:
                display_store.save_author_display_input(
                    external_chat_id=inbound.external_chat_id,
                    external_message_id=inbound.external_message_id,
                    edit_seq=inbound.edit_seq,
                    username=message.from_.username,
                    first_name=message.from_.first_name,
                )
            except Exception as exc:
                log.warning(
                    "author_display.capture_failed chat_id=%s message_id=%s "
                    "edit_seq=%s error_class=%s",
                    inbound.external_chat_id,
                    inbound.external_message_id,
                    inbound.edit_seq,
                    exc.__class__.__name__,
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
            blocks = [
                _render_draft_block(d, store=backend_store, community_id=inbound.community_id)
                for d in result.drafts
            ]
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
        if result.source_chunks is not None:
            chunk_count = len(result.source_chunks)
            # Requester-scoped community for the /sources author lookup. The
            # opaque community_id was resolved at the edge by the adapter-owned
            # chat→community resolver (D-093 / G-1); the community-scoped read
            # keeps author resolution from ever crossing a community boundary
            # (Slice 8.1.2 / D-089).
            community_id = inbound.community_id
            source_blocks = [
                render_source_block(
                    chunk,
                    index=i + 1,
                    total=chunk_count,
                    store=backend_store,
                    community_id=community_id,
                )
                for i, chunk in enumerate(result.source_chunks)
            ]
            messages = pack_drafts_into_messages(result.reply_text, source_blocks)
            total = len(messages)
            sent = 0
            for body in messages:
                try:
                    telegram_client.send_message(chat_id=inbound.external_chat_id, text=body)
                except Exception as exc:
                    log.warning(
                        "sources.delivery_failed chat_id=%s sent=%d total=%d error_class=%s",
                        inbound.external_chat_id,
                        sent,
                        total,
                        exc.__class__.__name__,
                    )
                    with contextlib.suppress(Exception):
                        telegram_client.send_message(
                            chat_id=inbound.external_chat_id,
                            text=(
                                f"Couldn't deliver all sources (sent {sent}/{total}). Try again."
                            ),
                        )
                    return {}
                sent += 1
            log.info(
                "sources.delivered chat_id=%s chunk_count=%d messages_sent=%d",
                inbound.external_chat_id,
                chunk_count,
                sent,
            )
            return {}
        return build_send_message_payload(inbound.external_chat_id, result.reply_text)


def _render_draft_block(
    draft: SourceMessage, *, store: AuthorDisplayInputStore, community_id: str
) -> str:
    """Render a draft as a chat block: header line + blank line + raw text.

    The header shows the adapter-resolved author display name (D-086 ladder:
    ``@username → first_name → opaque floor``), requester-``community_id``-scoped,
    in place of the raw opaque ``author_user_id`` — making ``/drafts`` consistent
    with ``/sources`` (D-098 milestone). Authorship is still carried only as the
    opaque ``author_user_id`` (I-6); the display name is non-authoritative.
    """
    author = _resolve_source_author_display(draft, store, community_id=community_id)
    header = f"\U0001f4dd {draft.created_at.date().isoformat()} · {author}"
    return f"{header}\n\n{draft.raw_text}"
