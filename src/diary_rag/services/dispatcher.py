"""Inbound-message dispatcher.

Maps a channel-neutral :class:`InboundMessage` to a
:class:`DispatchResult` carrying a reply string. ``ENTRY`` and ``ASK``
delegate to :class:`DiaryService` / :class:`QueryService`; ``CLARIFY``
returns a fixed clarification message; other routes return fixed
strings appropriate for the current phase.

Reply wording lives next to the dispatcher (channel-neutral) so the
Telegram adapter remains a transport layer (Invariant I-1).
"""

from __future__ import annotations

from diary_rag.core.diary import AnswerResult, FallbackMode, IngestResult
from diary_rag.core.routing import DispatchResult, InboundMessage, RouteKind
from diary_rag.services.diary_service import DiaryService
from diary_rag.services.query_service import QueryService

_REPLY_START = "Welcome — diary mode. Use /entry to record, /ask to query."
_REPLY_HELP = (
    "Commands: /start, /help, /entry, /ask. "
    "Diary mode is in setup; durable persistence and retrieval arrive in later phases."
)
_REPLY_UNKNOWN = "I haven't been taught how to handle plain messages yet — use /entry or /ask."
_REPLY_CLARIFY = (
    "I couldn't tell if that's a diary entry or a question. "
    "Send /entry <YYYY-MM-DD> on the first line then your events to record it, "
    "or /ask <your question> to query."
)
_HEURISTIC_MARKER_ENTRY = "(routed as entry — send /entry next time to be explicit)"
_HEURISTIC_MARKER_ASK = "(routed as question — send /ask next time to be explicit)"


def _format_ingest_reply(result: IngestResult) -> str:
    if result.fallback is FallbackMode.INVALID_INPUT:
        got = result.invalid_first_line or ""
        return f"Mock /entry needs an ISO date (YYYY-MM-DD) on the first line. Got: '{got}'."
    assert result.entry_date is not None
    if result.events_count == 0:
        return f"Saved {result.entry_date.isoformat()} with no event lines."
    plural = "event" if result.events_count == 1 else "events"
    return f"Saved {result.events_count} {plural} for {result.entry_date.isoformat()}."


def _format_answer_reply(result: AnswerResult) -> str:
    if result.fallback is FallbackMode.NO_EVIDENCE:
        if not result.query_text:
            return "No query text provided. (no_evidence — mock retrieval only.)"
        return f"No memories matched '{result.query_text}'. (no_evidence — mock retrieval only.)"
    count = len(result.evidence)
    plural = "memory" if count == 1 else "memories"
    lines = [f"Found {count} {plural}:"]
    lines.extend(f"- [{e.entry_date.isoformat()}] {e.chunk_text}" for e in result.evidence)
    lines.append("(mock retrieval — substring match)")
    return "\n".join(lines)


def _append_marker(reply: str, marker: str) -> str:
    return f"{reply}\n{marker}"


class Dispatcher:
    """Maps an :class:`InboundMessage` to a :class:`DispatchResult`."""

    def __init__(self, diary: DiaryService, query: QueryService) -> None:
        self._diary = diary
        self._query = query

    def dispatch(self, message: InboundMessage) -> DispatchResult:
        route = message.route
        is_heuristic = message.route_source == "heuristic"

        if route is RouteKind.START:
            return DispatchResult(reply_text=_REPLY_START, route=route)
        if route is RouteKind.HELP:
            return DispatchResult(reply_text=_REPLY_HELP, route=route)
        if route is RouteKind.ENTRY:
            ingest = self._diary.ingest(message)
            reply = _format_ingest_reply(ingest)
            if is_heuristic:
                reply = _append_marker(reply, _HEURISTIC_MARKER_ENTRY)
            return DispatchResult(
                reply_text=reply,
                route=route,
                metadata={
                    "fallback": ingest.fallback.value,
                    "route_source": message.route_source,
                },
            )
        if route is RouteKind.ASK:
            answer = self._query.answer(message)
            reply = _format_answer_reply(answer)
            if is_heuristic:
                reply = _append_marker(reply, _HEURISTIC_MARKER_ASK)
            return DispatchResult(
                reply_text=reply,
                route=route,
                metadata={
                    "fallback": answer.fallback.value,
                    "route_source": message.route_source,
                },
            )
        if route is RouteKind.CLARIFY:
            return DispatchResult(
                reply_text=_REPLY_CLARIFY,
                route=route,
                metadata={"route_source": message.route_source},
            )
        return DispatchResult(reply_text=_REPLY_UNKNOWN, route=RouteKind.UNKNOWN)
