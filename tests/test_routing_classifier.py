"""Plain-text classifier unit tests.

Covers :func:`memory_rag.core.routing.classifier.classify_plain_text`.
Per the D-078 contract (enforced in code by D-079), command-less plain
text routes only to the draft floor: any non-empty text falls through to
``RouteKind.DRAFT`` (reason ``draft_floor_no_signal``) so the dispatcher
persists the raw text rather than auto-promoting it to NOTE or ASK — those
lifecycles are reached only via the explicit ``/note`` / ``/ask`` commands.
``CLARIFY`` remains the empty/whitespace branch (defensive — the webhook
short-circuits empty text before reaching the classifier).
"""

from __future__ import annotations

import pytest

from memory_rag.core.routing import RouteKind
from memory_rag.core.routing.classifier import classify_plain_text


def test_dated_multi_line_falls_through_to_draft_floor() -> None:
    # Pre-D-079 this auto-promoted to NOTE; the dated-line heuristic is retired.
    result = classify_plain_text("2026-05-10\nLearned a new recipe\nWalked 5km")
    assert result.route is RouteKind.DRAFT
    assert result.confidence == "low"
    assert result.reason == "draft_floor_no_signal"


def test_dated_with_leading_blank_lines_falls_through_to_draft_floor() -> None:
    result = classify_plain_text("\n\n2026-05-10\nMorning routine")
    assert result.route is RouteKind.DRAFT
    assert result.confidence == "low"


def test_question_mark_terminator_falls_through_to_draft_floor() -> None:
    # Pre-D-079 this auto-routed to ASK; the question-shape heuristic is retired.
    result = classify_plain_text("recipe?")
    assert result.route is RouteKind.DRAFT
    assert result.confidence == "low"
    assert result.reason == "draft_floor_no_signal"


def test_interrogative_first_token_falls_through_to_draft_floor() -> None:
    result = classify_plain_text("what did I learn last week")
    assert result.route is RouteKind.DRAFT
    assert result.confidence == "low"
    assert result.reason == "draft_floor_no_signal"


def test_imperative_first_token_falls_through_to_draft_floor() -> None:
    result = classify_plain_text("show me the morning routines")
    assert result.route is RouteKind.DRAFT
    assert result.confidence == "low"


def test_first_token_case_does_not_route_to_ask() -> None:
    result = classify_plain_text("WHAT did we do")
    assert result.route is RouteKind.DRAFT


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


def test_payload_preserves_original_text_for_dated_draft() -> None:
    text = "2026-05-10\nLearned a new recipe"
    result = classify_plain_text(text)
    assert result.payload == text


@pytest.mark.parametrize(
    "text",
    [
        "what is phonemic awareness",
        "why doesn't he pronounce r?",
        "chat with me about books",
        "2026-05-10\nLearned a new recipe",
    ],
)
def test_plain_text_never_routes_to_chat(text: str) -> None:
    """RC-2 (D-108): routed chat is command-only — the heuristic
    plain-text classifier must never yield ``RouteKind.CHAT``."""
    result = classify_plain_text(text)
    assert result.route is not RouteKind.CHAT
