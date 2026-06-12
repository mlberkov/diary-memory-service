"""MockQueryRewriter behavior (RC-3, D-108).

The mock is the test/dev default behind ``CLASSIFIER_BACKEND=mock`` (the
rewriter rides the classifier contour). Identity rewrite by default;
constructor-steerable; honest mock provenance (``model_name="mock"``,
``latency_ms=0``); never emits ``subject_scope`` — no subject-name
vocabulary exists to map onto (see ``docs/assumptions.md``).
"""

from __future__ import annotations

import json
from datetime import date

from memory_rag.adapters.chat_routing import MockQueryRewriter
from memory_rag.core.domain import DateRange

_TODAY = date(2026, 6, 12)


def test_default_is_an_identity_rewrite_with_no_date_range() -> None:
    rewrite = MockQueryRewriter().rewrite("what games suit him", today=_TODAY)
    assert rewrite.retrieval_query == "what games suit him"
    assert rewrite.date_range is None
    assert rewrite.subject_scope is None
    assert rewrite.model_name == "mock"
    assert rewrite.latency_ms == 0


def test_constructor_steering_rewrites_query_and_range() -> None:
    rng = DateRange(start=date(2026, 5, 1), end=date(2026, 5, 31))
    rewriter = MockQueryRewriter(rewrite_to="games", date_range=rng)
    rewrite = rewriter.rewrite("what games suit him these days?", today=_TODAY)
    assert rewrite.retrieval_query == "games"
    assert rewrite.date_range == rng
    assert rewrite.subject_scope is None


def test_raw_output_is_a_deterministic_tool_shaped_object() -> None:
    rng = DateRange(start=date(2026, 5, 1), end=date(2026, 5, 31))
    rewrite = MockQueryRewriter(rewrite_to="games", date_range=rng).rewrite("q", today=_TODAY)
    assert json.loads(rewrite.raw_output) == {
        "retrieval_query": "games",
        "date_from": "2026-05-01",
        "date_to": "2026-05-31",
    }
    # Determinism: same inputs, same bytes.
    again = MockQueryRewriter(rewrite_to="games", date_range=rng).rewrite("q", today=_TODAY)
    assert again.raw_output == rewrite.raw_output


def test_open_ended_range_omits_the_absent_bound() -> None:
    rewrite = MockQueryRewriter(date_range=DateRange(start=date(2026, 5, 1))).rewrite(
        "q", today=_TODAY
    )
    assert json.loads(rewrite.raw_output) == {
        "retrieval_query": "q",
        "date_from": "2026-05-01",
    }
