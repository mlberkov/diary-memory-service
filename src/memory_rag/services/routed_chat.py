"""Channel-neutral routed-chat service (RC-2, D-108).

Hand-rolled classify-then-dispatch at the service seam (not the
Telegram adapter, I-1): the configured ``ChatRouteClassifier`` names one
of the four :class:`ChatRoute` values for an inbound question; the
dispatchable routes answer it; everything else funnels to the default
``notes_lookup`` route. There are no numeric confidence thresholds —
classification failure, unusable output, a not-yet-dispatchable route
(``notes_plus_model`` / ``notes_plus_knowledge``, RC-3 / RC-4), and an
empty question all take the same default branch, and the requested vs
effective distinction is preserved on the persisted
:class:`ChatRouteDecision` row and the returned result (R-6).

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

Every call — every contour — persists exactly one
:class:`ChatRouteDecision` row and logs a ``chat.routed`` line (R-11).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from memory_rag.core.answers.client import ChatClient, ChatProviderUnavailableError
from memory_rag.core.chat.classifier import (
    ChatRouteClassifier,
    ChatRouteClassifierUnavailableError,
    ChatRouteOutputError,
)
from memory_rag.core.chat.model_prompt import (
    MODEL_ONLY_PROMPT_VERSION,
    ModelOnlyAnswerError,
    build_model_only_prompt,
    parse_model_only_answer,
)
from memory_rag.core.chat.models import ChatRoute, ChatRouteDecision, RoutedChatResult
from memory_rag.core.domain.models import AnswerResult, AnswerTrace, FallbackMode, Query
from memory_rag.core.routing import InboundMessage
from memory_rag.logging import get_logger
from memory_rag.services.query_service import QueryService
from memory_rag.storage.repository import DomainRepository

log = get_logger(__name__)


class RoutedChatService:
    """Routes a ``/chat`` question to an answer pipeline (RC-2, D-108)."""

    def __init__(
        self,
        classifier: ChatRouteClassifier,
        query: QueryService,
        chat_client: ChatClient,
        repo: DomainRepository,
    ) -> None:
        self._classifier = classifier
        self._query = query
        self._chat = chat_client
        self._repo = repo

    def chat(
        self,
        message: InboundMessage,
        *,
        subject_scope: str | None = None,
    ) -> RoutedChatResult:
        """Classify and answer one routed-chat question.

        ``subject_scope`` passes through to the delegated retrieval
        exactly like ``QueryService.answer`` (H-3, D-107); there is no
        inbound subject syntax yet — the Telegram dispatcher passes
        none.
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
        # not-yet-dispatchable routes, and the empty question (D-108
        # fallback policy) — downstream wording must stay cause-neutral.
        if requested is ChatRoute.NOTES_LOOKUP or requested is ChatRoute.MODEL_ONLY:
            effective = requested
        else:
            effective = ChatRoute.NOTES_LOOKUP

        query_id: str | None
        if effective is ChatRoute.MODEL_ONLY:
            answer, query_id = self._answer_model_only(message, question)
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
