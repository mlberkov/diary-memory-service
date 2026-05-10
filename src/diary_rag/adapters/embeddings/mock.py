"""Deterministic mock embedding provider.

Used by every automated test by default and by any boot that runs
without ``OPENAI_API_KEY``. The ``model_name`` is the literal string
``"mock"`` — provider provenance in rows and logs must stay honest
(D-024). The ``dimension`` mirrors the production contour (3072) so
schema, pgvector binding, and boot gates exercise the same shape they
will in production.

Determinism: same text → same vector. Achieved with a SHA-256 seed of
the input text, used to drive a ``random.Random`` instance that fills
``dimension`` floats in ``[-1.0, 1.0)``. No external state.
"""

from __future__ import annotations

import hashlib
import random


class MockEmbeddingClient:
    """In-process deterministic embedding stand-in (D-024)."""

    def __init__(self, dimension: int = 3072) -> None:
        if dimension <= 0:
            raise ValueError(f"dimension must be positive, got {dimension}")
        self._dimension = dimension

    @property
    def model_name(self) -> str:
        return "mock"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:8], "big", signed=False)
        rng = random.Random(seed)
        return [rng.uniform(-1.0, 1.0) for _ in range(self._dimension)]
