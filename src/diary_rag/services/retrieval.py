"""Service-layer Reciprocal Rank Fusion (Slice 3.3, baseline hybrid).

Pure function over independently-ranked candidate lists. Each list is
treated as best-first; ranks are 1-based when fed into the RRF formula
``score = sum_l 1 / (k + rank_l)``. Score calibration between dense
(cosine distance) and sparse (FTS rank) is the bug RRF was designed to
avoid — only positions matter.

The merge lives in the service layer because the two legs are produced
independently by ``SearchRepository.dense_candidates`` and
``sparse_candidates``; there is no backend-specific logic here.

Slice 3.5 surfaces the fused score per chunk as ``FusedHit.score`` so
``QueryService`` can persist the merged-row scores in a ``RetrievalHit``
trace; the formula and tie-breaking rule are unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from diary_rag.core.domain.models import EventChunk

DEFAULT_RRF_K = 60


@dataclass(frozen=True, slots=True)
class FusedHit:
    """A merged chunk plus its fused RRF score."""

    chunk: EventChunk
    score: float


def reciprocal_rank_fusion(
    leg_rankings: Sequence[Sequence[EventChunk]],
    *,
    top_k: int,
    k: int = DEFAULT_RRF_K,
) -> list[FusedHit]:
    """Fuse independently-ranked candidate lists by Reciprocal Rank Fusion.

    Ties (same fused score) break on first-appearance order across the
    input lists so the output is deterministic without depending on
    backend-native score magnitudes.
    """
    if top_k <= 0:
        return []
    if k <= 0:
        raise ValueError(f"RRF k must be positive, got {k}")

    fused_score: dict[str, float] = {}
    chunks_by_id: dict[str, EventChunk] = {}
    first_seen: dict[str, int] = {}

    for ranking in leg_rankings:
        for rank, chunk in enumerate(ranking, start=1):
            fused_score[chunk.chunk_id] = fused_score.get(chunk.chunk_id, 0.0) + 1.0 / (k + rank)
            if chunk.chunk_id not in chunks_by_id:
                chunks_by_id[chunk.chunk_id] = chunk
                first_seen[chunk.chunk_id] = len(first_seen)

    ordered_ids = sorted(
        chunks_by_id.keys(),
        key=lambda cid: (-fused_score[cid], first_seen[cid]),
    )
    return [
        FusedHit(chunk=chunks_by_id[cid], score=fused_score[cid]) for cid in ordered_ids[:top_k]
    ]


__all__ = ["DEFAULT_RRF_K", "FusedHit", "reciprocal_rank_fusion"]
