"""Outbound Telegram Bot API client.

Telegram's webhook response body can deliver one ``method`` call inline,
but ``sendDocument`` with a freshly-generated binary payload requires a
multipart/form-data ``POST`` to ``api.telegram.org/bot<token>/sendDocument``.
``sendMessage`` outbound is needed for the ``/drafts`` recall (D-030)
when a multi-message split is forced or when the delivery is purely
outbound. This module owns both.

The :class:`TelegramClient` Protocol keeps the webhook handler
transport-agnostic so tests can inject a recording fake. The concrete
:class:`HttpxTelegramClient` performs both calls via ``httpx``;
``send_message`` uses a JSON body and intentionally omits ``parse_mode``
so user-supplied draft text passes through verbatim.
"""

from __future__ import annotations

from typing import Protocol

import httpx


class TelegramClient(Protocol):
    """Outbound Telegram Bot API surface used by the webhook adapter."""

    def send_document(
        self,
        *,
        chat_id: str,
        filename: str,
        content: bytes,
        media_type: str,
        caption: str | None = None,
    ) -> None: ...

    def send_message(self, *, chat_id: str, text: str) -> None: ...


class HttpxTelegramClient:
    """``httpx``-backed concrete client. Raises on non-2xx responses."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://api.telegram.org",
        timeout: float = 30.0,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def send_document(
        self,
        *,
        chat_id: str,
        filename: str,
        content: bytes,
        media_type: str,
        caption: str | None = None,
    ) -> None:
        if not self._token:
            raise RuntimeError("telegram bot token is not configured")
        url = f"{self._base_url}/bot{self._token}/sendDocument"
        data: dict[str, str] = {"chat_id": chat_id}
        if caption is not None:
            data["caption"] = caption
        files = {"document": (filename, content, media_type)}
        response = httpx.post(url, data=data, files=files, timeout=self._timeout)
        response.raise_for_status()

    def send_message(self, *, chat_id: str, text: str) -> None:
        if not self._token:
            raise RuntimeError("telegram bot token is not configured")
        url = f"{self._base_url}/bot{self._token}/sendMessage"
        response = httpx.post(
            url,
            json={"chat_id": chat_id, "text": text},
            timeout=self._timeout,
        )
        response.raise_for_status()
