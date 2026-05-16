"""Heuristic classifier unit tests.

Covers each classification rule in
``src/memory_rag/core/routing/classifier.py`` plus edge cases the
PRD heuristic does not address explicitly. Under the draft floor
(D-027 / R-13), any non-empty text that does not match the high-
confidence NOTE or ASK rules falls through to ``RouteKind.DRAFT``
so the dispatcher persists the raw text rather than discarding it.
``CLARIFY`` remains the empty/whitespace branch (defensive — the
webhook short-circuits empty text before reaching the classifier).
"""

from __future__ import annotations

import pytest

from memory_rag.core.routing import RouteKind
from memory_rag.core.routing.classifier import classify_plain_text


def test_dated_multi_line_classifies_as_note() -> None:
    result = classify_plain_text("2026-05-10\nLearned a new recipe\nWalked 5km")
    assert result.route is RouteKind.NOTE
    assert result.confidence == "high"
    assert result.reason == "first_line_iso_date_with_events"


def test_dated_with_leading_blank_lines_classifies_as_note() -> None:
    result = classify_plain_text("\n\n2026-05-10\nMorning routine")
    assert result.route is RouteKind.NOTE
    assert result.confidence == "high"


def test_question_mark_terminator_classifies_as_ask() -> None:
    result = classify_plain_text("recipe?")
    assert result.route is RouteKind.ASK
    assert result.confidence == "high"
    assert result.reason == "question_mark_terminator"


def test_interrogative_first_token_classifies_as_ask() -> None:
    result = classify_plain_text("what did I learn last week")
    assert result.route is RouteKind.ASK
    assert result.confidence == "high"
    assert result.reason == "interrogative_or_imperative_first_token"


def test_imperative_first_token_classifies_as_ask() -> None:
    result = classify_plain_text("show me the morning routines")
    assert result.route is RouteKind.ASK
    assert result.confidence == "high"


def test_first_token_case_normalized() -> None:
    result = classify_plain_text("WHAT did we do")
    assert result.route is RouteKind.ASK


def test_bare_iso_date_falls_through_to_draft_floor() -> None:
    result = classify_plain_text("2026-05-09")
    assert result.route is RouteKind.DRAFT
    assert result.confidence == "low"
    assert result.reason == "draft_floor_no_signal"


def test_malformed_date_attempt_falls_through_to_draft_floor() -> None:
    result = classify_plain_text("2026-5-9 walk")
    assert result.route is RouteKind.DRAFT
    assert result.confidence == "low"
    assert result.reason == "draft_floor_no_signal"


def test_relative_date_attempt_falls_through_to_draft_floor() -> None:
    result = classify_plain_text("yesterday I walked the dog")
    assert result.route is RouteKind.DRAFT
    assert result.confidence == "low"


def test_plain_statement_falls_through_to_draft_floor() -> None:
    result = classify_plain_text("recipe yesterday")
    assert result.route is RouteKind.DRAFT
    assert result.confidence == "low"
    assert result.reason == "draft_floor_no_signal"


def test_multi_line_without_date_falls_through_to_draft_floor() -> None:
    result = classify_plain_text("morning routine\nevening reading")
    assert result.route is RouteKind.DRAFT
    assert result.confidence == "low"


@pytest.mark.parametrize("text", ["", "   ", "\n\n", "\t\t"])
def test_empty_or_whitespace_classifies_as_clarify(text: str) -> None:
    result = classify_plain_text(text)
    assert result.route is RouteKind.CLARIFY
    assert result.confidence == "low"
    assert result.reason == "empty_after_strip"


def test_payload_preserves_original_text_for_dated_note() -> None:
    text = "2026-05-10\nLearned a new recipe"
    result = classify_plain_text(text)
    assert result.payload == text
