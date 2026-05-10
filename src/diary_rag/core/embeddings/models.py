"""Embedding-domain entities and per-chunk status.

``EmbeddingRecord`` is the TechSpec §5 entity that the storage layer
persists for each ``(chunk_id, model_name)`` pair: it carries the
provider provenance (``model_name``, ``dimension``) explicitly so a
future re-embedding under a different model can coexist with old rows
during a transition without a schema change.

``EmbeddingStatus`` lives on ``EventChunk`` so the operator can see, by
plain SQL, which chunks finished embedding and which fell back to
``failed`` (D-024, A-35: failed chunks persist and stay failed until a
future reconciliation job; replay does not retry).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class EmbeddingStatus(StrEnum):
    """Per-chunk progress of the embedding step.

    Transitions:
        * ``pending`` — chunk row was just committed; embedding has not run yet.
        * ``ready``   — an ``EmbeddingRecord`` was persisted for this chunk.
        * ``failed``  — the embedding call raised; the chunk is intact, the
          record was not written, and the row is observable by SQL so a
          future reconciliation job (Phase 6) can pick it up.
    """

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class EmbeddingRecord:
    """A single embedding for a single chunk under a single model.

    ``UNIQUE (chunk_id, model_name)`` at the storage layer is what makes
    a future model migration cheap: the new row coexists with the old
    one and the read path can choose which model to use.
    """

    embedding_record_id: str
    chunk_id: str
    source_message_id: str
    family_id: str
    model_name: str
    dimension: int
    embedding: list[float]
    created_at: datetime
