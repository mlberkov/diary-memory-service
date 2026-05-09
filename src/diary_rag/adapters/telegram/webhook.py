"""Telegram webhook endpoint.

Validates the ``X-Telegram-Bot-Api-Secret-Token`` header (fail-closed),
parses the leading command, hands a channel-neutral
:class:`InboundMessage` to the :class:`Dispatcher`, and returns a
``sendMessage`` payload as the webhook response body.
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
from diary_rag.core.routing import InboundMessage
from diary_rag.logging import get_logger
from diary_rag.services import Dispatcher

log = get_logger(__name__)

_dispatcher = Dispatcher()


def get_dispatcher() -> Dispatcher:
    return _dispatcher


def _verify_secret(expected: str, provided: str | None) -> None:
    if not expected or provided is None:
        raise HTTPException(status_code=401, detail="invalid webhook secret")
    if not secrets.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="invalid webhook secret")


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

        route, payload = parse_command(message.text)
        inbound = InboundMessage(
            external_message_id=str(message.message_id),
            external_chat_id=str(message.chat.id),
            external_user_id=str(message.from_.id),
            text=message.text or "",
            route=route,
            received_at=datetime.fromtimestamp(message.date, tz=UTC),
            payload=payload,
        )

        result = dispatcher.dispatch(inbound)
        log.info(
            "telegram.webhook update_id=%s route=%s",
            update.update_id,
            result.route.value,
        )
        return build_send_message_payload(inbound.external_chat_id, result.reply_text)
