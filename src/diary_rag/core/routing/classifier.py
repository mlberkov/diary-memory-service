"""Heuristic classifier for plain-text Telegram messages.

When the user sends a message without ``/entry`` or ``/ask``, the webhook
calls :func:`classify_plain_text` to pick a destination. The result is
one of three routes:

- ``RouteKind.ENTRY``  — first non-empty line is an ISO ``YYYY-MM-DD``
  date and the body has at least one event line. Detected by reusing
  :func:`diary_rag.core.diary.parser.parse_diary_entry` so the ISO-only
  rule (assumption A-28) lives in one place.
- ``RouteKind.ASK``    — the text ends with ``?`` or its first token is
  in a fixed interrogative/imperative set.
- ``RouteKind.CLARIFY`` — anything else. The dispatcher replies with a
  fixed clarification message rather than guessing (Decision D-006,
  runtime invariant R-11).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from diary_rag.core.diary.parser import parse_diary_entry
from diary_rag.core.routing.models import RouteKind

Confidence = Literal["high", "low"]

_QUESTION_WORDS: frozenset[str] = frozenset(
    {
        "what",
        "when",
        "who",
        "where",
        "why",
        "how",
        "which",
        "did",
        "do",
        "does",
        "is",
        "are",
        "was",
        "were",
        "can",
        "could",
        "would",
        "should",
        "show",
        "tell",
        "find",
        "list",
        "give",
        "remind",
    }
)
_TRAILING_PUNCT = ".,!?;:\"')]}"


@dataclass(frozen=True, slots=True)
class ClassifiedRoute:
    route: RouteKind
    payload: str
    confidence: Confidence
    reason: str


def classify_plain_text(text: str) -> ClassifiedRoute:
    stripped = (text or "").strip()
    if not stripped:
        return ClassifiedRoute(RouteKind.CLARIFY, text or "", "low", "empty_after_strip")

    parsed = parse_diary_entry(stripped)
    if parsed is not None:
        if parsed.events:
            return ClassifiedRoute(RouteKind.ENTRY, text, "high", "first_line_iso_date_with_events")
        return ClassifiedRoute(RouteKind.CLARIFY, text, "low", "first_line_iso_date_no_events")

    if stripped.endswith("?"):
        return ClassifiedRoute(RouteKind.ASK, text, "high", "question_mark_terminator")

    first_token = stripped.split(None, 1)[0].rstrip(_TRAILING_PUNCT).lower()
    if first_token in _QUESTION_WORDS:
        return ClassifiedRoute(
            RouteKind.ASK, text, "high", "interrogative_or_imperative_first_token"
        )

    return ClassifiedRoute(RouteKind.CLARIFY, text, "low", "plain_text_no_signal")
