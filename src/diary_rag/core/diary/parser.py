"""Diary entry parser.

Strict ISO ``YYYY-MM-DD`` on the first non-empty line of the payload;
remaining non-empty lines become events. Returns ``None`` when the
first non-empty line is not an ISO date — the service layer turns that
into an explicit ``INVALID_INPUT`` fallback rather than inventing a date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class ParsedEntry:
    """Result of a successful parse: a date and the event lines that follow."""

    entry_date: date
    events: list[str]
    first_line: str


def _split_non_empty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _parse_iso_date(token: str) -> date | None:
    try:
        return date.fromisoformat(token)
    except ValueError:
        return None


def parse_diary_entry(payload: str) -> ParsedEntry | None:
    """Parse ``payload`` into ``(entry_date, events)``.

    The first non-empty line must be an ISO ``YYYY-MM-DD`` date. The
    remaining non-empty lines become events, in order, one event per
    line (Invariant I-5).
    """
    lines = _split_non_empty_lines(payload or "")
    if not lines:
        return None

    first_line = lines[0]
    parsed_date = _parse_iso_date(first_line)
    if parsed_date is None:
        return None

    return ParsedEntry(entry_date=parsed_date, events=lines[1:], first_line=first_line)
