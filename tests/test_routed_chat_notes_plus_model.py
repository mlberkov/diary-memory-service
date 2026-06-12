"""The ``notes_plus_model`` route end-to-end on mocks (RC-3, D-108).

Covers: classify → rewrite → scoped enrichment retrieval → segmented
generation with per-segment provenance; every grading contour; the
cause-neutral rewrite-degrade paths (unusable output, provider
unavailable, no rewriter wired); the R-5 persistence shape (``Query``
with recorded ``subject_scope``, per-leg + merged ``RetrievalHit`` rows,
``notes-plus-model-v1`` ``AnswerTrace`` storing the raw segmented JSON
verbatim); the decision-then-rewrite trace chronology; R-3 / R-8 +
``subject_scope`` scoping forwarded to both legs *inside* enrichment
(the roadmap-mandated assertion, via a capturing fake search seam); and
the escalation clause reaching the provider verbatim on red-flag-style
prompts (mock providers, per D-108).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from memory_rag.adapters.answers import MockChatClient
from memory_rag.adapters.chat_routing import MockQueryRewriter, MockRouteClassifier
from memory_rag.adapters.embeddings import MockEmbeddingClient
from memory_rag.core.answers import ChatResponse
from memory_rag.core.chat import (
    ESCALATION_CLAUSE,
    NOTES_PLUS_MODEL_PROMPT_VERSION,
    ChatRoute,
    ChatRouteDecision,
    QueryRewrite,
    QueryRewriteOutputError,
    QueryRewriterUnavailableError,
    RoutedChatResult,
)
from memory_rag.core.domain import DateRange, FallbackMode
from memory_rag.core.domain.answer_prompt import AnswerPrompt
from memory_rag.core.domain.models import AnswerTrace, EventChunk, Query
from memory_rag.core.routing import InboundMessage, RouteKind
from memory_rag.services import DomainService, QueryService, RoutedChatService
from memory_rag.storage.mock import MockDomainStore
from tests.test_routed_chat_service import _DownChatClient, _JunkChatClient

_QUESTION = "what games would suit our son right now"


def _chat_msg(question: str = _QUESTION, *, chat: str = "42") -> InboundMessage:
    return InboundMessage(
        external_message_id="300",
        external_chat_id=chat,
        external_user_id="7",
        community_id=chat,
        text=f"/chat {question}",
        route=RouteKind.CHAT,
        received_at=datetime.now(tz=UTC),
        route_source="command",
        payload=question,
    )


def _ingest(
    store: MockDomainStore,
    payload: str,
    *,
    chat: str = "42",
    msg_id: str = "100",
    subject_id: str | None = None,
) -> None:
    DomainService(store, embedding_client=MockEmbeddingClient()).ingest(
        InboundMessage(
            external_message_id=msg_id,
            external_chat_id=chat,
            external_user_id="7",
            community_id=chat,
            text=f"/note {payload}",
            route=RouteKind.NOTE,
            received_at=datetime.now(tz=UTC),
            route_source="command",
            payload=payload,
            subject_id=subject_id,
        )
    )


class _SegmentedChatClient:
    """Fake provider emitting the segmented shape with a chosen uncertainty.

    Cites the prompt's own chunk ids so the I-9 citation check passes;
    captures every prompt for system-text assertions.
    """

    def __init__(
        self,
        *,
        uncertainty: str = "confident",
        cited: list[str] | None = None,
        model_text: str = "General guidance.",
    ) -> None:
        self._uncertainty = uncertainty
        self._cited = cited
        self._model_text = model_text
        self.prompts: list[AnswerPrompt] = []

    @property
    def model_name(self) -> str:
        return "mock-segmented"

    def complete(self, prompt: AnswerPrompt) -> ChatResponse:
        self.prompts.append(prompt)
        cited = self._cited if self._cited is not None else list(prompt.cited_chunk_ids)
        if self._uncertainty == "no_evidence":
            payload = {
                "notes_text": "",
                "cited_chunk_ids": [],
                "model_text": self._model_text,
                "notes_uncertainty": "no_evidence",
            }
        else:
            payload = {
                "notes_text": "Notes say he likes books.",
                "cited_chunk_ids": cited,
                "model_text": self._model_text,
                "notes_uncertainty": self._uncertainty,
            }
        raw_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return ChatResponse(
            raw_text=raw_text,
            model_name="mock-segmented",
            token_counts={"prompt": 1, "completion": len(raw_text)},
            latency_ms=3,
        )


class _BadOutputRewriter:
    @property
    def model_name(self) -> str:
        return "mock"

    def rewrite(self, question: str, *, today: date) -> QueryRewrite:
        raise QueryRewriteOutputError("no usable rewrite", raw_output='{"oops": true}')


class _UnavailableRewriter:
    @property
    def model_name(self) -> str:
        return "mock"

    def rewrite(self, question: str, *, today: date) -> QueryRewrite:
        raise QueryRewriterUnavailableError("provider down")


class _CapturingSearchRepo:
    """Records the scoping kwargs both legs were called with (R-3 / R-8)."""

    def __init__(self) -> None:
        self.dense_calls: list[dict[str, object]] = []
        self.sparse_calls: list[dict[str, object]] = []

    def dense_candidates(
        self,
        community_id: str,
        query_embedding: list[float],
        model_name: str,
        limit: int,
        *,
        date_range: DateRange | None = None,
        subject_scope: str | None = None,
    ) -> list[EventChunk]:
        self.dense_calls.append(
            {
                "community_id": community_id,
                "date_range": date_range,
                "subject_scope": subject_scope,
            }
        )
        return []

    def sparse_candidates(
        self,
        community_id: str,
        query_text: str,
        limit: int,
        *,
        date_range: DateRange | None = None,
        subject_scope: str | None = None,
    ) -> list[EventChunk]:
        self.sparse_calls.append(
            {
                "community_id": community_id,
                "query_text": query_text,
                "date_range": date_range,
                "subject_scope": subject_scope,
            }
        )
        return []


def _wire(
    store: MockDomainStore,
    *,
    chat_client: object | None = None,
    rewriter: object | None = None,
    search_repo: object | None = None,
    wire_rewriter: bool = True,
) -> RoutedChatService:
    chat = chat_client if chat_client is not None else MockChatClient()
    query = QueryService(
        store,
        search_repo if search_repo is not None else store,  # type: ignore[arg-type]
        MockEmbeddingClient(),
        chat,  # type: ignore[arg-type]
    )
    return RoutedChatService(
        MockRouteClassifier(default_route=ChatRoute.NOTES_PLUS_MODEL),
        query,
        chat,  # type: ignore[arg-type]
        store,
        rewriter=(
            (rewriter if rewriter is not None else MockQueryRewriter())  # type: ignore[arg-type]
            if wire_rewriter
            else None
        ),
    )


def _trace_rows(
    store: MockDomainStore, result: RoutedChatResult
) -> tuple[ChatRouteDecision, Query | None, AnswerTrace | None]:
    """Fetch (decision, query, answer_trace) for a RoutedChatResult."""
    decision = store.get_chat_route_decision(result.decision_id, community_id="42")
    assert decision is not None
    assert decision.query_id is not None
    query = store.get_query(decision.query_id, community_id="42")
    trace = store.get_answer_trace_for_query(decision.query_id, community_id="42")
    return decision, query, trace


# ---------------------------------------------------------------------------
# Dispatch + grading contours
# ---------------------------------------------------------------------------


def test_route_dispatches_with_requested_equal_to_effective() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nTried a new book")
    result = _wire(store).chat(_chat_msg("book"))
    assert result.requested_route is ChatRoute.NOTES_PLUS_MODEL
    assert result.effective_route is ChatRoute.NOTES_PLUS_MODEL


def test_success_carries_both_segments_and_persists_the_trace_shape() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nTried a new book")
    service = _wire(store)

    result = service.chat(_chat_msg("book"))

    answer = result.answer
    assert answer.fallback is FallbackMode.NONE
    assert answer.answer_text is not None and "chunk(s)" in answer.answer_text
    assert answer.model_text == "Mock general-knowledge segment."
    assert answer.cited_chunk_ids != ()
    assert answer.evidence != []

    decision, query, trace = _trace_rows(store, result)
    assert decision.requested_route is ChatRoute.NOTES_PLUS_MODEL
    assert decision.effective_route is ChatRoute.NOTES_PLUS_MODEL
    assert query is not None
    assert query.fallback is FallbackMode.NONE
    assert query.query_text == "book"
    assert query.model_name == MockEmbeddingClient().model_name
    assert trace is not None
    assert trace.prompt_version == NOTES_PLUS_MODEL_PROMPT_VERSION
    assert trace.fallback_mode is FallbackMode.NONE
    # The trace stores the raw segmented JSON verbatim (a mixed answer has
    # no single answer string; D-035 truthful provenance).
    parsed = json.loads(trace.answer_text)
    assert set(parsed) == {"notes_text", "cited_chunk_ids", "model_text", "notes_uncertainty"}
    # Per-leg + merged hits were written for the enrichment retrieval
    # (the mock dense leg may legitimately return no candidates here).
    assert decision.query_id is not None
    hits = store.get_retrieval_hits_for_query(decision.query_id, community_id="42")
    legs = {h.leg.value for h in hits}
    assert "merged" in legs
    assert "sparse" in legs


def test_weak_evidence_grades_and_keeps_both_segments() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nTried a new book")
    service = _wire(store, chat_client=_SegmentedChatClient(uncertainty="uncertain"))

    result = service.chat(_chat_msg("book"))

    assert result.answer.fallback is FallbackMode.WEAK_EVIDENCE
    assert result.answer.answer_text == "Notes say he likes books."
    assert result.answer.model_text == "General guidance."
    _, query, trace = _trace_rows(store, result)
    assert query is not None and query.fallback is FallbackMode.WEAK_EVIDENCE
    assert trace is not None and trace.fallback_mode is FallbackMode.WEAK_EVIDENCE


def test_empty_retrieval_still_generates_and_grades_no_evidence() -> None:
    """The route's point: empty diary evidence does not short-circuit —
    the model plane still answers, and the notes plane is honestly empty."""
    store = MockDomainStore()  # nothing ingested
    service = _wire(store)

    result = service.chat(_chat_msg())

    answer = result.answer
    assert answer.fallback is FallbackMode.NO_EVIDENCE
    assert answer.answer_text is None
    assert answer.model_text == "Mock general-knowledge segment."
    assert answer.cited_chunk_ids == ()
    decision, query, trace = _trace_rows(store, result)
    assert query is not None and query.fallback is FallbackMode.NO_EVIDENCE
    assert trace is not None
    assert trace.context_chunk_ids == ()
    assert decision.query_id is not None
    assert store.get_retrieval_hits_for_query(decision.query_id, community_id="42") == []


def test_provider_unavailable_grades_with_empty_trace_text() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nTried a new book")
    service = _wire(store, chat_client=_DownChatClient())

    result = service.chat(_chat_msg("book"))

    assert result.answer.fallback is FallbackMode.PROVIDER_UNAVAILABLE
    assert result.answer.answer_text is None
    assert result.answer.model_text is None
    _, query, trace = _trace_rows(store, result)
    assert query is not None and query.fallback is FallbackMode.PROVIDER_UNAVAILABLE
    assert trace is not None
    assert trace.answer_text == ""
    assert trace.token_counts == {}
    assert trace.latency_ms == 0


def test_parse_failure_preserves_raw_text_verbatim() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nTried a new book")
    service = _wire(store, chat_client=_JunkChatClient())

    result = service.chat(_chat_msg("book"))

    assert result.answer.fallback is FallbackMode.PARSE_FAILURE
    assert result.answer.model_text is None
    _, _, trace = _trace_rows(store, result)
    assert trace is not None
    assert trace.fallback_mode is FallbackMode.PARSE_FAILURE
    assert trace.answer_text == "not json at all"


def test_fabricated_citation_fails_closed_as_parse_failure() -> None:
    """Never render fabricated provenance (I-9): a response citing chunks
    outside the context grades PARSE_FAILURE."""
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nTried a new book")
    service = _wire(store, chat_client=_SegmentedChatClient(cited=["c-fabricated"]))

    result = service.chat(_chat_msg("book"))

    assert result.answer.fallback is FallbackMode.PARSE_FAILURE
    assert result.answer.answer_text is None
    assert result.answer.model_text is None


# ---------------------------------------------------------------------------
# Rewrite step
# ---------------------------------------------------------------------------


def test_rewritten_query_and_date_range_drive_the_retrieval() -> None:
    search = _CapturingSearchRepo()
    store = MockDomainStore()
    rng = DateRange(start=date(2026, 5, 1), end=date(2026, 5, 31))
    service = _wire(
        store,
        search_repo=search,
        rewriter=MockQueryRewriter(rewrite_to="toddler games", date_range=rng),
    )

    result = service.chat(_chat_msg())

    assert search.sparse_calls[0]["query_text"] == "toddler games"
    assert search.sparse_calls[0]["date_range"] == rng
    assert search.dense_calls[0]["date_range"] == rng
    rewrite = store.get_chat_query_rewrite_for_decision(result.decision_id, community_id="42")
    assert rewrite is not None
    assert rewrite.rewritten_query == "toddler games"
    assert rewrite.date_start == date(2026, 5, 1)
    assert rewrite.date_end == date(2026, 5, 31)
    assert rewrite.subject_scope is None
    # The Query row still carries the original question; the rewrite lives
    # in its own trace row.
    decision, query, _ = _trace_rows(store, result)
    assert query is not None and query.query_text == _QUESTION


@pytest.mark.parametrize(
    ("rewriter", "wire_rewriter", "expected_raw"),
    [
        (_BadOutputRewriter(), True, '{"oops": true}'),
        (_UnavailableRewriter(), True, ""),
        (None, False, ""),
    ],
    ids=["unusable-output", "provider-unavailable", "no-rewriter-wired"],
)
def test_rewrite_failure_degrades_to_the_original_question(
    rewriter: object | None, wire_rewriter: bool, expected_raw: str
) -> None:
    search = _CapturingSearchRepo()
    store = MockDomainStore()
    service = _wire(store, search_repo=search, rewriter=rewriter, wire_rewriter=wire_rewriter)

    result = service.chat(_chat_msg())

    # Retrieval ran on the (normalized) original question, no date constraint.
    assert search.sparse_calls[0]["query_text"] == _QUESTION
    assert search.sparse_calls[0]["date_range"] is None
    # The answer still has both planes available (mock model segment).
    assert result.answer.fallback is FallbackMode.NO_EVIDENCE
    assert result.answer.model_text == "Mock general-knowledge segment."
    # The rewrite row records the degraded shape truthfully.
    rewrite = store.get_chat_query_rewrite_for_decision(result.decision_id, community_id="42")
    assert rewrite is not None
    assert rewrite.rewritten_query is None
    assert rewrite.date_start is None
    assert rewrite.date_end is None
    assert rewrite.rewriter_raw_output == expected_raw


def test_a_rewrite_normalizing_to_empty_degrades_the_same_way() -> None:
    search = _CapturingSearchRepo()
    store = MockDomainStore()
    service = _wire(store, search_repo=search, rewriter=MockQueryRewriter(rewrite_to="???"))

    result = service.chat(_chat_msg())

    assert search.sparse_calls[0]["query_text"] == _QUESTION
    rewrite = store.get_chat_query_rewrite_for_decision(result.decision_id, community_id="42")
    assert rewrite is not None
    assert rewrite.rewritten_query is None


def test_every_execution_writes_exactly_one_rewrite_row_after_the_decision() -> None:
    store = MockDomainStore()
    service = _wire(store)
    result = service.chat(_chat_msg())
    # The mock store enforces decision-row-first (unknown decision_id raises)
    # and one-row-per-decision; reaching here proves the chronology held.
    assert store.len_chat_query_rewrites() == 1
    rewrite = store.get_chat_query_rewrite_for_decision(result.decision_id, community_id="42")
    assert rewrite is not None
    assert rewrite.decision_id == result.decision_id


def test_funnelled_routes_write_no_rewrite_row() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nTried a new book")
    chat = MockChatClient()
    query = QueryService(store, store, MockEmbeddingClient(), chat)
    service = RoutedChatService(
        MockRouteClassifier(default_route=ChatRoute.NOTES_LOOKUP),
        query,
        chat,
        store,
        rewriter=MockQueryRewriter(),
    )
    service.chat(_chat_msg("book"))
    assert store.len_chat_query_rewrites() == 0


# ---------------------------------------------------------------------------
# Scoping inside enrichment (R-3 / R-8 + subject_scope; roadmap-mandated)
# ---------------------------------------------------------------------------


def test_enrichment_retrieval_forwards_scoping_to_both_legs() -> None:
    search = _CapturingSearchRepo()
    store = MockDomainStore()
    service = _wire(store, search_repo=search)

    service.chat(_chat_msg(), subject_scope="kid-1")

    for leg_calls in (search.dense_calls, search.sparse_calls):
        assert len(leg_calls) == 1
        assert leg_calls[0]["community_id"] == "42"
        assert leg_calls[0]["subject_scope"] == "kid-1"


def test_caller_subject_scope_wins_even_if_a_rewriter_emits_one() -> None:
    """The service never applies a rewriter-emitted subject — only the
    caller's (docs/assumptions.md)."""

    class _SubjectEmittingRewriter:
        @property
        def model_name(self) -> str:
            return "mock"

        def rewrite(self, question: str, *, today: date) -> QueryRewrite:
            return QueryRewrite(
                retrieval_query=question,
                date_range=None,
                subject_scope="smuggled-subject",
                raw_output="{}",
                model_name="mock",
                latency_ms=0,
            )

    search = _CapturingSearchRepo()
    store = MockDomainStore()
    service = _wire(store, search_repo=search, rewriter=_SubjectEmittingRewriter())

    result = service.chat(_chat_msg(), subject_scope="kid-1")

    assert search.dense_calls[0]["subject_scope"] == "kid-1"
    assert search.sparse_calls[0]["subject_scope"] == "kid-1"
    # The emitted value is still recorded truthfully in the trace row.
    rewrite = store.get_chat_query_rewrite_for_decision(result.decision_id, community_id="42")
    assert rewrite is not None
    assert rewrite.subject_scope == "smuggled-subject"


