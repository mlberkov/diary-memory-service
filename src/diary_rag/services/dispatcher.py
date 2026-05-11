"""Inbound-message dispatcher.

Maps a channel-neutral :class:`InboundMessage` to a
:class:`DispatchResult` carrying a reply string. ``ENTRY``, ``DRAFT``,
and ``ASK`` delegate to :class:`DiaryService` / :class:`QueryService`;
``CLARIFY`` returns a fixed clarification message; other routes return
fixed strings appropriate for the current phase.

Draft floor (D-027 / R-13): the ``DRAFT`` path persists the inbound
raw text via ``DiaryService.ingest`` and stops there — no parse,
chunk, embed, or index. ``DRAFT`` covers both the explicit ``/draft``
command and the no-command default, so no plain-text message is
silently discarded.

Reply wording lives next to the dispatcher (channel-neutral) so the
Telegram adapter remains a transport layer (Invariant I-1).

Slice 3.3 (D-025): the ASK path runs hybrid retrieval through
``QueryService``. Backends without retrieval parity (SQLite is opt-in
ingest only) raise ``NotImplementedError`` from the search seam; this
dispatcher catches that, logs a clear ``retrieval.unavailable`` line,
and returns ``FallbackMode.NO_EVIDENCE`` so the user gets a clean reply
rather than a 500.
"""

from __future__ import annotations

from diary_rag.core.diary import AnswerResult, FallbackMode, IngestResult
from diary_rag.core.export import ExportFormat
from diary_rag.core.routing import DispatchResult, InboundMessage, RouteKind
from diary_rag.logging import get_logger
from diary_rag.services.diary_service import DiaryService
from diary_rag.services.export_service import ExportService
from diary_rag.services.query_service import QueryService

log = get_logger(__name__)

_REPLY_START = (
    "Welcome — diary mode. Use /entry to record, /draft to save raw text "
    "without parsing, or /ask to query."
)
_REPLY_HELP = (
    "Commands: /start, /help, /entry, /draft, /ask. Plain text without a "
    "command is stored as a draft so nothing is lost."
)
_REPLY_UNKNOWN = "I haven't been taught how to handle that yet — use /entry, /draft, or /ask."
_REPLY_CLARIFY = (
    "I couldn't tell if that's a diary entry or a question. "
    "Send /entry <YYYY-MM-DD> on the first line then your events to record it, "
    "or /ask <your question> to query."
)
_REPLY_EXPORT_USAGE = "Usage: /export json | /export txt — pick a format."
_HEURISTIC_MARKER_ENTRY = "(routed as entry — send /entry next time to be explicit)"
_HEURISTIC_MARKER_ASK = "(routed as question — send /ask next time to be explicit)"
_DRAFT_REPLY_PREFIX = "Stored as draft"
_DRAFT_REPLY_HINT = (
    "Send /entry <YYYY-MM-DD> on the first line to commit it as a note, " "or /ask to query."
)


def _format_ingest_reply(result: IngestResult) -> str:
    if result.fallback is FallbackMode.INVALID_INPUT:
        got = result.invalid_first_line or ""
        return f"Mock /entry needs an ISO date (YYYY-MM-DD) on the first line. Got: '{got}'."
    assert result.entry_date is not None
    if result.events_count == 0:
        return f"Saved {result.entry_date.isoformat()} with no event lines."
    plural = "event" if result.events_count == 1 else "events"
    return f"Saved {result.events_count} {plural} for {result.entry_date.isoformat()}."


def _format_draft_reply(result: IngestResult) -> str:
    suffix = " (replay)" if result.replayed else ""
    return f"{_DRAFT_REPLY_PREFIX}{suffix}. {_DRAFT_REPLY_HINT}"


_RETRIEVAL_TRAILER = "(hybrid retrieval — dense+sparse RRF)"


def _format_answer_reply(result: AnswerResult) -> str:
    if result.fallback is FallbackMode.NO_EVIDENCE:
        if not result.query_text:
            return "No query text provided."
        return f"No memories matched '{result.query_text}'."
    count = len(result.evidence)
    plural = "memory" if count == 1 else "memories"
    lines = [f"Found {count} {plural}:"]
    lines.extend(f"- [{e.entry_date.isoformat()}] {e.chunk_text}" for e in result.evidence)
    lines.append(_RETRIEVAL_TRAILER)
    return "\n".join(lines)


def _append_marker(reply: str, marker: str) -> str:
    return f"{reply}\n{marker}"


class Dispatcher:
    """Maps an :class:`InboundMessage` to a :class:`DispatchResult`."""

    def __init__(
        self,
        diary: DiaryService,
        query: QueryService,
        export: ExportService,
    ) -> None:
        self._diary = diary
        self._query = query
        self._export = export

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
                    "effective_path": "replay" if ingest.replayed else "fresh",
                },
            )
        if route is RouteKind.DRAFT:
            ingest = self._diary.ingest(message)
            reply = _format_draft_reply(ingest)
            return DispatchResult(
                reply_text=reply,
                route=route,
                metadata={
                    "fallback": ingest.fallback.value,
                    "route_source": message.route_source,
                    "effective_path": "replay" if ingest.replayed else "fresh",
                },
            )
        if route is RouteKind.ASK:
            try:
                answer = self._query.answer(message)
            except NotImplementedError as exc:
                log.warning(
                    "retrieval.unavailable reason=%s family_id=%s",
                    exc,
                    message.external_chat_id,
                )
                answer = AnswerResult(
                    fallback=FallbackMode.NO_EVIDENCE,
                    query_text=message.payload.strip(),
                )
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
        if route is RouteKind.EXPORT:
            return self._dispatch_export(message)
        if route is RouteKind.CLARIFY:
            return DispatchResult(
                reply_text=_REPLY_CLARIFY,
                route=route,
                metadata={"route_source": message.route_source},
            )
        return DispatchResult(reply_text=_REPLY_UNKNOWN, route=RouteKind.UNKNOWN)

    def _dispatch_export(self, message: InboundMessage) -> DispatchResult:
        arg = message.payload.strip().lower()
        if arg == "json":
            fmt = ExportFormat.JSON
        elif arg == "txt":
            fmt = ExportFormat.TXT
        else:
            log.info(
                "export.usage_error chat_id=%s payload=%r",
                message.external_chat_id,
                message.payload,
            )
            return DispatchResult(
                reply_text=_REPLY_EXPORT_USAGE,
                route=RouteKind.EXPORT,
                metadata={
                    "fallback": FallbackMode.INVALID_INPUT.value,
                    "route_source": message.route_source,
                },
            )
        family_id = message.external_chat_id
        payload = self._export.export(
            family_id=family_id,
            requester_user_id=message.external_user_id,
            format=fmt,
        )
        unit = "message" if payload.record_count == 1 else "messages"
        reply = f"Exported {payload.record_count} raw {unit} as {fmt.value.upper()}."
        return DispatchResult(
            reply_text=reply,
            route=RouteKind.EXPORT,
            document=payload,
            metadata={
                "fallback": FallbackMode.NONE.value,
                "route_source": message.route_source,
                "format": fmt.value,
            },
        )
