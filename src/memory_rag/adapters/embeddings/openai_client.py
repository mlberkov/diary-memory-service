"""OpenAI embeddings adapter (D-024).

Canonical Phase-3 contour: ``text-embedding-3-large`` at full 3072
dimensions. ``dimensions=3072`` is passed explicitly in the request even
though it is the native default — the request contract is self-documenting.

Provider hardening (R-9): the SDK client is built with an explicit per-attempt
``timeout`` and ``max_retries=0`` (the adapter's own bounded loop is the single
retry authority), and ``embed`` runs the API call through
:func:`~memory_rag.adapters.resilience.run_with_retries` with rate-limit-aware
backoff (``Retry-After`` honored via ``extract_retry_after_seconds``). On
exhausted or non-retryable failure the original SDK exception is re-raised —
``embed`` introduces no exception type of its own, so ``DomainService`` still
flips ``embedding_status='failed'`` (A-35).

Domain code only sees ``EmbeddingClient``; the SDK lives behind this
adapter (Invariant I-11).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from memory_rag.adapters.resilience import (
    RetryPolicy,
    classify_openai_error,
    extract_retry_after_seconds,
    run_with_retries,
)
from memory_rag.logging import get_logger

if TYPE_CHECKING:
    from openai import OpenAI

_log = get_logger(__name__)


class OpenAIEmbeddingClient:
    """Sync OpenAI embeddings provider (D-024)."""

    def __init__(
        self,
        api_key: str,
        *,
        model_name: str = "text-embedding-3-large",
        dimension: int = 3072,
        retry_policy: RetryPolicy,
        _client: Any = None,
    ) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for the OpenAI embedding backend")
        if dimension <= 0:
            raise ValueError(f"dimension must be positive, got {dimension}")
        self._model_name = model_name
        self._dimension = dimension
        self._retry_policy = retry_policy

        self._client: OpenAI
        if _client is not None:
            self._client = _client
        else:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=api_key,
                timeout=retry_policy.timeout_seconds,
                max_retries=0,
            )

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        def _call() -> list[list[float]]:
            response = self._client.embeddings.create(
                model=self._model_name,
                input=texts,
                dimensions=self._dimension,
            )
            return [item.embedding for item in response.data]

        vectors = run_with_retries(
            _call,
            policy=self._retry_policy,
            classify=classify_openai_error,
            retry_after=extract_retry_after_seconds,
            label="openai.embeddings",
            logger=_log,
        )
        if len(vectors) != len(texts):
            raise RuntimeError(f"OpenAI returned {len(vectors)} embeddings for {len(texts)} inputs")
        for vec in vectors:
            if len(vec) != self._dimension:
                raise RuntimeError(
                    f"OpenAI returned vector of dim {len(vec)}, expected {self._dimension}"
                )
        return [list(v) for v in vectors]
