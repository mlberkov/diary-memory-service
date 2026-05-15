"""Channel-neutral context assembler (Slice 4.1).

Maps a persisted :class:`Query` plus the RRF-merged retrieval hits to an
:class:`AnswerContext` — the minimal payload every Phase-4 consumer
(answer prompt, chat-client adapter, ``AnswerTrace`` persistence,
citation rendering) will read.

Pure: no retrieval calls, no persistence, no providers. Order is the
order of ``merged`` (RRF rank with the deterministic tie-break already
applied in :func:`diary_rag.services.retrieval.reciprocal_rank_fusion`).
RRF merges by ``chunk_id`` upstream, so the assembler does no further
dedup. Family scoping is enforced upstream (R-3); the assembler does
not re-scope.

Date grouping and other presentation shapes are intentionally NOT
fields of :class:`AnswerContext` — they belong to consumers that need
them.
"""

from __future__ import annotations

from collections.abc import Sequence

from diary_rag.core.domain import AnswerContext, Query
from diary_rag.services.retrieval import FusedHit


def assemble_answer_context(query: Query, merged: Sequence[FusedHit]) -> AnswerContext:
    """Build an :class:`AnswerContext` from a query and RRF-merged hits."""
    return AnswerContext(
        query_id=query.query_id,
        query_text=query.query_text,
        ordered_chunks=tuple(h.chunk for h in merged),
        model_name=query.model_name,
        created_at=query.created_at,
    )


__all__ = ["assemble_answer_context"]
