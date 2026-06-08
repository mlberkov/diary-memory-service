"""Pure parser tests for the note payload."""

from __future__ import annotations

from datetime import date

import pytest

from memory_rag.core.domain import parse_note
from memory_rag.core.domain.parser import normalize_iso_date_token


def test_parses_iso_date_and_body() -> None:
    # I-5 / D-106: the body after the date line is one logical unit; the
    # interior newline is preserved as content, never an event separator.
    parsed = parse_note("2026-05-09\nHad a calm morning\nTried a new book")
    assert parsed is not None
    assert parsed.note_date == date(2026, 5, 9)
    assert parsed.body == "Had a calm morning\nTried a new book"


def test_strips_blank_lines_in_body() -> None:
    parsed = parse_note("2026-05-09\n\nFirst event\n\nSecond event\n")
    assert parsed is not None
    assert parsed.body == "First event\nSecond event"


def test_skips_leading_blank_lines_before_date() -> None:
    parsed = parse_note("\n\n2026-05-09\nFirst event")
    assert parsed is not None
    assert parsed.note_date == date(2026, 5, 9)
    assert parsed.body == "First event"


def test_returns_none_when_first_line_not_iso_date() -> None:
    # Boundary pin (D-085): the parser stays strict ISO-only. The
    # "missing first-line date defaults to today" behavior lives in the
    # /note dispatcher seam, never in parse_note.
    assert parse_note("not-a-date\nfoo") is None
    assert parse_note("walk in park") is None


def test_returns_none_for_non_iso_locale_date() -> None:
    assert parse_note("09/05/2026\nfoo") is None


@pytest.mark.parametrize("payload", ["", "   ", "\n\n"])
def test_returns_none_for_empty_payload(payload: str) -> None:
    assert parse_note(payload) is None


def test_date_only_has_empty_body() -> None:
    parsed = parse_note("2026-05-09")
    assert parsed is not None
    assert parsed.note_date == date(2026, 5, 9)
    assert parsed.body == ""


# ---------------------------------------------------------------------------
# normalize_iso_date_token — six-form near-ISO whitelist used by the explicit
# /note dispatcher path. parse_note itself remains strict; these tests cover
# only the additive helper.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    ["2026-05-09", "2026/05/09", "2026.05.09", "09-05-2026", "09/05/2026", "09.05.2026"],
)
def test_normalize_accepts_six_whitelisted_forms(token: str) -> None:
    assert normalize_iso_date_token(token) == "2026-05-09"


@pytest.mark.parametrize("token", ["05-09-2026", "05/09/2026", "05.09.2026"])
def test_normalize_dd_first_is_always_dd_mm_yyyy_by_product_convention(token: str) -> None:
    # Convention pin: DD-first inputs are interpreted as DD/MM/YYYY regardless
    # of whether the first two numeric groups are <= 12. 05/09/2026 always
    # becomes 2026-09-05 (5 September 2026), never 2026-05-09 (9 May 2026).
    assert normalize_iso_date_token(token) == "2026-09-05"


@pytest.mark.parametrize(
    "token",
    [
        "2026-5-9",
        "2026/5/9",
        "2026.5.9",
        "9-5-2026",
        "9/5/2026",
        "9.5.2026",
        "2026-05-9",
        "9-05-2026",
    ],
)
def test_normalize_rejects_unpadded_forms(token: str) -> None:
    assert normalize_iso_date_token(token) is None


@pytest.mark.parametrize("token", ["2026-05/09", "2026/05.09", "09.05-2026", "09-05/2026"])
def test_normalize_rejects_mixed_separators(token: str) -> None:
    assert normalize_iso_date_token(token) is None


@pytest.mark.parametrize("token", ["May 9 2026", "9 May 2026", "today", "yesterday", "now"])
def test_normalize_rejects_natural_language(token: str) -> None:
    assert normalize_iso_date_token(token) is None


@pytest.mark.parametrize("token", ["", "   ", "\n", "not-a-date"])
def test_normalize_rejects_empty_or_junk(token: str) -> None:
    assert normalize_iso_date_token(token) is None


@pytest.mark.parametrize("token", ["2026-02-30", "30-02-2026", "2026-13-01", "32-01-2026"])
def test_normalize_rejects_impossible_calendar_dates(token: str) -> None:
    assert normalize_iso_date_token(token) is None


def test_normalize_returns_none_for_non_string_input() -> None:
    assert normalize_iso_date_token(None) is None
    assert normalize_iso_date_token(20260509) is None


def test_normalize_strips_surrounding_whitespace_before_matching() -> None:
    assert normalize_iso_date_token("  2026-05-09  ") == "2026-05-09"
    assert normalize_iso_date_token("\t09/05/2026\n") == "2026-05-09"
