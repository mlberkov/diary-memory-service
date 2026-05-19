"""Pure-function unit tests for the OP-5.2a hit-rate / empty-rate metrics.

``hit_rate`` and ``empty_rate`` are pure functions over the harness's
per-query rows (D-057). These tests pin their exact semantics on
constructed inputs — unlike ``test_retrieval_harness_shape.py``, which
asserts report shape only. The semantics under test:

- ``hit_rate`` uses a **non-empty-gold denominator** — only queries with
  at least one expected chunk participate; negative queries are excluded.
- ``empty_rate`` divides by **all** queries — it counts queries whose
  fused result list came back empty, negatives included.
"""

from __future__ import annotations

import pytest

from memory_rag.eval.retrieval.harness import (
    PerQueryResult,
    empty_rate,
    hit_rate,
)


def _row(
    *,
    expected: tuple[str, ...],
    rank_fused: int | None,
    fused_ids: tuple[str, ...] = ("c1", "c2"),
) -> PerQueryResult:
    """Build a PerQueryResult exercising only the fields the metrics read.

    ``expected`` -> ``expected_chunk_ids``; ``rank_fused`` ->
    ``first_relevant_rank_in_fused``; ``fused_ids`` -> ``fused_top_k_ids``.
    Unrelated fields get inert placeholders.
    """
    return PerQueryResult(
        query="q",
        community_id="eval-community",
        expected_chunk_ids=expected,
        dense_top_k_ids=(),
        sparse_top_k_ids=(),
        fused_top_k_ids=fused_ids,
        first_relevant_rank_in_dense=None,
        first_relevant_rank_in_sparse=None,
        first_relevant_rank_in_fused=rank_fused,
        reciprocal_rank_in_fused=0.0 if rank_fused is None else 1.0 / rank_fused,
        recall_at_5=0.0,
        recall_at_10=0.0,
        recall_at_20=0.0,
    )


# ------------------------------------------------------------------ hit_rate


def test_hit_rate_all_answerable_queries_hit() -> None:
    rows = [
        _row(expected=("a",), rank_fused=1),
        _row(expected=("b", "c"), rank_fused=4),
    ]
    assert hit_rate(rows) == 1.0


def test_hit_rate_partial() -> None:
    rows = [
        _row(expected=("a",), rank_fused=1),
        _row(expected=("b",), rank_fused=None),
        _row(expected=("c",), rank_fused=7),
    ]
    assert hit_rate(rows) == pytest.approx(2 / 3)


def test_hit_rate_no_answerable_query_hits() -> None:
    rows = [
        _row(expected=("a",), rank_fused=None),
        _row(expected=("b",), rank_fused=None),
    ]
    assert hit_rate(rows) == 0.0


def test_hit_rate_excludes_negatives_from_denominator() -> None:
    # 3 answerable queries (2 hit), plus 2 negatives. Denominator is 3,
    # not 5 — negatives cannot hit and must not dilute the rate.
    rows = [
        _row(expected=("a",), rank_fused=1),
        _row(expected=("b",), rank_fused=3),
        _row(expected=("c",), rank_fused=None),
        _row(expected=(), rank_fused=None),
        _row(expected=(), rank_fused=None),
    ]
    assert hit_rate(rows) == pytest.approx(2 / 3)


def test_hit_rate_all_negative_set_is_zero() -> None:
    rows = [
        _row(expected=(), rank_fused=None),
        _row(expected=(), rank_fused=None),
    ]
    assert hit_rate(rows) == 0.0


def test_hit_rate_empty_report_is_zero() -> None:
    assert hit_rate([]) == 0.0


# ---------------------------------------------------------------- empty_rate


def test_empty_rate_no_empty_fused_lists() -> None:
    rows = [
        _row(expected=("a",), rank_fused=1, fused_ids=("c1",)),
        _row(expected=("b",), rank_fused=None, fused_ids=("c2", "c3")),
    ]
    assert empty_rate(rows) == 0.0


def test_empty_rate_some_empty() -> None:
    rows = [
        _row(expected=("a",), rank_fused=1, fused_ids=("c1",)),
        _row(expected=("b",), rank_fused=None, fused_ids=()),
        _row(expected=("c",), rank_fused=None, fused_ids=()),
        _row(expected=("d",), rank_fused=2, fused_ids=("c4",)),
    ]
    assert empty_rate(rows) == pytest.approx(0.5)


def test_empty_rate_all_empty() -> None:
    rows = [
        _row(expected=("a",), rank_fused=None, fused_ids=()),
        _row(expected=("b",), rank_fused=None, fused_ids=()),
    ]
    assert empty_rate(rows) == 1.0


def test_empty_rate_counts_negatives_in_denominator() -> None:
    # All queries count toward empty_rate, negatives included: 1 empty
    # fused list out of 4 total queries (2 answerable + 2 negative).
    rows = [
        _row(expected=("a",), rank_fused=1, fused_ids=("c1",)),
        _row(expected=("b",), rank_fused=2, fused_ids=("c2",)),
        _row(expected=(), rank_fused=None, fused_ids=("c3",)),
        _row(expected=(), rank_fused=None, fused_ids=()),
    ]
    assert empty_rate(rows) == pytest.approx(0.25)


def test_empty_rate_empty_report_is_zero() -> None:
    assert empty_rate([]) == 0.0
