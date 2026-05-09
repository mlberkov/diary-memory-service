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
        ("/entry", RouteKind.ENTRY),
        ("/ask", RouteKind.ASK),
    ],
)
def test_parse_command_recognizes_each_supported_command(
    text: str, expected_route: RouteKind
) -> None:
    route, payload = parse_command(text)
    assert route is expected_route
    assert payload == ""


def test_parse_command_returns_payload_after_command() -> None:
    route, payload = parse_command("/entry 2026-05-09\nFoo")
    assert route is RouteKind.ENTRY
    assert payload == "2026-05-09\nFoo"


def test_parse_command_strips_bot_username_suffix() -> None:
    route, payload = parse_command("/ask@DiaryBot what did we do?")
    assert route is RouteKind.ASK
    assert payload == "what did we do?"


def test_parse_command_handles_newline_after_command() -> None:
    route, payload = parse_command("/entry\n2026-05-09\nFoo")
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
