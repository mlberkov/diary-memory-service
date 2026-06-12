"""The ``notes_plus_knowledge`` route end-to-end on mocks (RC-4, D-108).

Covers: classify → rewrite → scoped enrichment retrieval → outward
rewrite conditioned on retrieved chunks → knowledge search → segmented
generation with per-segment provenance; every grading contour; the
cause-neutral degrade paths (outward-rewrite failure to the stripped
original question; knowledge-search failure to an empty knowledge
plane); the dispatch-vs-funnel split on whether a knowledge source is
wired; the R-5 persistence shape (``notes-plus-knowledge-v1``
``AnswerTrace`` storing the raw segmented JSON verbatim); the
decision-then-rewrite-then-knowledge trace chronology; R-3 / R-8 +
``subject_scope`` scoping forwarded to both legs inside enrichment; and
the escalation clause reaching the provider verbatim (mock providers,
per D-108).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from memory_rag.adapters.answers import MockChatClient
from memory_rag.adapters.chat_routing import (
    MockOutwardRewriter,
    MockQueryRewriter,
    MockRouteClassifier,
)
from memory_rag.adapters.embeddings import MockEmbeddingClient
from memory_rag.adapters.knowledge import MockKnowledgeSource
from memory_rag.core.answers import ChatResponse
from memory_rag.core.chat import (
    ESCALATION_CLAUSE,
    NOTES_PLUS_KNOWLEDGE_PROMPT_VERSION,
    ChatRoute,
    ChatRouteDecision,
    KnowledgeExcerpt,
    KnowledgeResult,
    KnowledgeSourceOutputError,
    KnowledgeSourceUnavailableError,
    OutwardRewrite,
    OutwardRewriteOutputError,
    OutwardRewriterUnavailableError,
    RoutedChatResult,
)
from memory_rag.core.domain import FallbackMode
from memory_rag.core.domain.answer_prompt import AnswerPrompt
from memory_rag.core.domain.models import AnswerTrace, Query
from memory_rag.core.routing import InboundMessage, RouteKind
from memory_rag.services import DomainService, QueryService, RoutedChatService
from memory_rag.storage.mock import MockDomainStore
from tests.test_routed_chat_notes_plus_model import _CapturingSearchRepo
from tests.test_routed_chat_service import _DownChatClient, _JunkChatClient

_QUESTION = "why does our son refuse naps lately"

_EXCERPTS = (
    KnowledgeExcerpt(ref="https://example.org/naps", title="Nap science", text="nap facts"),
)


def _chat_msg(question: str = _QUESTION, *, chat: str = "42") -> InboundMessage:
    return InboundMessage(
        external_message_id="400",
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


class _SixFieldChatClient:
    """Fake provider emitting the six-field shape with chosen planes.

    Cites the prompt's own chunk ids and knowledge refs so the I-9
    checks pass; captures every prompt for system-text assertions.
    """

    def __init__(
        self,
        *,
        uncertainty: str = "confident",
        cited: list[str] | None = None,
        refs: list[str] | None = None,
        knowledge_text: str = "Web says naps shift at this age.",
        model_text: str = "General guidance.",
    ) -> None:
        self._uncertainty = uncertainty
        self._cited = cited
        self._refs = refs
        self._knowledge_text = knowledge_text
        self._model_text = model_text
        self.prompts: list[AnswerPrompt] = []

    @property
    def model_name(self) -> str:
        return "mock-six-field"

    def complete(self, prompt: AnswerPrompt) -> ChatResponse:
        self.prompts.append(prompt)
        refs = self._refs if self._refs is not None else list(prompt.knowledge_refs)
        knowledge_text = self._knowledge_text if refs else ""
        if not knowledge_text:
            refs = []
        payload: dict[str, object] = {
            "knowledge_text": knowledge_text,
            "cited_knowledge_refs": refs,
            "model_text": self._model_text,
        }
        cited = self._cited if self._cited is not None else list(prompt.cited_chunk_ids)
        if self._uncertainty == "no_evidence" or not cited:
            payload.update(
                {"notes_text": "", "cited_chunk_ids": [], "notes_uncertainty": "no_evidence"}
            )
        else:
            payload.update(
                {
                    "notes_text": "Notes say he naps badly after busy days.",
                    "cited_chunk_ids": cited,
                    "notes_uncertainty": self._uncertainty,
                }
            )
        raw_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return ChatResponse(
            raw_text=raw_text,
            model_name="mock-six-field",
            token_counts={"prompt": 1, "completion": len(raw_text)},
            latency_ms=3,
        )


class _DownKnowledgeSource:
    @property
    def provider_name(self) -> str:
        return "mock"

    def search(self, query: str) -> KnowledgeResult:
        raise KnowledgeSourceUnavailableError("provider down")


class _JunkKnowledgeSource:
    @property
    def provider_name(self) -> str:
        return "mock"

    def search(self, query: str) -> KnowledgeResult:
        raise KnowledgeSourceOutputError("no usable result", raw_output="<html>junk</html>")


class _CapturingKnowledgeSource:
    """Records the searched query; returns scripted excerpts."""

    def __init__(self, excerpts: tuple[KnowledgeExcerpt, ...] = _EXCERPTS) -> None:
        self._excerpts = excerpts
        self.queries: list[str] = []

    @property
    def provider_name(self) -> str:
        return "mock"

    def search(self, query: str) -> KnowledgeResult:
        self.queries.append(query)
        return KnowledgeResult(
            excerpts=self._excerpts, raw_output='{"results": ["scripted"]}', latency_ms=2
        )


class _BadOutwardRewriter:
    @property
    def model_name(self) -> str:
        return "mock"

    def rewrite_outward(self, question: str, *, notes_context: tuple[str, ...]) -> OutwardRewrite:
        raise OutwardRewriteOutputError("no usable rewrite", raw_output='{"oops": true}')


class _UnavailableOutwardRewriter:
    @property
    def model_name(self) -> str:
        return "mock"

    def rewrite_outward(self, question: str, *, notes_context: tuple[str, ...]) -> OutwardRewrite:
        raise OutwardRewriterUnavailableError("provider down")


def _wire(
    store: MockDomainStore,
    *,
    chat_client: object | None = None,
    knowledge_source: object | None = None,
    wire_knowledge: bool = True,
    outward_rewriter: object | None = None,
    wire_outward: bool = True,
    search_repo: object | None = None,
) -> RoutedChatService:
    chat = chat_client if chat_client is not None else _SixFieldChatClient()
    query = QueryService(
        store,
        search_repo if search_repo is not None else store,  # type: ignore[arg-type]
        MockEmbeddingClient(),
        chat,  # type: ignore[arg-type]
    )
    return RoutedChatService(
        MockRouteClassifier(default_route=ChatRoute.NOTES_PLUS_KNOWLEDGE),
        query,
        chat,  # type: ignore[arg-type]
        store,
        rewriter=MockQueryRewriter(),
        knowledge_source=(
            (
                knowledge_source
                if knowledge_source is not None
                else MockKnowledgeSource(excerpts=_EXCERPTS)
            )  # type: ignore[arg-type]
            if wire_knowledge
            else None
        ),
        outward_rewriter=(
            (outward_rewriter if outward_rewriter is not None else MockOutwardRewriter())  # type: ignore[arg-type]
            if wire_outward
            else None
        ),
    )


def _trace_rows(
    store: MockDomainStore, result: RoutedChatResult
) -> tuple[ChatRouteDecision, Query | None, AnswerTrace | None]:
    decision = store.get_chat_route_decision(result.decision_id, community_id="42")
    assert decision is not None
    assert decision.query_id is not None
    query = store.get_query(decision.query_id, community_id="42")
    trace = store.get_answer_trace_for_query(decision.query_id, community_id="42")
    return decision, query, trace


# ---------------------------------------------------------------------------
# Dispatch vs funnel
# ---------------------------------------------------------------------------


def test_route_dispatches_when_a_knowledge_source_is_wired() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nSkipped his nap again")
    result = _wire(store).chat(_chat_msg())
    assert result.requested_route is ChatRoute.NOTES_PLUS_KNOWLEDGE
    assert result.effective_route is ChatRoute.NOTES_PLUS_KNOWLEDGE


def test_route_funnels_to_notes_lookup_when_no_knowledge_source_is_wired() -> None:
    """The RC-2 funnel shape survives: requested-vs-effective preserved,
    no rewrite or knowledge rows written."""
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nSkipped his nap again")
    result = _wire(store, chat_client=MockChatClient(), wire_knowledge=False).chat(_chat_msg())
    assert result.requested_route is ChatRoute.NOTES_PLUS_KNOWLEDGE
    assert result.effective_route is ChatRoute.NOTES_LOOKUP
    assert store.len_chat_query_rewrites() == 0
    assert store.len_chat_knowledge_searches() == 0


# ---------------------------------------------------------------------------
# Grading contours + persistence shape
# ---------------------------------------------------------------------------


def test_success_carries_all_three_segments_and_persists_the_trace_shape() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nSkipped his nap again")
    result = _wire(store).chat(_chat_msg("nap"))

    answer = result.answer
    assert answer.fallback is FallbackMode.NONE
    assert answer.answer_text == "Notes say he naps badly after busy days."
    assert answer.knowledge_text == "Web says naps shift at this age."
    assert answer.knowledge_refs == ("https://example.org/naps",)
    assert answer.model_text == "General guidance."
    assert answer.cited_chunk_ids != ()

    decision, query, trace = _trace_rows(store, result)
    assert decision.effective_route is ChatRoute.NOTES_PLUS_KNOWLEDGE
    assert query is not None and query.fallback is FallbackMode.NONE
    assert query.query_text == "nap"
    assert trace is not None
    assert trace.prompt_version == NOTES_PLUS_KNOWLEDGE_PROMPT_VERSION
    # The trace stores the raw segmented JSON verbatim.
    parsed = json.loads(trace.answer_text)
    assert set(parsed) == {
        "notes_text",
        "cited_chunk_ids",
        "knowledge_text",
        "cited_knowledge_refs",
        "model_text",
        "notes_uncertainty",
    }
    assert decision.query_id is not None
    hits = store.get_retrieval_hits_for_query(decision.query_id, community_id="42")
    assert {h.leg.value for h in hits} >= {"sparse", "merged"}


def test_empty_retrieval_still_generates_with_the_knowledge_plane() -> None:
    store = MockDomainStore()  # nothing ingested
    result = _wire(store).chat(_chat_msg())
    answer = result.answer
    assert answer.fallback is FallbackMode.NO_EVIDENCE
    assert answer.answer_text is None
    assert answer.knowledge_text == "Web says naps shift at this age."
    assert answer.model_text == "General guidance."


def test_provider_unavailable_grades_with_empty_planes() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nSkipped his nap again")
    result = _wire(store, chat_client=_DownChatClient()).chat(_chat_msg("nap"))
    assert result.answer.fallback is FallbackMode.PROVIDER_UNAVAILABLE
    assert result.answer.answer_text is None
    assert result.answer.knowledge_text is None
    assert result.answer.model_text is None
    _, query, trace = _trace_rows(store, result)
    assert query is not None and query.fallback is FallbackMode.PROVIDER_UNAVAILABLE
    assert trace is not None and trace.answer_text == ""


def test_parse_failure_preserves_raw_text_verbatim() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nSkipped his nap again")
    result = _wire(store, chat_client=_JunkChatClient()).chat(_chat_msg("nap"))
    assert result.answer.fallback is FallbackMode.PARSE_FAILURE
    assert result.answer.knowledge_text is None
    _, _, trace = _trace_rows(store, result)
    assert trace is not None and trace.answer_text == "not json at all"


def test_fabricated_knowledge_ref_fails_closed_as_parse_failure() -> None:
    """Never render fabricated provenance (generalized I-9): a response
    citing refs outside the offered excerpts grades PARSE_FAILURE."""
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nSkipped his nap again")
    service = _wire(store, chat_client=_SixFieldChatClient(refs=["https://fabricated.example.org"]))
    result = service.chat(_chat_msg("nap"))
    assert result.answer.fallback is FallbackMode.PARSE_FAILURE
    assert result.answer.knowledge_text is None
    assert result.answer.model_text is None


# ---------------------------------------------------------------------------
# Outward rewrite + search degradation
# ---------------------------------------------------------------------------


def test_outward_rewrite_conditions_on_retrieved_chunks_and_drives_the_search() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nSkipped his nap again")
    outward = MockOutwardRewriter(rewrite_to="toddler nap refusal causes")
    knowledge = _CapturingKnowledgeSource()
    service = _wire(store, knowledge_source=knowledge, outward_rewriter=outward)

    result = service.chat(_chat_msg("nap"))

    assert outward.last_notes_context is not None
    assert any("nap" in text for text in outward.last_notes_context)
    assert knowledge.queries == ["toddler nap refusal causes"]
    search_row = store.get_chat_knowledge_search_for_decision(result.decision_id, community_id="42")
    assert search_row is not None
    assert search_row.outward_query == "toddler nap refusal causes"
    assert search_row.result_count == 1
    assert search_row.provider_name == "mock"


@pytest.mark.parametrize(
    ("outward_rewriter", "wire_outward", "expected_raw"),
    [
        (_BadOutwardRewriter(), True, '{"oops": true}'),
        (_UnavailableOutwardRewriter(), True, ""),
        (None, False, ""),
    ],
    ids=["unusable-output", "provider-unavailable", "no-rewriter-wired"],
)
def test_outward_rewrite_failure_degrades_to_the_original_question(
    outward_rewriter: object | None, wire_outward: bool, expected_raw: str
) -> None:
    store = MockDomainStore()
    knowledge = _CapturingKnowledgeSource()
    service = _wire(
        store,
        knowledge_source=knowledge,
        outward_rewriter=outward_rewriter,
        wire_outward=wire_outward,
    )

    result = service.chat(_chat_msg())

    # The search ran on the stripped original question.
    assert knowledge.queries == [_QUESTION]
    search_row = store.get_chat_knowledge_search_for_decision(result.decision_id, community_id="42")
    assert search_row is not None
    assert search_row.outward_query == _QUESTION
    assert search_row.outward_rewriter_raw_output == expected_raw


@pytest.mark.parametrize(
    "knowledge_source",
    [_DownKnowledgeSource(), _JunkKnowledgeSource()],
    ids=["provider-unavailable", "unusable-output"],
)
def test_search_failure_degrades_within_the_route_to_an_empty_knowledge_plane(
    knowledge_source: object,
) -> None:
    """Generation still runs (the route's point); the reply stays
    cause-neutral; the trace row records the failure truthfully."""
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nSkipped his nap again")
    service = _wire(store, knowledge_source=knowledge_source)

    result = service.chat(_chat_msg("nap"))

    answer = result.answer
    # Effective route stays notes_plus_knowledge; generation ran.
    assert result.effective_route is ChatRoute.NOTES_PLUS_KNOWLEDGE
    assert answer.fallback is FallbackMode.NONE
    assert answer.answer_text is not None
    assert answer.knowledge_text is None
    assert answer.knowledge_refs == ()
    assert answer.model_text == "General guidance."
    search_row = store.get_chat_knowledge_search_for_decision(result.decision_id, community_id="42")
    assert search_row is not None
    assert search_row.result_count == 0
    expected_raw = "<html>junk</html>" if isinstance(knowledge_source, _JunkKnowledgeSource) else ""
    assert search_row.raw_output == expected_raw


# ---------------------------------------------------------------------------
# Trace chronology
# ---------------------------------------------------------------------------


def test_every_execution_writes_one_rewrite_and_one_knowledge_row_after_the_decision() -> None:
    store = MockDomainStore()
    service = _wire(store)
    result = service.chat(_chat_msg())
    # The mock store enforces decision-row-first (unknown decision_id raises)
    # and one-row-per-decision; reaching here proves the chronology held.
    assert store.len_chat_query_rewrites() == 1
    assert store.len_chat_knowledge_searches() == 1
    search_row = store.get_chat_knowledge_search_for_decision(result.decision_id, community_id="42")
    assert search_row is not None
    assert search_row.decision_id == result.decision_id


def test_retrieval_seam_unavailable_writes_no_rows() -> None:
    class _NoRetrieval:
        def dense_candidates(self, *args: object, **kwargs: object) -> list[object]:
            raise NotImplementedError("no retrieval backend")

        def sparse_candidates(self, *args: object, **kwargs: object) -> list[object]:
            raise NotImplementedError("no retrieval backend")

    store = MockDomainStore()
    service = _wire(store, search_repo=_NoRetrieval())

    result = service.chat(_chat_msg())

    assert result.answer.fallback is FallbackMode.NO_EVIDENCE
    decision = store.get_chat_route_decision(result.decision_id, community_id="42")
    assert decision is not None
    assert decision.query_id is None
    assert store.len_chat_query_rewrites() == 0
    assert store.len_chat_knowledge_searches() == 0


def test_other_routes_write_no_knowledge_row() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nSkipped his nap again")
    chat = MockChatClient()
    query = QueryService(store, store, MockEmbeddingClient(), chat)
    service = RoutedChatService(
        MockRouteClassifier(default_route=ChatRoute.NOTES_PLUS_MODEL),
        query,
        chat,
        store,
        rewriter=MockQueryRewriter(),
        knowledge_source=MockKnowledgeSource(excerpts=_EXCERPTS),
        outward_rewriter=MockOutwardRewriter(),
    )
    service.chat(_chat_msg("nap"))
    assert store.len_chat_knowledge_searches() == 0


# ---------------------------------------------------------------------------
# Scoping inside enrichment (R-3 / R-8 + subject_scope)
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


def test_subject_scope_is_recorded_on_the_query_row() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nSkipped his nap again", subject_id="kid-1")
    result = _wire(store).chat(_chat_msg("nap"), subject_scope="kid-1")
    _, query, _ = _trace_rows(store, result)
    assert query is not None
    assert query.subject_scope == "kid-1"


def test_community_scoping_never_crosses_communities() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nSkipped his nap again", chat="A", msg_id="100")
    _ingest(store, "2026-05-09\nSecret nap of B", chat="B", msg_id="101")
    service = _wire(store)

    result = service.chat(_chat_msg("nap", chat="A"))

    texts = {e.chunk_text for e in result.answer.evidence}
    assert "Secret nap of B" not in texts


# ---------------------------------------------------------------------------
# Escalation invariant (D-108 medical amendment; RC-4 closure requirement)
# ---------------------------------------------------------------------------


def test_red_flag_style_prompt_carries_the_escalation_clause_verbatim() -> None:
    """The escalation rule is a system-prompt invariant of this route:
    every generation call — red-flag-style or not — carries the clause
    byte-identically (the shared RC-3 constant, D-110)."""
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nHe is 20 months old")
    capturing = _SixFieldChatClient()
    service = _wire(store, chat_client=capturing)

    service.chat(_chat_msg("my son is 20 months and still doesn't walk — what should we do?"))

    assert len(capturing.prompts) == 1
    assert ESCALATION_CLAUSE in capturing.prompts[0].system_text
    assert capturing.prompts[0].prompt_version == NOTES_PLUS_KNOWLEDGE_PROMPT_VERSION


def test_a_specialist_recommendation_answer_parses_through_unaltered() -> None:
    """A red-flag answer that recommends consulting a specialist survives
    parsing and grading untouched (nothing strips or rewrites it)."""
    specialist_text = (
        "This could have many causes; please consult a qualified specialist "
        "such as your pediatrician."
    )
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nHe is 20 months old")
    service = _wire(store, chat_client=_SixFieldChatClient(model_text=specialist_text))

    result = service.chat(_chat_msg("he is 20 months and still doesn't walk"))

    assert result.answer.model_text == specialist_text
