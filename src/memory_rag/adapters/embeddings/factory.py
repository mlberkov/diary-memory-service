"""Single factory for the configured :class:`EmbeddingClient`.

Boot gate (R-10) and request-path wiring (``get_dispatcher``) both go
through this function so they cannot disagree on backend, model name,
or dimension. ``embedding_backend="openai"`` requires
``OPENAI_API_KEY``; ``mock`` is the test/dev default and has no
external dependencies.
"""

from __future__ import annotations

from memory_rag.adapters.embeddings.mock import MockEmbeddingClient
from memory_rag.adapters.resilience import RetryPolicy
from memory_rag.config import Settings
from memory_rag.core.embeddings import EmbeddingClient


def build_embedding_client(settings: Settings) -> EmbeddingClient:
    if settings.embedding_backend == "openai":
        from memory_rag.adapters.embeddings.openai_client import OpenAIEmbeddingClient

        return OpenAIEmbeddingClient(
            api_key=settings.openai_api_key,
            model_name=settings.embedding_model,
            dimension=settings.embedding_dimension,
            retry_policy=RetryPolicy(
                timeout_seconds=settings.provider_timeout_seconds,
                max_attempts=settings.provider_max_attempts,
                backoff_base_seconds=settings.provider_backoff_base_seconds,
                backoff_cap_seconds=settings.provider_backoff_cap_seconds,
            ),
        )
    return MockEmbeddingClient(dimension=settings.embedding_dimension)
