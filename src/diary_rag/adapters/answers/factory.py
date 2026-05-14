"""Single factory for the configured :class:`ChatClient`.

Boot gate (R-10) and request-path wiring (``get_dispatcher``) both go
through this function so they cannot disagree on backend or model name.
``chat_backend="openai"`` requires ``OPENAI_API_KEY`` and the canonical
``CHAT_MODEL`` (D-037); ``mock`` is the test/dev default and has no
external dependencies.
"""

from __future__ import annotations

from diary_rag.adapters.answers.mock import MockChatClient
from diary_rag.config import Settings
from diary_rag.core.answers import ChatClient


def build_chat_client(settings: Settings) -> ChatClient:
    if settings.chat_backend == "openai":
        from diary_rag.adapters.answers.openai_client import OpenAIChatClient

        return OpenAIChatClient(
            api_key=settings.openai_api_key,
            model_name=settings.chat_model,
        )
    return MockChatClient()
