"""Telegram command parser.

Recognises ``/start``, ``/help``, ``/entry``, ``/ask``. The leading
``@BotName`` suffix that Telegram appends in group chats is stripped
before lookup. Anything else maps to :class:`RouteKind.UNKNOWN`.
"""

from __future__ import annotations

from diary_rag.core.routing import RouteKind

COMMAND_TOKENS: dict[str, RouteKind] = {
    "/start": RouteKind.START,
    "/help": RouteKind.HELP,
    "/entry": RouteKind.ENTRY,
    "/ask": RouteKind.ASK,
}


def parse_command(text: str | None) -> tuple[RouteKind, str]:
    """Return ``(route, payload)`` where ``payload`` is the text after the command."""
    if not text:
        return RouteKind.UNKNOWN, ""

    head, _, rest = text.partition(" ")
    head_no_newline, _, rest_after_newline = head.partition("\n")
    if rest_after_newline:
        # First whitespace was a newline, not a space.
        rest = rest_after_newline + ((" " + rest) if rest else "")
        head = head_no_newline

    token = head.split("@", 1)[0]
    route = COMMAND_TOKENS.get(token)
    if route is None:
        return RouteKind.UNKNOWN, text

    return route, rest.lstrip()
