"""Single factory for the configured :class:`ChatClient` (Slice 4.3a).

Boot gate (R-10) and request-path wiring (``get_dispatcher``) both go
through this function so they cannot disagree on backend or model name.
``chat_backend`` is currently a one-value Literal (``"mock"``); real
provider adapters land in a later packet.
"""

from __future__ import annotations

from diary_rag.adapters.answers.mock import MockChatClient
from diary_rag.config import Settings
from diary_rag.core.answers import ChatClient


def build_chat_client(settings: Settings) -> ChatClient:
    if settings.chat_backend == "mock":
        return MockChatClient()
    raise ValueError(f"unsupported chat_backend: {settings.chat_backend!r}")
