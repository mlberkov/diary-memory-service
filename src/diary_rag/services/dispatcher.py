"""Inbound-message dispatcher.

Turns an :class:`InboundMessage` into a :class:`DispatchResult` carrying
a reply string. The handlers here return fixed mock replies; persistence
and retrieval are not part of this layer yet.
"""

from __future__ import annotations

from diary_rag.core.routing import DispatchResult, InboundMessage, RouteKind

_REPLY_START = "Welcome — diary mode. Use /entry to record, /ask to query."
_REPLY_HELP = (
    "Commands: /start, /help, /entry, /ask. "
    "Diary mode is in setup; durable persistence and retrieval arrive in later phases."
)
_REPLY_ENTRY = "Got it. (mock — no durable persistence yet.)"
_REPLY_ASK = "Mock answer. (no real retrieval yet.)"
_REPLY_UNKNOWN = "I haven't been taught how to handle plain messages yet — use /entry or /ask."


class Dispatcher:
    """Maps an :class:`InboundMessage` to a :class:`DispatchResult`."""

    def dispatch(self, message: InboundMessage) -> DispatchResult:
        route = message.route
        if route is RouteKind.START:
            return DispatchResult(reply_text=_REPLY_START, route=route)
        if route is RouteKind.HELP:
            return DispatchResult(reply_text=_REPLY_HELP, route=route)
        if route is RouteKind.ENTRY:
            return DispatchResult(reply_text=_REPLY_ENTRY, route=route, metadata={"mock": "true"})
        if route is RouteKind.ASK:
            return DispatchResult(reply_text=_REPLY_ASK, route=route, metadata={"mock": "true"})
        return DispatchResult(reply_text=_REPLY_UNKNOWN, route=RouteKind.UNKNOWN)
