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

import secrets
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException

from diary_rag.adapters.telegram.commands import parse_command
from diary_rag.adapters.telegram.models import TelegramUpdate
from diary_rag.adapters.telegram.reply import build_send_message_payload
from diary_rag.config import Settings, get_settings
from diary_rag.core.routing import InboundMessage, RouteKind, RouteSource
from diary_rag.core.routing.classifier import classify_plain_text
from diary_rag.logging import get_logger
from diary_rag.services import DiaryService, Dispatcher, QueryService
from diary_rag.storage.mock import MockDiaryStore
from diary_rag.storage.repository import DiaryRepository

log = get_logger(__name__)

_dispatcher: Dispatcher | None = None


def _build_store(settings: Settings) -> DiaryRepository:
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
        _dispatcher = Dispatcher(DiaryService(store), QueryService(store))
        log.info("dispatcher.built storage_backend=%s", settings.storage_backend)
    return _dispatcher


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
        x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        _verify_secret(settings.telegram_webhook_secret, x_telegram_bot_api_secret_token)

        message = update.message
        if message is None:
            log.info("telegram.webhook update_id=%s no_message=true", update.update_id)
            return {}

        route, payload, route_source, confidence = _resolve_route(message.text)
        inbound = InboundMessage(
            external_message_id=str(message.message_id),
            external_chat_id=str(message.chat.id),
            external_user_id=str(message.from_.id),
            text=message.text or "",
            route=route,
            received_at=datetime.fromtimestamp(message.date, tz=UTC),
            route_source=route_source,
            payload=payload,
        )

        result = dispatcher.dispatch(inbound)
        log.info(
            "telegram.webhook update_id=%s route=%s route_source=%s confidence=%s",
            update.update_id,
            result.route.value,
            route_source,
            confidence or "n/a",
        )
        return build_send_message_payload(inbound.external_chat_id, result.reply_text)
