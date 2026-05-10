"""OpenAI embeddings adapter (D-024).

Canonical Phase-3 contour: ``text-embedding-3-large`` at full 3072
dimensions, single attempt, no retries (Phase 6 owns hardening, R-9).
``dimensions=3072`` is passed explicitly in the request even though it
is the native default — the request contract is self-documenting.

Domain code only sees ``EmbeddingClient``; the SDK lives behind this
adapter (Invariant I-11).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openai import OpenAI


class OpenAIEmbeddingClient:
    """Sync OpenAI embeddings provider (D-024)."""

    def __init__(
        self,
        api_key: str,
        *,
        model_name: str = "text-embedding-3-large",
        dimension: int = 3072,
    ) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for the OpenAI embedding backend")
        if dimension <= 0:
            raise ValueError(f"dimension must be positive, got {dimension}")
        from openai import OpenAI

        self._client: OpenAI = OpenAI(api_key=api_key)
        self._model_name = model_name
        self._dimension = dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client.embeddings.create(
            model=self._model_name,
            input=texts,
            dimensions=self._dimension,
        )
        vectors = [item.embedding for item in response.data]
        if len(vectors) != len(texts):
            raise RuntimeError(f"OpenAI returned {len(vectors)} embeddings for {len(texts)} inputs")
        for vec in vectors:
            if len(vec) != self._dimension:
                raise RuntimeError(
                    f"OpenAI returned vector of dim {len(vec)}, expected {self._dimension}"
                )
        return [list(v) for v in vectors]
