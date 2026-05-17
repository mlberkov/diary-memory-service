"""Single factory for the configured :class:`ChatClient`.

Boot gate (R-10) and request-path wiring (``get_dispatcher``) both go
through this function so they cannot disagree on backend or model name.
``chat_backend="openai"`` requires ``OPENAI_API_KEY`` and the canonical
``CHAT_MODEL`` (D-037); ``mock`` is the test/dev default and has no
external dependencies.
"""

from __future__ import annotations

from memory_rag.adapters.answers.mock import MockChatClient
from memory_rag.adapters.resilience import RetryPolicy
from memory_rag.config import Settings
from memory_rag.core.answers import ChatClient


def build_chat_client(settings: Settings) -> ChatClient:
    if settings.chat_backend == "openai":
        from memory_rag.adapters.answers.openai_client import OpenAIChatClient

        return OpenAIChatClient(
            api_key=settings.openai_api_key,
            model_name=settings.chat_model,
            retry_policy=RetryPolicy(
                timeout_seconds=settings.provider_timeout_seconds,
                max_attempts=settings.provider_max_attempts,
            ),
        )
    return MockChatClient()
