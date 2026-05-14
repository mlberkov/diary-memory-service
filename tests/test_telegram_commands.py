"""Pure command parser tests."""

from __future__ import annotations

import pytest

from diary_rag.adapters.telegram.commands import parse_command
from diary_rag.core.routing import RouteKind


@pytest.mark.parametrize(
    ("text", "expected_route"),
    [
        ("/start", RouteKind.START),
        ("/help", RouteKind.HELP),
        ("/note", RouteKind.ENTRY),
        ("/ask", RouteKind.ASK),
        ("/drafts", RouteKind.DRAFTS),
        ("/sources", RouteKind.SOURCES),
    ],
)
def test_parse_command_recognizes_each_supported_command(
    text: str, expected_route: RouteKind
) -> None:
    route, payload = parse_command(text)
    assert route is expected_route
    assert payload == ""


def test_parse_command_drafts_returns_integer_payload() -> None:
    route, payload = parse_command("/drafts 5")
    assert route is RouteKind.DRAFTS
    assert payload == "5"


def test_parse_command_drafts_without_argument_yields_empty_payload() -> None:
    route, payload = parse_command("/drafts")
    assert route is RouteKind.DRAFTS
    assert payload == ""


def test_parse_command_old_draft_token_no_longer_maps_to_draft_route() -> None:
    route, payload = parse_command("/draft groceries: milk, bread")
    assert route is RouteKind.UNKNOWN
    assert payload == "/draft groceries: milk, bread"


def test_parse_command_old_entry_token_no_longer_maps_to_entry_route() -> None:
    route, payload = parse_command("/entry 2026-05-09\nFoo")
    assert route is RouteKind.UNKNOWN
    assert payload == "/entry 2026-05-09\nFoo"


def test_parse_command_returns_payload_after_command() -> None:
    route, payload = parse_command("/note 2026-05-09\nFoo")
    assert route is RouteKind.ENTRY
    assert payload == "2026-05-09\nFoo"


def test_parse_command_strips_bot_username_suffix() -> None:
    route, payload = parse_command("/ask@DiaryBot what did we do?")
    assert route is RouteKind.ASK
    assert payload == "what did we do?"


def test_parse_command_handles_newline_after_command() -> None:
    route, payload = parse_command("/note\n2026-05-09\nFoo")
    assert route is RouteKind.ENTRY
    assert payload == "2026-05-09\nFoo"


def test_parse_command_returns_unknown_for_plain_text() -> None:
    route, payload = parse_command("hello")
    assert route is RouteKind.UNKNOWN
    assert payload == "hello"


@pytest.mark.parametrize("text", ["", None])
def test_parse_command_returns_unknown_for_empty_or_none(text: str | None) -> None:
    route, payload = parse_command(text)
    assert route is RouteKind.UNKNOWN
    assert payload == ""


def test_parse_command_returns_unknown_for_unrecognized_slash() -> None:
    route, payload = parse_command("/foo")
    assert route is RouteKind.UNKNOWN
    assert payload == "/foo"