def test_subject_scope_is_recorded_on_the_query_row() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nTried a new book", subject_id="kid-1")
    service = _wire(store)

    result = service.chat(_chat_msg("book"), subject_scope="kid-1")

    _, query, _ = _trace_rows(store, result)
    assert query is not None
    assert query.subject_scope == "kid-1"


def test_community_scoping_never_crosses_communities() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nTried a new book", chat="A", msg_id="100")
    _ingest(store, "2026-05-09\nSecret book of B", chat="B", msg_id="101")
    service = _wire(store)

    result = service.chat(_chat_msg("book", chat="A"))

    texts = {e.chunk_text for e in result.answer.evidence}
    assert "Secret book of B" not in texts


# ---------------------------------------------------------------------------
# Escalation invariant (D-108 medical amendment)
# ---------------------------------------------------------------------------


def test_red_flag_style_prompt_carries_the_escalation_clause_verbatim() -> None:
    """The escalation rule is a system-prompt invariant of this route:
    every generation call — red-flag-style or not — carries the clause."""
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nHe is 20 months old")
    capturing = _SegmentedChatClient()
    service = _wire(store, chat_client=capturing)

    service.chat(_chat_msg("my son is 20 months and still doesn't walk — what games suit him?"))

    assert len(capturing.prompts) == 1
    assert ESCALATION_CLAUSE in capturing.prompts[0].system_text
    assert capturing.prompts[0].prompt_version == NOTES_PLUS_MODEL_PROMPT_VERSION
