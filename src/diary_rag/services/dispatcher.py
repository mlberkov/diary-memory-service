"""Inbound-message dispatcher.

Maps a channel-neutral :class:`InboundMessage` to a
:class:`DispatchResult` carrying a reply string. ``ENTRY``, ``DRAFT``,
and ``ASK`` delegate to :class:`DiaryService` / :class:`QueryService`;
``CLARIFY`` returns a fixed clarification message; other routes return
fixed strings appropriate for the current phase.

Draft floor (D-027 / R-13): the ``DRAFT`` path persists the inbound
raw text via ``DiaryService.ingest`` and stops there — no parse,
chunk, embed, or index. ``DRAFT`` is set by the no-command default for
plain text, so no plain-text message is silently discarded.

``DRAFTS`` (D-030) recalls the most-recent full raw drafts for the
family. The dispatcher parses the optional ``N`` argument, clamps it
to ``drafts_max_limit``, asks the diary service for the rows, and
returns a header plus the drafts payload. The adapter renders the
combined response as one transport message by default, splitting only
when the transport size cap forces it.

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

from diary_rag.config import Settings
from diary_rag.core.diary import AnswerResult, FallbackMode, IngestResult
from diary_rag.core.export import ExportFormat
from diary_rag.core.routing import DispatchResult, InboundMessage, RouteKind
from diary_rag.logging import get_logger
from diary_rag.services.diary_service import DiaryService
from diary_rag.services.export_service import ExportService
from diary_rag.services.query_service import QueryService

log = get_logger(__name__)

_REPLY_START = (
    "Welcome — diary mode. Use /note to record, /ask to query, or /drafts to recall "
    "recent drafts. Plain text without a command is stored as a draft so nothing is lost."
)
_REPLY_HELP = (
    "Commands: /start, /help, /note, /ask, /drafts, /export. Plain text without a "
    "command is stored as a draft."
)
_REPLY_UNKNOWN = "I haven't been taught how to handle that yet — use /note, /ask, or /drafts."
_REPLY_CLARIFY = (
    "I couldn't tell if that's a diary entry or a question. "
    "Send /note <YYYY-MM-DD> on the first line then your events to record it, "
    "or /ask <your question> to query."
)
_REPLY_EXPORT_USAGE = "Usage: /export json | /export txt — pick a format."
_REPLY_DRAFTS_USAGE = "Usage: /drafts [N]. N must be a positive integer."
_REPLY_DRAFTS_EMPTY = "No drafts to show."
_HEURISTIC_MARKER_ENTRY = "(routed as note — send /note next time to be explicit)"
_HEURISTIC_MARKER_ASK = "(routed as question — send /ask next time to be explicit)"
_DRAFT_REPLY_PREFIX = "Stored as draft"
_DRAFT_REPLY_HINT = (
    "Send /note <YYYY-MM-DD> on the first line to commit it as a note, or /ask to query."
)


def _format_ingest_reply(result: IngestResult) -> str:
    if result.fallback is FallbackMode.INVALID_INPUT:
        got = result.invalid_first_line or ""
        return f"Mock /note needs an ISO date (YYYY-MM-DD) on the first line. Got: '{got}'."
    assert result.entry_date is not None
    if result.events_count == 0:
        return f"Saved {result.entry_date.isoformat()} with no event lines."
    plural = "event" if result.events_count == 1 else "events"
    return f"Saved {result.events_count} {plural} for {result.entry_date.isoformat()}."


def _format_draft_reply(result: IngestResult) -> str:
    suffix = " (replay)" if result.replayed else ""
    return f"{_DRAFT_REPLY_PREFIX}{suffix}. {_DRAFT_REPLY_HINT}"


_RETRIEVAL_TRAILER = "(hybrid retrieval — dense+sparse RRF)"
_TRAILER_WEAK_EVIDENCE = "(weak evidence — model expressed uncertainty)"
_TRAILER_AMBIGUOUS = "(ambiguous question — refine and ask again)"
_REPLY_PROVIDER_UNAVAILABLE = (
    "Couldn't generate an answer — chat provider is unavailable. Try again later."
)
_REPLY_PARSE_FAILURE = "Couldn't generate an answer — provider response was unparseable. Try again."


def _format_evidence_lines(result: AnswerResult) -> list[str]:
    count = len(result.evidence)
    plural = "memory" if count == 1 else "memories"
    lines = [f"Found {count} {plural}:"]
    lines.extend(f"- [{e.entry_date.isoformat()}] {e.chunk_text}" for e in result.evidence)
    return lines


def _format_answer_reply(result: AnswerResult) -> str:
    """Render the answer reply per :class:`FallbackMode` (D-035).

    ``NO_EVIDENCE`` has two distinct effective paths — empty retrieval
    and LLM-marker — that must produce different surface text per R-6.
    The Dispatcher disambiguates on ``bool(result.evidence)``.
    """
    fallback = result.fallback

    if fallback is FallbackMode.NONE:
        lines = _format_evidence_lines(result)
        lines.append(_RETRIEVAL_TRAILER)
        return "\n".join(lines)

    if fallback is FallbackMode.WEAK_EVIDENCE:
        lines = _format_evidence_lines(result)
        lines.append(_TRAILER_WEAK_EVIDENCE)
        return "\n".join(lines)

    if fallback is FallbackMode.AMBIGUOUS:
        lines = _format_evidence_lines(result)
        lines.append(_TRAILER_AMBIGUOUS)
        return "\n".join(lines)

    if fallback is FallbackMode.PROVIDER_UNAVAILABLE:
        return _REPLY_PROVIDER_UNAVAILABLE

    if fallback is FallbackMode.PARSE_FAILURE:
        return _REPLY_PARSE_FAILURE

    if fallback is FallbackMode.NO_EVIDENCE:
        if not result.query_text:
            return "No query text provided."
        if result.evidence:
            return (
                f"Found possible matches but couldn't ground an answer for "
                f"'{result.query_text}'. Try refining the question."
            )
        return f"No memories matched '{result.query_text}'."

    return _REPLY_UNKNOWN


def _append_marker(reply: str, marker: str) -> str:
    return f"{reply}\n{marker}"


def _format_drafts_header(*, returned: int, requested: int, explicit: bool, max_limit: int) -> str:
    plural = "draft" if returned == 1 else "drafts"
    if not explicit:
        # No explicit N — user did not assert an expectation; just state what we show.
        return f"Most recent {returned} {plural}:"
    if returned == requested:
        return f"Most recent {returned} {plural}:"
    if returned < requested:
        # Either availability is below the request, or the cap is below the
        # request. The "all available" framing wins when availability is the
        # binding constraint; otherwise the cap is named.
        if returned < max_limit:
            return f"Showing all {returned} {plural} (you asked for {requested})."
        # returned == max_limit < requested
        return f"Showing the {returned} most recent {plural} (you asked for {requested})."
    # returned > requested should not happen — fall back to the simple form.
    return f"Most recent {returned} {plural}:"


class Dispatcher:
    """Maps an :class:`InboundMessage` to a :class:`DispatchResult`."""

    def __init__(
        self,
        diary: DiaryService,
        query: QueryService,
        export: ExportService,
        settings: Settings,
    ) -> None:
        self._diary = diary
        self._query = query
        self._export = export
        self._settings = settings

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
        if route is RouteKind.DRAFTS:
            return self._dispatch_drafts(message)
        if route is RouteKind.EXPORT:
            return self._dispatch_export(message)
        if route is RouteKind.CLARIFY:
            return DispatchResult(
                reply_text=_REPLY_CLARIFY,
                route=route,
                metadata={"route_source": message.route_source},
            )
        return DispatchResult(reply_text=_REPLY_UNKNOWN, route=RouteKind.UNKNOWN)

    def _dispatch_drafts(self, message: InboundMessage) -> DispatchResult:
        payload = message.payload.strip()
        requested: int
        if not payload:
            requested = self._settings.drafts_default_limit
            explicit = False
        else:
            try:
                requested = int(payload)
            except ValueError:
                log.info(
                    "drafts.usage_error chat_id=%s payload=%r",
                    message.external_chat_id,
                    message.payload,
                )
                return DispatchResult(
                    reply_text=_REPLY_DRAFTS_USAGE,
                    route=RouteKind.DRAFTS,
                    metadata={
                        "fallback": FallbackMode.INVALID_INPUT.value,
                        "route_source": message.route_source,
                    },
                )
            if requested < 1:
                log.info(
                    "drafts.usage_error chat_id=%s payload=%r",
                    message.external_chat_id,
                    message.payload,
                )
                return DispatchResult(
                    reply_text=_REPLY_DRAFTS_USAGE,
                    route=RouteKind.DRAFTS,
                    metadata={
                        "fallback": FallbackMode.INVALID_INPUT.value,
                        "route_source": message.route_source,
                    },
                )
            explicit = True

        max_limit = self._settings.drafts_max_limit
        effective_limit = min(requested, max_limit)
        family_id = message.external_chat_id
        drafts = self._diary.list_recent_drafts(family_id, limit=effective_limit)
        returned = len(drafts)

        if returned == 0:
            return DispatchResult(
                reply_text=_REPLY_DRAFTS_EMPTY,
                route=RouteKind.DRAFTS,
                metadata={
                    "fallback": FallbackMode.NONE.value,
                    "route_source": message.route_source,
                    "requested": str(requested),
                    "returned": "0",
                },
            )

        header = _format_drafts_header(
            returned=returned,
            requested=requested,
            explicit=explicit,
            max_limit=max_limit,
        )
        return DispatchResult(
            reply_text=header,
            route=RouteKind.DRAFTS,
            metadata={
                "fallback": FallbackMode.NONE.value,
                "route_source": message.route_source,
                "requested": str(requested),
                "returned": str(returned),
            },
            drafts=drafts,
        )

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
