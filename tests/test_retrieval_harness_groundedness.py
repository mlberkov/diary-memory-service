"""Pure-function unit tests for the OP-5.2b groundedness-proxy metric.

``is_grounded`` / ``groundedness_rate`` / ``fallback_mode_counts`` are pure
functions in the harness module (D-058). These tests pin their exact
semantics on constructed inputs — unlike
``test_retrieval_harness_shape.py``, which asserts report shape only. The
semantics under test:

- ``is_grounded`` is the documented fallback-derived proxy mapping
  (OP-5.2b / D-058): ``NONE`` / ``WEAK_EVIDENCE`` / ``AMBIGUOUS`` are
  grounded; ``NO_EVIDENCE`` / ``PROVIDER_UNAVAILABLE`` / ``PARSE_FAILURE``
  are **not** — the I-9 citation-subset violation contour is folded into
  ``PARSE_FAILURE`` and remains ungrounded (guardrail).
- ``groundedness_rate`` uses a **non-empty-gold (answerable) denominator**
  — negatives are excluded even when their ``grounded`` flag differs.
- ``fallback_mode_counts`` divides by **all** rows (negatives included).
"""

from __future__ import annotations

import pytest

from memory_rag.core.domain import FallbackMode
from memory_rag.eval.retrieval.harness import (
    PerAnswerResult,
    fallback_mode_counts,
    groundedness_rate,
    is_grounded,
)


def _row(
    *,
    answerable: bool,
    fallback: FallbackMode,
    grounded: bool | None = None,
    context_chunk_count: int = 0,
) -> PerAnswerResult:
    """Build a PerAnswerResult exercising only the fields the metrics read.

    ``grounded`` defaults to ``is_grounded(fallback)`` so the fixture row
    is consistent with the documented projection; individual tests can
    override it to exercise an inconsistent row if needed.
    """
    return PerAnswerResult(
        query="q",
        community_id="eval-community",
        answerable=answerable,
        fallback_mode=fallback.value,
        context_chunk_count=context_chunk_count,
        grounded=is_grounded(fallback) if grounded is None else grounded,
    )


# ------------------------------------------------------------ is_grounded


@pytest.mark.parametrize(
    "fallback",
    [FallbackMode.NONE, FallbackMode.WEAK_EVIDENCE, FallbackMode.AMBIGUOUS],
)
def test_is_grounded_true_for_evidence_backed_contours(fallback: FallbackMode) -> None:
    """The three contours that carry non-empty cited_chunk_ids ⊆ context."""
    assert is_grounded(fallback) is True


@pytest.mark.parametrize(
    "fallback",
    [
        FallbackMode.NO_EVIDENCE,
        FallbackMode.PROVIDER_UNAVAILABLE,
        FallbackMode.PARSE_FAILURE,
    ],
)
def test_is_grounded_false_for_ungrounded_contours(fallback: FallbackMode) -> None:
    """Guardrail: PARSE_FAILURE (catches FabricatedCitationError — the I-9
    citation-subset violation contour) and PROVIDER_UNAVAILABLE must never
    be counted as grounded; NO_EVIDENCE (empty retrieval or LLM-declared
    no_evidence) is correctly ungrounded."""
    assert is_grounded(fallback) is False


def test_is_grounded_covers_every_fallback_mode() -> None:
    """Future-proofing: any new ``FallbackMode`` member forces a deliberate
    proxy-mapping decision instead of silently defaulting one way."""
    for mode in FallbackMode:
        result = is_grounded(mode)
        assert isinstance(result, bool)


# ---------------------------------------------------- groundedness_rate


def test_groundedness_rate_all_answerable_grounded() -> None:
    rows = [
        _row(answerable=True, fallback=FallbackMode.NONE),
        _row(answerable=True, fallback=FallbackMode.WEAK_EVIDENCE),
    ]
    assert groundedness_rate(rows) == 1.0


def test_groundedness_rate_partial() -> None:
    rows = [
        _row(answerable=True, fallback=FallbackMode.NONE),
        _row(answerable=True, fallback=FallbackMode.NO_EVIDENCE),
        _row(answerable=True, fallback=FallbackMode.AMBIGUOUS),
    ]
    assert groundedness_rate(rows) == pytest.approx(2 / 3)


def test_groundedness_rate_none_grounded() -> None:
    rows = [
        _row(answerable=True, fallback=FallbackMode.NO_EVIDENCE),
        _row(answerable=True, fallback=FallbackMode.PARSE_FAILURE),
        _row(answerable=True, fallback=FallbackMode.PROVIDER_UNAVAILABLE),
    ]
    assert groundedness_rate(rows) == 0.0


def test_groundedness_rate_excludes_negatives_from_denominator() -> None:
    # 3 answerable queries (2 grounded), plus 2 negatives — including a
    # negative whose retrieval happened to surface chunks and produce a
    # ``confident`` mock answer (grounded=True on that row). The negative
    # must not enter the denominator and must not inflate the rate.
    rows = [
        _row(answerable=True, fallback=FallbackMode.NONE),
        _row(answerable=True, fallback=FallbackMode.NONE),
        _row(answerable=True, fallback=FallbackMode.NO_EVIDENCE),
        _row(answerable=False, fallback=FallbackMode.NONE),
        _row(answerable=False, fallback=FallbackMode.NO_EVIDENCE),
    ]
    assert groundedness_rate(rows) == pytest.approx(2 / 3)


def test_groundedness_rate_all_negative_set_is_zero() -> None:
    rows = [
        _row(answerable=False, fallback=FallbackMode.NO_EVIDENCE),
        _row(answerable=False, fallback=FallbackMode.NONE),
    ]
    assert groundedness_rate(rows) == 0.0


def test_groundedness_rate_empty_report_is_zero() -> None:
    assert groundedness_rate([]) == 0.0


# --------------------------------------------------- fallback_mode_counts


def test_fallback_mode_counts_counts_every_row_including_negatives() -> None:
    rows = [
        _row(answerable=True, fallback=FallbackMode.NONE),
        _row(answerable=True, fallback=FallbackMode.NONE),
        _row(answerable=True, fallback=FallbackMode.WEAK_EVIDENCE),
        _row(answerable=False, fallback=FallbackMode.NO_EVIDENCE),
    ]
    counts = fallback_mode_counts(rows)
    assert counts == {"none": 2, "weak_evidence": 1, "no_evidence": 1}
    # Sums to ``len(rows)`` so the breakdown is a complete partition.
    assert sum(counts.values()) == len(rows)


def test_fallback_mode_counts_empty_report() -> None:
    assert fallback_mode_counts([]) == {}
