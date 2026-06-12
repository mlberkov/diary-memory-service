"""Channel-neutral routed-chat service (RC-2/RC-3, D-108).

Hand-rolled classify-then-dispatch at the service seam (not the
Telegram adapter, I-1): the configured ``ChatRouteClassifier`` names one
of the four :class:`ChatRoute` values for an inbound question; the
dispatchable routes answer it; everything else funnels to the default
``notes_lookup`` route. There are no numeric confidence thresholds —
classification failure, unusable output, the not-yet-dispatchable
``notes_plus_knowledge`` route (RC-4), and an empty question all take
the same default branch, and the requested vs effective distinction is
preserved on the persisted :class:`ChatRouteDecision` row and the
returned result (R-6).

Route execution:

- ``notes_lookup`` delegates to ``QueryService.answer`` unchanged — the
  existing grounded ask, including its ``Query`` / ``RetrievalHit`` /
  ``AnswerTrace`` persistence and fallback grading. A search seam that
  raises ``NotImplementedError`` is handled exactly like the dispatcher
  ASK branch: a synthetic ``NO_EVIDENCE`` result, in which case no
  ``Query`` row exists and the decision row carries ``query_id=None``.
- ``model_only`` answers from general model knowledge via the existing
  ``ChatClient`` (the D-037 generation contour — the classifier pin is
  classification-only) and writes its own ``Query`` row (zero retrieval
  hits) plus ``AnswerTrace`` (``prompt_version="model-only-v1"``,
  empty ``context_chunk_ids``) so R-5 stays uniform across routes. The
  provider/parse failure contours mirror the D-035 grading shape.
- ``notes_plus_model`` (RC-3) rewrites the question onto the landed
  retrieval kwargs (``date_range``; the caller-provided
  ``subject_scope`` passes through unchanged), runs one scoped
  enrichment retrieval through ``QueryService.retrieve``, and answers
  with one generation combining a citation-grounded notes segment and
  an explicitly labeled model-knowledge segment
  (``prompt_version="notes-plus-model-v1"``, generalized I-9). A
  rewriter failure degrades cause-neutrally to the original question
  with no date constraint; empty retrieval does not short-circuit —
  generation still runs and the reply layer states the degradation
  before any model content. The path writes its own ``Query`` row
  (original question, recorded ``subject_scope``), ``RetrievalHit``
  rows for every contour that ran retrieval, an ``AnswerTrace``, and
  one :class:`ChatQueryRewrite` trace row.

Every call — every contour — persists exactly one
:class:`ChatRouteDecision` row and logs a ``chat.routed`` line (R-11).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from memory_rag.core.answers.client import ChatClient, ChatProviderUnavailableError
from memory_rag.core.chat.classifier import (
    ChatRouteClassifier,
    ChatRouteClassifierUnavailableError,
    ChatRouteOutputError,
)
from memory_rag.core.chat.enriched_prompt import (
    NOTES_PLUS_MODEL_PROMPT_VERSION,
    NotesPlusModelAnswerError,
    build_notes_plus_model_prompt,
    parse_notes_plus_model_answer,
)
from memory_rag.core.chat.model_prompt import (
    MODEL_ONLY_PROMPT_VERSION,
    ModelOnlyAnswerError,
    build_model_only_prompt,
    parse_model_only_answer,
)
from memory_rag.core.chat.models import (
    ChatQueryRewrite,
    ChatRoute,
    ChatRouteDecision,
    RoutedChatResult,
)
from memory_rag.core.chat.rewrite import (
    QueryRewriteOutputError,
    QueryRewriter,
    QueryRewriterUnavailableError,
)
from memory_rag.core.domain.models import (
    AnswerResult,
    AnswerTrace,
    DateRange,
    Evidence,
    FallbackMode,
    Query,
)
from memory_rag.core.routing import InboundMessage
from memory_rag.logging import get_logger
from memory_rag.services.context_assembler import assemble_answer_context
from memory_rag.services.query_service import QueryService, normalize_query
from memory_rag.services.retrieval import build_retrieval_hits
from memory_rag.storage.repository import DomainRepository

log = get_logger(__name__)

_NOTES_MARKER_TO_FALLBACK: dict[str, FallbackMode] = {
    "confident": FallbackMode.NONE,
    "uncertain": FallbackMode.WEAK_EVIDENCE,
    "no_evidence": FallbackMode.NO_EVIDENCE,
}


@dataclass(frozen=True, slots=True)
class _RewriteCapture:
    """What one rewrite attempt produced, for the trace row (RC-3).

    ``rewritten_query`` is ``None`` when no usable rewrite existed —
    the route degraded to the original question with no date
    constraint. ``model_name`` is ``""`` only when no rewriter was
    wired at all.
    """

    rewritten_query: str | None
    date_range: DateRange | None
    subject_scope: str | None
    model_name: str
    raw_output: str
    latency_ms: int


class RoutedChatService:
    """Routes a ``/chat`` question to an answer pipeline (RC-2/RC-3, D-108)."""

    def __init__(
        self,
        classifier: ChatRouteClassifier,
        query: QueryService,
        chat_client: ChatClient,
        repo: DomainRepository,
        *,
        rewriter: QueryRewriter | None = None,
    ) -> None:
        self._classifier = classifier
        self._query = query
        self._chat = chat_client
        self._repo = repo
        self._rewriter = rewriter

    def chat(
        self,
        message: InboundMessage,
        *,
        subject_scope: str | None = None,
    ) -> RoutedChatResult:
        """Classify and answer one routed-chat question.

        ``subject_scope`` passes through to the delegated retrieval
        exactly like ``QueryService.answer`` (H-3, D-107) — including
        the RC-3 enrichment retrieval; there is no inbound subject
        syntax yet — the Telegram dispatcher passes none.
        """
        # Opaque community scope resolved by the adapter at the edge (D-093 /
        # G-1); the core never re-derives it from external_chat_id (I-1).
        community_id = message.community_id
        if not community_id:
            raise ValueError("InboundMessage.community_id is required (R-3)")

        question = message.payload.strip()
        requested: ChatRoute | None = None
        classifier_raw_output = ""
        classifier_latency_ms = 0
        if question:
            try:
                classification = self._classifier.classify(question)
            except ChatRouteOutputError as exc:
                classifier_raw_output = exc.raw_output
            except ChatRouteClassifierUnavailableError:
                pass
            else:
                requested = classification.route
                classifier_raw_output = classification.raw_output
                classifier_latency_ms = classification.latency_ms

        # One branch funnels classifier failure, unusable output, the
        # not-yet-dispatchable route, and the empty question (D-108
        # fallback policy) — downstream wording must stay cause-neutral.
        if (
            requested is ChatRoute.NOTES_LOOKUP
            or requested is ChatRoute.MODEL_ONLY
            or requested is ChatRoute.NOTES_PLUS_MODEL
        ):
            effective = requested
        else:
            effective = ChatRoute.NOTES_LOOKUP

        query_id: str | None
        rewrite_capture: _RewriteCapture | None = None
        if effective is ChatRoute.MODEL_ONLY:
            answer, query_id = self._answer_model_only(message, question)
        elif effective is ChatRoute.NOTES_PLUS_MODEL:
            try:
                answer, query_id, rewrite_capture = self._answer_notes_plus_model(
                    message, question, subject_scope
                )
            except NotImplementedError as exc:
                # Same shape as the notes_lookup branch: the enrichment
                # retrieval seam is unavailable, so no Query row (and no
                # rewrite row) exists for this call.
                log.warning(
                    "retrieval.unavailable reason=%s community_id=%s",
                    exc,
                    community_id,
                )
                answer = AnswerResult(
                    fallback=FallbackMode.NO_EVIDENCE,
                    query_text=question,
                )
                query_id = None
        else:
            try:
                answer = self._query.answer(message, subject_scope=subject_scope)
            except NotImplementedError as exc:
                log.warning(
                    "retrieval.unavailable reason=%s community_id=%s",
                    exc,
                    community_id,
                )
                answer = AnswerResult(
                    fallback=FallbackMode.NO_EVIDENCE,
                    query_text=question,
                )
            query_id = answer.context.query_id if answer.context else None

        decision = ChatRouteDecision(
            decision_id=str(uuid4()),
            community_id=community_id,
            question_text=question,
            requested_route=requested,
            effective_route=effective,
            classifier_model_name=self._classifier.model_name,
            classifier_raw_output=classifier_raw_output,
            classifier_latency_ms=classifier_latency_ms,
            query_id=query_id,
            created_at=datetime.now(tz=UTC),
        )
        self._repo.save_chat_route_decision(decision)
        if rewrite_capture is not None:
            # The rewrite row links to the decision row, so it is written
            # strictly after it.
            self._repo.save_chat_query_rewrite(
                ChatQueryRewrite(
                    rewrite_id=str(uuid4()),
                    decision_id=decision.decision_id,
                    community_id=community_id,
                    rewritten_query=rewrite_capture.rewritten_query,
                    date_start=(
                        rewrite_capture.date_range.start if rewrite_capture.date_range else None
                    ),
                    date_end=(
                        rewrite_capture.date_range.end if rewrite_capture.date_range else None
                    ),
                    subject_scope=rewrite_capture.subject_scope,
                    rewriter_model_name=rewrite_capture.model_name,
                    rewriter_raw_output=rewrite_capture.raw_output,
                    rewriter_latency_ms=rewrite_capture.latency_ms,
                    created_at=datetime.now(tz=UTC),
                )
            )
        log.info(
            "chat.routed decision_id=%s community_id=%s requested=%s effective=%s "
            "fallback=%s query_id=%s",
            decision.decision_id,
            community_id,
            requested.value if requested else "unclassified",
            effective.value,
            answer.fallback.value,
            query_id,
        )
        return RoutedChatResult(
            requested_route=requested,
            effective_route=effective,
            answer=answer,
            decision_id=decision.decision_id,
        )

    def _rewrite(self, question: str) -> _RewriteCapture:
        """Run the rewrite step; never raises (RC-3).

        Failure — no rewriter wired, provider unavailable, unusable
        output, or a rewrite that normalizes to empty — degrades to the
        original question with no date constraint, captured as
        ``rewritten_query=None``. Logs may name the cause; user-facing
        wording must not.
        """
        if self._rewriter is None:
            return _RewriteCapture(
                rewritten_query=None,
                date_range=None,
                subject_scope=None,
                model_name="",
                raw_output="",
                latency_ms=0,
            )
        today = datetime.now(tz=UTC).date()
        try:
            rewrite = self._rewriter.rewrite(question, today=today)
        except QueryRewriteOutputError as exc:
            log.warning("chat.rewrite_failed reason=unusable_output error=%s", exc)
            return _RewriteCapture(
                rewritten_query=None,
                date_range=None,
                subject_scope=None,
                model_name=self._rewriter.model_name,
                raw_output=exc.raw_output,
                latency_ms=0,
            )
        except QueryRewriterUnavailableError as exc:
            log.warning("chat.rewrite_failed reason=provider_unavailable error=%s", exc)
            return _RewriteCapture(
                rewritten_query=None,
                date_range=None,
                subject_scope=None,
                model_name=self._rewriter.model_name,
                raw_output="",
                latency_ms=0,
            )
        rewritten_query = normalize_query(rewrite.retrieval_query)
        if not rewritten_query:
            log.warning("chat.rewrite_failed reason=empty_rewritten_query")
            return _RewriteCapture(
                rewritten_query=None,
                date_range=None,
                subject_scope=None,
                model_name=rewrite.model_name,
                raw_output=rewrite.raw_output,
                latency_ms=rewrite.latency_ms,
            )
        return _RewriteCapture(
            rewritten_query=rewritten_query,
            date_range=rewrite.date_range,
            subject_scope=rewrite.subject_scope,
            model_name=rewrite.model_name,
            raw_output=rewrite.raw_output,
            latency_ms=rewrite.latency_ms,
        )

    def _answer_notes_plus_model(
        self, message: InboundMessage, question: str, subject_scope: str | None
    ) -> tuple[AnswerResult, str, _RewriteCapture]:
        """Answer combining the notes and model planes (RC-3).

        Pipeline: rewrite-to-kwargs → scoped enrichment retrieval →
        one generation with per-segment provenance. ``Query.fallback``
        and ``AnswerTrace.fallback_mode`` are written from one
        post-generation decision (D-035); the trace stores the raw
        segmented JSON verbatim on the success and parse-failure
        contours because a mixed answer has no single answer string.
        The rewriter never scopes the retrieval by subject — only the
        caller-provided ``subject_scope`` is applied (see
        ``docs/assumptions.md``).
        """
        community_id = message.community_id
        created_at = datetime.now(tz=UTC)
        query_id = str(uuid4())

        capture = self._rewrite(question)
        retrieval_query = (
            capture.rewritten_query
            if capture.rewritten_query is not None
            else normalize_query(question)
        )
        date_range = capture.date_range

        candidates = self._query.retrieve(
            community_id,
            retrieval_query,
            date_range=date_range,
            subject_scope=subject_scope,
        )
        provisional_query = Query(
            query_id=query_id,
            community_id=community_id,
            query_text=question,
            model_name=candidates.embedding_model_name,
            fallback=FallbackMode.NONE,
            created_at=created_at,
            subject_scope=subject_scope,
        )
        context = assemble_answer_context(provisional_query, candidates.merged)
        context_chunk_ids = tuple(c.chunk_id for c in context.ordered_chunks)
        evidence = [
            Evidence(
                chunk_id=h.chunk.chunk_id,
                note_date=h.chunk.note_date,
                chunk_text=h.chunk.chunk_text,
            )
            for h in candidates.merged
        ]

        prompt = build_notes_plus_model_prompt(context)

        fallback = FallbackMode.NONE
        answer_text: str | None = None
        model_text: str | None = None
        cited_chunk_ids: tuple[str, ...] = ()
        trace_answer_text = ""
        token_counts: dict[str, int] = {}
        latency_ms = 0
        try:
            response = self._chat.complete(prompt)
        except ChatProviderUnavailableError as exc:
            log.warning(
                "chat.notes_plus_model.provider_unavailable community_id=%s error=%s",
                community_id,
                exc,
            )
            fallback = FallbackMode.PROVIDER_UNAVAILABLE
        else:
            token_counts = response.token_counts
            latency_ms = response.latency_ms
            try:
                parsed = parse_notes_plus_model_answer(response.raw_text, context=context)
            except NotesPlusModelAnswerError as exc:
                log.warning(
                    "chat.notes_plus_model.parse_failure community_id=%s error=%s",
                    community_id,
                    exc,
                )
                fallback = FallbackMode.PARSE_FAILURE
                trace_answer_text = response.raw_text
            else:
                fallback = _NOTES_MARKER_TO_FALLBACK[parsed.notes_uncertainty]
                answer_text = parsed.notes_text or None
                model_text = parsed.model_text
                cited_chunk_ids = parsed.cited_chunk_ids
                trace_answer_text = response.raw_text

        final_query = Query(
            query_id=query_id,
            community_id=community_id,
            query_text=question,
            model_name=candidates.embedding_model_name,
            fallback=fallback,
            created_at=created_at,
            subject_scope=subject_scope,
        )
        self._repo.save_query(final_query)
        hits = build_retrieval_hits(
            query_id=query_id,
            model_name=candidates.embedding_model_name,
            created_at=created_at,
            candidates=candidates,
        )
        if hits:
            self._repo.save_retrieval_hits(hits)
        self._repo.save_answer_trace(
            AnswerTrace(
                answer_trace_id=str(uuid4()),
                query_id=query_id,
                prompt_version=NOTES_PLUS_MODEL_PROMPT_VERSION,
                context_chunk_ids=context_chunk_ids,
                answer_text=trace_answer_text,
                fallback_mode=fallback,
                model_name=self._chat.model_name,
                token_counts=token_counts,
                latency_ms=latency_ms,
                created_at=created_at,
            )
        )
        log.info(
            "chat.enriched query_id=%s community_id=%s dense_n=%d sparse_n=%d "
            "merged_n=%d rewritten=%s fallback=%s",
            query_id,
            community_id,
            len(candidates.dense),
            len(candidates.sparse),
            len(candidates.merged),
            capture.rewritten_query is not None,
            fallback.value,
        )
        answer = AnswerResult(
            fallback=fallback,
            query_text=question,
            evidence=evidence,
            context=context,
            answer_text=answer_text,
            cited_chunk_ids=cited_chunk_ids,
            model_text=model_text,
        )
        return answer, query_id, capture

    def _answer_model_only(
        self, message: InboundMessage, question: str
    ) -> tuple[AnswerResult, str]:
        """Answer from general model knowledge; persist Query + AnswerTrace.

        Trace shape per contour mirrors D-035: success carries the
        parsed answer plus response tokens/latency; provider-unavailable
        carries ``""`` with zero latency and empty tokens; parse-failure
        preserves ``response.raw_text`` verbatim with the response's
        tokens/latency.
        """
        created_at = datetime.now(tz=UTC)
        query_id = str(uuid4())
        prompt = build_model_only_prompt(question)

        fallback = FallbackMode.NONE
        answer_text: str | None = None
        trace_answer_text = ""
        token_counts: dict[str, int] = {}
        latency_ms = 0
        try:
            response = self._chat.complete(prompt)
        except ChatProviderUnavailableError as exc:
            log.warning(
                "chat.model_only.provider_unavailable community_id=%s error=%s",
                message.community_id,
                exc,
            )
            fallback = FallbackMode.PROVIDER_UNAVAILABLE
            answer_text = ""
        else:
            token_counts = response.token_counts
            latency_ms = response.latency_ms
            try:
                parsed = parse_model_only_answer(response.raw_text)
            except ModelOnlyAnswerError as exc:
                log.warning(
                    "chat.model_only.parse_failure community_id=%s error=%s",
                    message.community_id,
                    exc,
                )
                fallback = FallbackMode.PARSE_FAILURE
                answer_text = ""
                trace_answer_text = response.raw_text
            else:
                answer_text = parsed
                trace_answer_text = parsed

        self._repo.save_query(
            Query(
                query_id=query_id,
                community_id=message.community_id,
                query_text=question,
                model_name=self._chat.model_name,
                fallback=fallback,
                created_at=created_at,
                subject_scope=None,
            )
        )
        self._repo.save_answer_trace(
            AnswerTrace(
                answer_trace_id=str(uuid4()),
                query_id=query_id,
                prompt_version=MODEL_ONLY_PROMPT_VERSION,
                context_chunk_ids=(),
                answer_text=trace_answer_text,
                fallback_mode=fallback,
                model_name=self._chat.model_name,
                token_counts=token_counts,
                latency_ms=latency_ms,
                created_at=created_at,
            )
        )
        answer = AnswerResult(
            fallback=fallback,
            query_text=question,
            evidence=[],
            context=None,
            answer_text=answer_text,
            cited_chunk_ids=(),
        )
        return answer, query_id
