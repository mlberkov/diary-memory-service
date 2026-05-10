"""Pure parser tests for the diary entry payload."""

from __future__ import annotations

from datetime import date

import pytest

from diary_rag.core.diary import parse_diary_entry


def test_parses_iso_date_and_event_lines() -> None:
    parsed = parse_diary_entry("2026-05-09\nHad a calm morning\nTried a new book")
    assert parsed is not None
    assert parsed.entry_date == date(2026, 5, 9)
    assert parsed.events == ["Had a calm morning", "Tried a new book"]


def test_strips_blank_lines_between_events() -> None:
    parsed = parse_diary_entry("2026-05-09\n\nFirst event\n\nSecond event\n")
    assert parsed is not None
    assert parsed.events == ["First event", "Second event"]


def test_skips_leading_blank_lines_before_date() -> None:
    parsed = parse_diary_entry("\n\n2026-05-09\nFirst event")
    assert parsed is not None
    assert parsed.entry_date == date(2026, 5, 9)
    assert parsed.events == ["First event"]


def test_returns_none_when_first_line_not_iso_date() -> None:
    assert parse_diary_entry("not-a-date\nfoo") is None


def test_returns_none_for_non_iso_locale_date() -> None:
    assert parse_diary_entry("09/05/2026\nfoo") is None


@pytest.mark.parametrize("payload", ["", "   ", "\n\n"])
def test_returns_none_for_empty_payload(payload: str) -> None:
    assert parse_diary_entry(payload) is None


def test_date_only_returns_no_events() -> None:
    parsed = parse_diary_entry("2026-05-09")
    assert parsed is not None
    assert parsed.entry_date == date(2026, 5, 9)
    assert parsed.events == []
