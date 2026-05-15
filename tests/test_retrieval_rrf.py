"""Unit tests for service-layer Reciprocal Rank Fusion (Slice 3.3)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from diary_rag.core.domain.models import EventChunk
from diary_rag.core.embeddings.models import EmbeddingStatus
from diary_rag.services.retrieval import DEFAULT_RRF_K, reciprocal_rank_fusion


def _chunk(cid: str) -> EventChunk:
    return EventChunk(
        chunk_id=cid,
        diary_entry_id="e1",
        source_message_id="s1",
        family_id="fam-A",
        author_user_id="u1",
        entry_date=date(2026, 5, 11),
        event_index=0,
        chunk_text=f"chunk {cid}",
        created_at=datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC),
        embedding_status=EmbeddingStatus.READY,
    )


def test_single_leg_passes_through_order() -> None:
    a, b, c = _chunk("a"), _chunk("b"), _chunk("c")

    fused = reciprocal_rank_fusion([[a, b, c]], top_k=10)

    assert [h.chunk.chunk_id for h in fused] == ["a", "b", "c"]


def test_both_legs_agree_promotes_shared_top() -> None:
    a, b, c = _chunk("a"), _chunk("b"), _chunk("c")
    dense = [b, a, c]
    sparse = [b, c, a]

    fused = reciprocal_rank_fusion([dense, sparse], top_k=10)

    assert fused[0].chunk.chunk_id == "b"


def test_legs_disagree_uses_summed_reciprocal_rank() -> None:
    a, b, c = _chunk("a"), _chunk("b"), _chunk("c")
    dense = [a, b, c]
    sparse = [c, b, a]

    fused = reciprocal_rank_fusion([dense, sparse], top_k=10, k=DEFAULT_RRF_K)

    # a and c are symmetric (each is rank 1 in one list, rank 3 in the other);
    # b is rank 2 in both. The convexity of 1/(k+rank) means rank-1 + rank-3
    # beats two rank-2 entries by a hair: 1/61 + 1/63 > 2/62.
    score_a = 1.0 / (60 + 1) + 1.0 / (60 + 3)
    score_b = 2.0 * (1.0 / (60 + 2))
    score_c = 1.0 / (60 + 3) + 1.0 / (60 + 1)
    assert score_a == score_c
    assert score_a > score_b
    # First-appearance order resolves the a/c tie: dense lists a before c.
    assert [h.chunk.chunk_id for h in fused] == ["a", "c", "b"]


def test_both_legs_agree_promotes_shared_top_via_doubled_rank_one() -> None:
    """When both legs put the same chunk at rank 1, it dominates regardless
    of how the other chunks order."""
    a, b, c = _chunk("a"), _chunk("b"), _chunk("c")
    dense = [a, b, c]
    sparse = [a, c, b]

    fused = reciprocal_rank_fusion([dense, sparse], top_k=10, k=DEFAULT_RRF_K)

    assert fused[0].chunk.chunk_id == "a"


def test_top_k_truncates_output() -> None:
    chunks = [_chunk(c) for c in "abcdef"]

    fused = reciprocal_rank_fusion([chunks], top_k=3)

    assert [h.chunk.chunk_id for h in fused] == ["a", "b", "c"]


def test_empty_inputs_return_empty() -> None:
    assert reciprocal_rank_fusion([], top_k=5) == []
    assert reciprocal_rank_fusion([[], []], top_k=5) == []


def test_zero_top_k_returns_empty_even_with_inputs() -> None:
    a, b = _chunk("a"), _chunk("b")
    assert reciprocal_rank_fusion([[a, b]], top_k=0) == []


def test_one_empty_leg_is_passthrough_of_other() -> None:
    a, b = _chunk("a"), _chunk("b")
    fused = reciprocal_rank_fusion([[a, b], []], top_k=5)
    assert [h.chunk.chunk_id for h in fused] == ["a", "b"]


def test_disjoint_legs_interleave_by_rank() -> None:
    a, b, c, d = _chunk("a"), _chunk("b"), _chunk("c"), _chunk("d")
    dense = [a, b]
    sparse = [c, d]

    fused = reciprocal_rank_fusion([dense, sparse], top_k=10)

    # Rank-1 of each leg outranks rank-2 of either: a and c tie at score 1/(60+1),
    # then b and d tie at 1/(60+2). Tie-break uses first-appearance order: a, c, b, d.
    assert [h.chunk.chunk_id for h in fused] == ["a", "c", "b", "d"]


def test_invalid_k_raises() -> None:
    a = _chunk("a")
    with pytest.raises(ValueError, match="k must be positive"):
        reciprocal_rank_fusion([[a]], top_k=5, k=0)


def test_fused_score_is_monotone_non_increasing() -> None:
    """Output ordering is best-first by fused score; ties resolve deterministically.

    The score field is the canonical merged-row score persisted to
    ``retrieval_hits`` in Slice 3.5.
    """
    chunks = [_chunk(c) for c in "abcdef"]
    dense = chunks
    sparse = list(reversed(chunks))

    fused = reciprocal_rank_fusion([dense, sparse], top_k=6)

    scores = [h.score for h in fused]
    assert scores == sorted(scores, reverse=True)
    assert all(s > 0.0 for s in scores)
