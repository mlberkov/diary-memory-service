"""Note parser.

Strict ISO ``YYYY-MM-DD`` on the first non-empty line of the payload;
everything after the date line is the note body, kept as one logical
unit (Invariant I-5 / D-106) — newlines inside a ``/note`` are content
structure, not event separators, and never split the note. Returns
``None`` when the first non-empty line is not an ISO date — the service
layer turns that into an explicit ``INVALID_INPUT`` fallback rather than
inventing a date.

``normalize_iso_date_token`` is an additive helper used by the explicit
``/note`` dispatcher path to accept a small whitelist of near-ISO forms
and rewrite them to canonical ``YYYY-MM-DD`` before the strict parser
runs. DD-first inputs are interpreted as DD/MM/YYYY by intentional
product convention (e.g. ``05/09/2026`` → ``2026-09-05``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class ParsedNote:
    """Result of a successful parse: a date and the note body that follows.

    ``body`` is the single logical unit after the date line (the non-empty
    body lines joined by ``\\n``); it is ``""`` for a date-only note. Per
    Invariant I-5 / D-106 the body is never split into per-line events.
    """

    note_date: date
    body: str
    first_line: str


def _split_non_empty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _parse_iso_date(token: str) -> date | None:
    try:
        return date.fromisoformat(token)
    except ValueError:
        return None


_YYYY_FIRST_RE = re.compile(r"^(\d{4})([-/.])(\d{2})\2(\d{2})$")
_DD_FIRST_RE = re.compile(r"^(\d{2})([-/.])(\d{2})\2(\d{4})$")


def normalize_iso_date_token(token: object) -> str | None:
    """Return canonical ``YYYY-MM-DD`` for a whitelisted near-ISO token, else ``None``.

    Accepted forms (zero-padded only): ``YYYY-MM-DD``, ``YYYY/MM/DD``,
    ``YYYY.MM.DD``, ``DD-MM-YYYY``, ``DD/MM/YYYY``, ``DD.MM.YYYY``.
    DD-first inputs are read as DD/MM/YYYY by product convention, so
    ``05/09/2026`` always becomes ``2026-09-05``. Unpadded forms
    (``2026-5-9``), mixed separators, natural-language dates, and
    impossible calendar dates are rejected.
    """
    if not isinstance(token, str):
        return None
    s = token.strip()
    if (m := _YYYY_FIRST_RE.match(s)) is not None:
        year, month, day = m.group(1), m.group(3), m.group(4)
    elif (m := _DD_FIRST_RE.match(s)) is not None:
        day, month, year = m.group(1), m.group(3), m.group(4)
    else:
        return None
    candidate = f"{year}-{month}-{day}"
    if _parse_iso_date(candidate) is None:
        return None
    return candidate


def parse_note(payload: str) -> ParsedNote | None:
    """Parse ``payload`` into ``(note_date, body)``.

    The first non-empty line must be an ISO ``YYYY-MM-DD`` date. Everything
    after it is the note body — the remaining non-empty lines joined by
    ``\\n`` into one logical unit (Invariant I-5 / D-106), never split into
    per-line events. A date-only note has an empty ``body``.
    """
    lines = _split_non_empty_lines(payload or "")
    if not lines:
        return None

    first_line = lines[0]
    parsed_date = _parse_iso_date(first_line)
    if parsed_date is None:
        return None

    body = "\n".join(lines[1:])
    return ParsedNote(note_date=parsed_date, body=body, first_line=first_line)
