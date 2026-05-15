"""Telegram command parser.

Recognises ``/start``, ``/help``, ``/note``, ``/ask``, ``/drafts``,
``/export``, ``/sources``. The leading ``@BotName`` suffix that Telegram
appends in group chats is stripped before lookup. Anything else maps to
:class:`RouteKind.UNKNOWN` and the webhook hands off to the heuristic
classifier; under the draft floor (D-027) any non-empty plain text
without a recognised command is preserved as a draft rather than
dropped.
"""

from __future__ import annotations

from diary_rag.core.routing import RouteKind

COMMAND_TOKENS: dict[str, RouteKind] = {
    "/start": RouteKind.START,
    "/help": RouteKind.HELP,
    "/note": RouteKind.NOTE,
    "/ask": RouteKind.ASK,
    "/drafts": RouteKind.DRAFTS,
    "/export": RouteKind.EXPORT,
    "/sources": RouteKind.SOURCES,
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
