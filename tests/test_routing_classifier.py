"""Heuristic classifier unit tests.

Covers each classification rule in
``src/diary_rag/core/routing/classifier.py`` plus edge cases that the
PRD heuristic does not address explicitly: bare ISO date, malformed
date attempts, plain statement, multi-line non-dated text.
"""

from __future__ import annotations

import pytest

from diary_rag.core.routing import RouteKind
from diary_rag.core.routing.classifier import classify_plain_text


def test_dated_multi_line_classifies_as_entry() -> None:
    result = classify_plain_text("2026-05-10\nLearned a new recipe\nWalked 5km")
    assert result.route is RouteKind.ENTRY
    assert result.confidence == "high"
    assert result.reason == "first_line_iso_date_with_events"


def test_dated_with_leading_blank_lines_classifies_as_entry() -> None:
    result = classify_plain_text("\n\n2026-05-10\nMorning routine")
    assert result.route is RouteKind.ENTRY
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


def test_bare_iso_date_classifies_as_clarify() -> None:
    result = classify_plain_text("2026-05-09")
    assert result.route is RouteKind.CLARIFY
    assert result.confidence == "low"
    assert result.reason == "first_line_iso_date_no_events"


def test_malformed_date_attempt_classifies_as_clarify() -> None:
    result = classify_plain_text("2026-5-9 walk")
    assert result.route is RouteKind.CLARIFY
    assert result.confidence == "low"
    assert result.reason == "plain_text_no_signal"


def test_relative_date_attempt_classifies_as_clarify() -> None:
    result = classify_plain_text("yesterday I walked the dog")
    assert result.route is RouteKind.CLARIFY
    assert result.confidence == "low"


def test_plain_statement_classifies_as_clarify() -> None:
    result = classify_plain_text("recipe yesterday")
    assert result.route is RouteKind.CLARIFY
    assert result.confidence == "low"
    assert result.reason == "plain_text_no_signal"


def test_multi_line_without_date_classifies_as_clarify() -> None:
    result = classify_plain_text("morning routine\nevening reading")
    assert result.route is RouteKind.CLARIFY
    assert result.confidence == "low"


@pytest.mark.parametrize("text", ["", "   ", "\n\n", "\t\t"])
def test_empty_or_whitespace_classifies_as_clarify(text: str) -> None:
    result = classify_plain_text(text)
    assert result.route is RouteKind.CLARIFY
    assert result.confidence == "low"
    assert result.reason == "empty_after_strip"


def test_payload_preserves_original_text_for_dated_entry() -> None:
    text = "2026-05-10\nLearned a new recipe"
    result = classify_plain_text(text)
    assert result.payload == text
