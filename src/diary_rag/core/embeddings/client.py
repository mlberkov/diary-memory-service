"""``EmbeddingClient`` Protocol (D-024).

Every embedding provider — the real OpenAI one and the deterministic
test mock — exposes ``model_name``, ``dimension``, and a sync
``embed(texts) -> list[list[float]]``. Domain code depends only on this
Protocol, never on a provider SDK (Invariant I-11).

The boot-time health gate (R-10) asserts the client's ``dimension`` and
``model_name`` match what config declares — a misconfigured pair must
abort startup rather than silently produce vectors of the wrong size.
"""

from __future__ import annotations

from typing import Protocol


class EmbeddingClient(Protocol):
    """Sync embedding provider seam used by ``DiaryService.ingest``."""

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...
