"""Inbound-message dispatcher.

Maps a channel-neutral :class:`InboundMessage` to a
:class:`DispatchResult` carrying a reply string. ``NOTE``, ``DRAFT``,
and ``ASK`` delegate to :class:`DomainService` / :class:`QueryService`;
``CLARIFY`` returns a fixed clarification message; other routes return
fixed strings appropriate for the current phase.

Draft floor (D-027 / R-13): the ``DRAFT`` path persists the inbound
raw text via ``DomainService.ingest`` and stops there — no parse,
chunk, embed, or index. ``DRAFT`` is set by the no-command default for
plain text, so no plain-text message is silently discarded.

``DRAFTS`` (D-030) recalls the most-recent full raw drafts for the
community. The dispatcher parses the optional ``N`` argument, clamps it
to ``drafts_max_limit``, asks the domain service for the rows, and
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

import dataclasses

from memory_rag.config import Settings
from memory_rag.core.domain import AnswerResult, FallbackMode, IngestResult
from memory_rag.core.domain.models import EventChunk
from memory_rag.core.domain.parser import normalize_iso_date_token
from memory_rag.core.export import ExportFormat
from memory_rag.core.routing import DispatchResult, InboundMessage, RouteKind
from memory_rag.logging import get_logger
from memory_rag.services.domain_service import DomainService
from memory_rag.services.export_service import ExportService
from memory_rag.services.query_service import QueryService

log = get_logger(__name__)

_REPLY_START = (
    "Welcome — diary mode. Use /note to record, /ask to query, /sources to see the chunks "
    "behind your last answer, or /drafts to recall recent drafts. For /note, put a date on "
    "the first line — 2026-05-09 is the recommended form; 2026/05/09, 2026.05.09, "
    "09-05-2026, 09/05/2026, and 09.05.2026 also work (DD-first is read as DD/MM/YYYY). "
    "Plain text without a command is stored as a draft so nothing is lost."
)
_REPLY_HELP = (
    "Commands: /start, /help, /note, /ask, /sources, /drafts, /export. Plain text "
    "without a command is stored as a draft."
)
_REPLY_UNKNOWN = (
    "I haven't been taught how to handle that yet — use /note, /ask, /sources, or /drafts."
)
_REPLY_CLARIFY = (
    "I couldn't tell if that's a diary entry or a question. "
    "Send /note <YYYY-MM-DD> on the first line then your events to record it, "
    "or /ask <your question> to query."
)
_REPLY_EXPORT_USAGE = "Usage: /export json | /export txt — pick a format."
_REPLY_DRAFTS_USAGE = "Usage: /drafts [N]. N must be a positive integer."
_REPLY_DRAFTS_EMPTY = "No drafts to show."
_DRAFT_REPLY_PREFIX = "Stored as draft"
_DRAFT_REPLY_HINT = (
    "Send /note <YYYY-MM-DD> on the first line to commit it as a note, or /ask to query."
)


def _format_ingest_reply(result: IngestResult) -> str:
    if result.fallback is FallbackMode.INVALID_INPUT:
        got = result.invalid_first_line or ""
        return f"First line must be a date like 2026-05-09. Got: '{got}'."
    assert result.note_date is not None
    if result.events_count == 0:
        return f"Saved {result.note_date.isoformat()} with no event lines."
    plural = "event" if result.events_count == 1 else "events"
    return f"Saved {result.events_count} {plural} for {result.note_date.isoformat()}."


def _normalize_note_first_line(message: InboundMessage) -> InboundMessage:
    """Normalize the first non-empty line of a ``/note`` payload before parsing.

    NOTE is reached only via the explicit ``/note`` command (D-079), so this
    runs on every NOTE dispatch. The non-empty-line rule must match
    :func:`parse_note`'s behavior so the surface the user sees matches what
    the parser will then read.

    Three cases on the first non-empty line:

    * a recognized near-ISO date (the D-070 six-form whitelist) is rewritten
      in place to canonical ``YYYY-MM-DD`` (an already-canonical date is left
      untouched);
    * a line that is **not** a recognized date defaults the note to "today"
      (D-085): a canonical ``YYYY-MM-DD`` line for ``message.received_at`` is
      prepended, so the previously-first line and everything after it become
      event lines. "today" is the UTC date the message was received — a
      deterministic, per-message source, not a dispatch wall-clock.

    An empty or whitespace-only payload is returned unchanged, so it still
    falls through to :func:`parse_note` and yields ``INVALID_INPUT``.
    """
    payload = message.payload
    if not payload:
        return message
    lines = payload.splitlines(keepends=True)
    for idx, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped:
            continue
        canonical = normalize_iso_date_token(stripped)
        if canonical is None:
            today_iso = message.received_at.date().isoformat()
            return dataclasses.replace(message, payload=f"{today_iso}\n{payload}")
        if canonical == stripped:
            return message
        leading_len = len(raw) - len(raw.lstrip())
        trailing = raw[leading_len + len(stripped) :]
        lines[idx] = raw[:leading_len] + canonical + trailing
        return dataclasses.replace(message, payload="".join(lines))
    return message


def _format_draft_reply(result: IngestResult) -> str:
    suffix = " (replay)" if result.replayed else ""
    return f"{_DRAFT_REPLY_PREFIX}{suffix}. {_DRAFT_REPLY_HINT}"


_TRAILER_WEAK_EVIDENCE = "(weak evidence — model expressed uncertainty)"
_TRAILER_AMBIGUOUS = "(ambiguous question — refine and ask again)"
_REPLY_PROVIDER_UNAVAILABLE = (
    "Couldn't generate an answer — chat provider is unavailable. Try again later."
)
_REPLY_PARSE_FAILURE = "Couldn't generate an answer — provider response was unparseable. Try again."
_REPLY_NO_MATCHES_TEMPLATE = (
    "Nothing in your saved notes matched '{query}'. "
    "Try rephrasing the question, or use words that appear in your notes."
)
_REPLY_SOURCES_NONE = "No selected chunks available — ask a question with /ask first."
_REPLY_SOURCES_NONE_CITED = "Your last /ask answer didn't cite any specific notes."


def _format_answer_reply(result: AnswerResult) -> str:
    """Render the answer reply per :class:`FallbackMode` (D-035, D-036).

    Slice 4.4 (D-036): the body for ``NONE`` is ``result.answer_text``
    alone. ``WEAK_EVIDENCE`` and ``AMBIGUOUS`` append their plain-English
    explanatory trailer. The cited chunks are not in the default reply —
    ``/sources`` exposes them on demand.

    ``NO_EVIDENCE`` has two distinct effective paths — empty-evidence
    and LLM-marker — that must produce different surface text per R-6.
    The Dispatcher disambiguates on ``bool(result.evidence)``. The
    empty-evidence reply names the empty-match outcome and offers two
    short question-side nudges, staying neutral about cause. The
    LLM-marker reply deliberately does not surface the LLM's prose:
    "no_evidence" means there is no answer to render.
    """
    fallback = result.fallback

    if fallback is FallbackMode.NONE:
        return result.answer_text or ""

    if fallback is FallbackMode.WEAK_EVIDENCE:
        body = result.answer_text or ""
        return f"{body}\n\n{_TRAILER_WEAK_EVIDENCE}"

    if fallback is FallbackMode.AMBIGUOUS:
        body = result.answer_text or ""
        return f"{body}\n\n{_TRAILER_AMBIGUOUS}"

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
        return _REPLY_NO_MATCHES_TEMPLATE.format(query=result.query_text)

    return _REPLY_UNKNOWN


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
    """Maps an :class:`InboundMessage` to a :class:`DispatchResult`.

    Holds a small per-community in-memory cache of the chunks the LLM
    cited in the chat's most recent ``/ask`` answer (Slice 4.4 / D-036;
    cited-only since D-100). The cache backs ``/sources``: every ``/ask``
    dispatch overwrites it with the cited subset of
    ``answer.context.ordered_chunks`` (the chunks in
    ``answer.cited_chunk_ids``; D-098), which is empty for every
    cited-empty contour (D-099). Key presence — not non-emptiness —
    records that an ``/ask`` happened, so ``/sources`` distinguishes "no
    prior /ask" from "prior /ask that cited nothing". The cache is
    process-local and dies on restart; this is acceptable because the
    FastAPI wiring at
    ``adapters/telegram/webhook.py`` makes ``Dispatcher`` a module-level
    singleton, so ``/ask`` and a follow-up ``/sources`` are served by
    the same instance within one process. Multi-worker deploys would
    break the latest-only contract — see D-036 for the follow-up
    trigger.
    """

    def __init__(
        self,
        domain: DomainService,
        query: QueryService,
        export: ExportService,
        settings: Settings,
    ) -> None:
        self._domain = domain
        self._query = query
        self._export = export
        self._settings = settings
        self._latest_sources: dict[str, tuple[EventChunk, ...]] = {}

    def dispatch(self, message: InboundMessage) -> DispatchResult:
        route = message.route

        if route is RouteKind.START:
            return DispatchResult(reply_text=_REPLY_START, route=route)
        if route is RouteKind.HELP:
            return DispatchResult(reply_text=_REPLY_HELP, route=route)
        if route is RouteKind.NOTE:
            message = _normalize_note_first_line(message)
            ingest = self._domain.ingest(message)
            reply = _format_ingest_reply(ingest)
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
            ingest = self._domain.ingest(message)
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
                    "retrieval.unavailable reason=%s community_id=%s",
                    exc,
                    message.community_id,
                )
                answer = AnswerResult(
                    fallback=FallbackMode.NO_EVIDENCE,
                    query_text=message.payload.strip(),
                )
            self._update_latest_sources(message.community_id, answer)
            reply = _format_answer_reply(answer)
            return DispatchResult(
                reply_text=reply,
                route=route,
                metadata={
                    "fallback": answer.fallback.value,
                    "route_source": message.route_source,
                },
            )
        if route is RouteKind.SOURCES:
            return self._dispatch_sources(message)
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
        community_id = message.community_id
        drafts = self._domain.list_recent_drafts(community_id, limit=effective_limit)
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
        community_id = message.community_id
        payload = self._export.export(
            community_id=community_id,
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

    def _update_latest_sources(self, community_id: str, answer: AnswerResult) -> None:
        """Cache the chunks the LLM cited for the community's last /ask (D-036, D-100).

        Every ``/ask`` dispatch writes the cache (no skip path), so key
        presence records that an ``/ask`` happened at all. The stored
        value is the *cited* subset — the chunks in
        ``answer.context.ordered_chunks`` whose ``chunk_id`` is in
        ``answer.cited_chunk_ids`` (the LLM's used-evidence set, an I-9
        subset of the retrieved context; D-098), kept in post-RRF
        ``ordered_chunks`` order. Every cited-empty contour
        (``cited_chunk_ids == ()`` per D-099 — both ``NO_EVIDENCE``
        paths, ``PROVIDER_UNAVAILABLE``, ``PARSE_FAILURE``, and the
        no-context contour) stores an empty tuple, which ``/sources``
        distinguishes from "no prior /ask" by key presence. Only the next
        ``/ask`` overwrites this entry.
        """
        cited_ids = set(answer.cited_chunk_ids)
        if answer.context is not None and cited_ids:
            cited = tuple(c for c in answer.context.ordered_chunks if c.chunk_id in cited_ids)
        else:
            cited = ()
        self._latest_sources[community_id] = cited

    def _dispatch_sources(self, message: InboundMessage) -> DispatchResult:
        """Serve ``/sources`` from the latest-cited cache (D-036, D-100).

        Returns the chunks the LLM *cited* in the chat's most recent
        ``/ask`` answer (``AnswerResult.cited_chunk_ids``; D-098) as
        opaque ``EventChunk`` objects on ``source_chunks``. The adapter
        renders each block (full ``chunk_text``) and resolves the author
        display name (adapter-only; D-081 / D-086); the channel-neutral
        dispatcher never composes a display name. Two empty contours are
        kept distinct by key presence: no prior ``/ask`` (key absent) →
        ``_REPLY_SOURCES_NONE``; a prior ``/ask`` whose answer cited
        nothing (key present, empty tuple — every cited-empty contour per
        D-099) → ``_REPLY_SOURCES_NONE_CITED``. Not fine-grained
        attribution.
        """
        community_id = message.community_id
        if community_id not in self._latest_sources:
            return DispatchResult(
                reply_text=_REPLY_SOURCES_NONE,
                route=RouteKind.SOURCES,
                metadata={
                    "fallback": FallbackMode.NONE.value,
                    "route_source": message.route_source,
                    "returned": "0",
                },
            )
        chunks = self._latest_sources[community_id]
        if not chunks:
            return DispatchResult(
                reply_text=_REPLY_SOURCES_NONE_CITED,
                route=RouteKind.SOURCES,
                metadata={
                    "fallback": FallbackMode.NONE.value,
                    "route_source": message.route_source,
                    "returned": "0",
                },
            )
        header = f"Selected chunks for your last /ask ({len(chunks)} chunk(s)):"
        return DispatchResult(
            reply_text=header,
            route=RouteKind.SOURCES,
            metadata={
                "fallback": FallbackMode.NONE.value,
                "route_source": message.route_source,
                "returned": str(len(chunks)),
            },
            source_chunks=chunks,
        )
