"""RoutedChatService dispatch, fallback, and trace tests (RC-2, D-108).

Mock fixtures throughout (store, embeddings, chat, classifier). Covers:
classify → dispatch → labeled answer on the two dispatchable routes;
the single fallback funnel (classifier unavailable, unusable output,
not-yet-dispatchable routes, empty question) with requested vs effective
preserved (R-6); the per-call ``ChatRouteDecision`` row; the model_only
``Query`` + ``AnswerTrace`` shape (R-5); R-3 community scoping; and the
``subject_scope`` passthrough (H-3, D-107).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from memory_rag.adapters.answers import MockChatClient
from memory_rag.adapters.chat_routing import MockRouteClassifier
from memory_rag.adapters.embeddings import MockEmbeddingClient
from memory_rag.core.answers import ChatProviderUnavailableError, ChatResponse
from memory_rag.core.chat import (
    MODEL_ONLY_PROMPT_VERSION,
    ChatRoute,
    ChatRouteClassifierUnavailableError,
    ChatRouteDecision,
    ChatRouteOutputError,
    RouteClassification,
)
from memory_rag.core.domain import FallbackMode
from memory_rag.core.domain.answer_prompt import AnswerPrompt
from memory_rag.core.routing import InboundMessage, RouteKind
from memory_rag.services import DomainService, QueryService, RoutedChatService
from memory_rag.storage.mock import MockDomainStore
from memory_rag.storage.sqlite import SqliteDomainStore


def _chat_msg(question: str, *, chat: str = "42", user: str = "7") -> InboundMessage:
    return InboundMessage(
        external_message_id="300",
        external_chat_id=chat,
        external_user_id=user,
        community_id=chat,
        text=f"/chat {question}",
        route=RouteKind.CHAT,
        received_at=datetime.now(tz=UTC),
        route_source="command",
        payload=question,
    )


def _note(
    payload: str,
    *,
    chat: str = "42",
    msg_id: str = "100",
    subject_id: str | None = None,
) -> InboundMessage:
    return InboundMessage(
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


def _ingest(
    store: MockDomainStore,
    payload: str,
    *,
    chat: str = "42",
    msg_id: str = "100",
    subject_id: str | None = None,
) -> None:
    DomainService(store, embedding_client=MockEmbeddingClient()).ingest(
        _note(payload, chat=chat, msg_id=msg_id, subject_id=subject_id)
    )


class _UnavailableClassifier:
    @property
    def model_name(self) -> str:
        return "mock"

    def classify(self, question: str) -> RouteClassification:
        raise ChatRouteClassifierUnavailableError("provider down")


class _BadOutputClassifier:
    @property
    def model_name(self) -> str:
        return "mock"

    def classify(self, question: str) -> RouteClassification:
        raise ChatRouteOutputError("unknown route", raw_output='{"route": "web_only"}')


class _CountingClassifier(MockRouteClassifier):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def classify(self, question: str) -> RouteClassification:
        self.calls += 1
        return super().classify(question)


class _JunkChatClient:
    """Chat client returning unparseable model-only output."""

    @property
    def model_name(self) -> str:
        return "mock-junk"

    def complete(self, prompt: AnswerPrompt) -> ChatResponse:
        return ChatResponse(
            raw_text="not json at all",
            model_name="mock-junk",
            token_counts={"prompt": 1, "completion": 1},
            latency_ms=5,
        )


class _DownChatClient:
    @property
    def model_name(self) -> str:
        return "mock-down"

    def complete(self, prompt: AnswerPrompt) -> ChatResponse:
        raise ChatProviderUnavailableError("chat provider down")


def _wire(
    store: MockDomainStore | SqliteDomainStore,
    *,
    classifier: object | None = None,
    chat_client: object | None = None,
) -> RoutedChatService:
    chat = chat_client if chat_client is not None else MockChatClient()
    query = QueryService(store, store, MockEmbeddingClient(), chat)  # type: ignore[arg-type]
    return RoutedChatService(
        classifier if classifier is not None else MockRouteClassifier(),  # type: ignore[arg-type]
        query,
        chat,  # type: ignore[arg-type]
        store,
    )


def _decision(
    store: MockDomainStore, decision_id: str, *, community_id: str = "42"
) -> ChatRouteDecision:
    decision = store.get_chat_route_decision(decision_id, community_id=community_id)
    assert decision is not None
    return decision


# ---------------------------------------------------------------------------
# notes_lookup delegation
# ---------------------------------------------------------------------------


def test_notes_lookup_delegates_to_the_grounded_ask() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nTried a new book")
    service = _wire(store)

    result = service.chat(_chat_msg("book"))

    assert result.requested_route is ChatRoute.NOTES_LOOKUP
    assert result.effective_route is ChatRoute.NOTES_LOOKUP
    assert result.answer.fallback is FallbackMode.NONE
    assert result.answer.context is not None
    # The delegated seam persisted the /ask-shaped rows.
    query_id = result.answer.context.query_id
    assert store.get_query(query_id, community_id="42") is not None
    assert store.get_answer_trace_for_query(query_id, community_id="42") is not None
    # The decision row links the same Query row.
    decision = _decision(store, result.decision_id)
    assert decision.query_id == query_id
    assert decision.requested_route is ChatRoute.NOTES_LOOKUP
    assert decision.effective_route is ChatRoute.NOTES_LOOKUP


def test_notes_lookup_answer_matches_a_direct_query_service_answer() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nTried a new book")
    service = _wire(store)
    direct = QueryService(store, store, MockEmbeddingClient(), MockChatClient())

    routed = service.chat(_chat_msg("book")).answer
    ask = direct.answer(
        InboundMessage(
            external_message_id="301",
            external_chat_id="42",
            external_user_id="7",
            community_id="42",
            text="/ask book",
            route=RouteKind.ASK,
            received_at=datetime.now(tz=UTC),
            route_source="command",
            payload="book",
        )
    )

    assert routed.fallback is ask.fallback
    assert routed.answer_text == ask.answer_text
    assert routed.cited_chunk_ids == ask.cited_chunk_ids


# ---------------------------------------------------------------------------
# model_only
# ---------------------------------------------------------------------------


def test_model_only_answers_with_its_own_query_and_trace() -> None:
    store = MockDomainStore()
    service = _wire(store)
    chat_model = MockChatClient().model_name

    result = service.chat(_chat_msg("what is model_only phonemic awareness"))

    assert result.requested_route is ChatRoute.MODEL_ONLY
    assert result.effective_route is ChatRoute.MODEL_ONLY
    assert result.answer.fallback is FallbackMode.NONE
    assert result.answer.answer_text == "Mock model-knowledge answer (no notes consulted)."
    assert result.answer.cited_chunk_ids == ()
    assert result.answer.evidence == []

    decision = _decision(store, result.decision_id)
    assert decision.query_id is not None
    query = store.get_query(decision.query_id, community_id="42")
    assert query is not None
    assert query.fallback is FallbackMode.NONE
    assert query.model_name == chat_model
    assert query.subject_scope is None
    assert store.get_retrieval_hits_for_query(decision.query_id, community_id="42") == []
    trace = store.get_answer_trace_for_query(decision.query_id, community_id="42")
    assert trace is not None
    assert trace.prompt_version == MODEL_ONLY_PROMPT_VERSION
    assert trace.context_chunk_ids == ()
    assert trace.fallback_mode is FallbackMode.NONE


def test_model_only_provider_unavailable_grades_and_traces() -> None:
    store = MockDomainStore()
    service = _wire(
        store,
        classifier=MockRouteClassifier(default_route=ChatRoute.MODEL_ONLY),
        chat_client=_DownChatClient(),
    )

    result = service.chat(_chat_msg("anything at all"))

    assert result.effective_route is ChatRoute.MODEL_ONLY
    assert result.answer.fallback is FallbackMode.PROVIDER_UNAVAILABLE
    decision = _decision(store, result.decision_id)
    assert decision.query_id is not None
    trace = store.get_answer_trace_for_query(decision.query_id, community_id="42")
    assert trace is not None
    assert trace.fallback_mode is FallbackMode.PROVIDER_UNAVAILABLE
    assert trace.answer_text == ""
    assert trace.token_counts == {}
    assert trace.latency_ms == 0


def test_model_only_parse_failure_preserves_raw_text() -> None:
    store = MockDomainStore()
    service = _wire(
        store,
        classifier=MockRouteClassifier(default_route=ChatRoute.MODEL_ONLY),
        chat_client=_JunkChatClient(),
    )

    result = service.chat(_chat_msg("anything at all"))

    assert result.answer.fallback is FallbackMode.PARSE_FAILURE
    decision = _decision(store, result.decision_id)
    assert decision.query_id is not None
    trace = store.get_answer_trace_for_query(decision.query_id, community_id="42")
    assert trace is not None
    assert trace.fallback_mode is FallbackMode.PARSE_FAILURE
    assert trace.answer_text == "not json at all"
    assert trace.latency_ms == 5


# ---------------------------------------------------------------------------
# Fallback funnel (R-6)
# ---------------------------------------------------------------------------


def test_classifier_unavailable_falls_back_to_notes_lookup() -> None:
    store = MockDomainStore()
    service = _wire(store, classifier=_UnavailableClassifier())

    result = service.chat(_chat_msg("book"))

    assert result.requested_route is None
    assert result.effective_route is ChatRoute.NOTES_LOOKUP
    decision = _decision(store, result.decision_id)
    assert decision.requested_route is None
    assert decision.classifier_raw_output == ""
    assert decision.classifier_latency_ms == 0


def test_unusable_classifier_output_preserves_raw_output() -> None:
    store = MockDomainStore()
    service = _wire(store, classifier=_BadOutputClassifier())

    result = service.chat(_chat_msg("book"))

    assert result.requested_route is None
    assert result.effective_route is ChatRoute.NOTES_LOOKUP
    decision = _decision(store, result.decision_id)
    assert decision.classifier_raw_output == '{"route": "web_only"}'


@pytest.mark.parametrize("route", [ChatRoute.NOTES_PLUS_MODEL, ChatRoute.NOTES_PLUS_KNOWLEDGE])
def test_not_yet_dispatchable_routes_fall_back_with_requested_recorded(
    route: ChatRoute,
) -> None:
    store = MockDomainStore()
    service = _wire(store, classifier=MockRouteClassifier(default_route=route))

    result = service.chat(_chat_msg("what games suit him now"))

    assert result.requested_route is route
    assert result.effective_route is ChatRoute.NOTES_LOOKUP
    decision = _decision(store, result.decision_id)
    assert decision.requested_route is route
    assert decision.effective_route is ChatRoute.NOTES_LOOKUP


def test_empty_question_skips_the_classifier_and_falls_back() -> None:
    store = MockDomainStore()
    classifier = _CountingClassifier()
    service = _wire(store, classifier=classifier)

    result = service.chat(_chat_msg("   "))

    assert classifier.calls == 0
    assert result.requested_route is None
    assert result.effective_route is ChatRoute.NOTES_LOOKUP
    # The delegated empty-query contour persists its Query row (R-5).
    assert result.answer.fallback is FallbackMode.NO_EVIDENCE
    decision = _decision(store, result.decision_id)
    assert decision.query_id is not None
    assert decision.question_text == ""


def test_unavailable_search_seam_yields_no_evidence_and_unlinked_decision(
    tmp_path: Path,
) -> None:
    """SQLite raises ``NotImplementedError`` from the search seam (D-022 /
    D-025); the routed service mirrors the dispatcher ASK handling and the
    decision row carries ``query_id=None``."""
    store = SqliteDomainStore(str(tmp_path / "diary.db"))
    service = _wire(store)

    result = service.chat(_chat_msg("book"))

    assert result.effective_route is ChatRoute.NOTES_LOOKUP
    assert result.answer.fallback is FallbackMode.NO_EVIDENCE
    assert result.answer.context is None
    decision = store.get_chat_route_decision(result.decision_id, community_id="42")
    assert decision is not None
    assert decision.query_id is None


# ---------------------------------------------------------------------------
# Scoping (R-3 / R-8, H-3)
# ---------------------------------------------------------------------------


def test_community_id_is_required() -> None:
    store = MockDomainStore()
    service = _wire(store)
    message = InboundMessage(
        external_message_id="300",
        external_chat_id="42",
        external_user_id="7",
        community_id="",
        text="/chat book",
        route=RouteKind.CHAT,
        received_at=datetime.now(tz=UTC),
        route_source="command",
        payload="book",
    )
    with pytest.raises(ValueError, match="community_id"):
        service.chat(message)


def test_notes_lookup_never_crosses_communities() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nTried a new book", chat="A", msg_id="100")
    _ingest(store, "2026-05-09\nSecret book of B", chat="B", msg_id="101")
    service = _wire(store)

    result = service.chat(_chat_msg("book", chat="A"))

    texts = {e.chunk_text for e in result.answer.evidence}
    assert "Secret book of B" not in texts


def test_subject_scope_passthrough_restricts_and_is_recorded() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nTried a new book", msg_id="100", subject_id="kid-1")
    _ingest(store, "2026-05-09\nAnother book chapter", msg_id="101")
    service = _wire(store)

    result = service.chat(_chat_msg("book"), subject_scope="kid-1")

    texts = {e.chunk_text for e in result.answer.evidence}
    assert "Tried a new book" in texts
    # Strict match (H-3, D-107): the community-wide chunk is excluded.
    assert "Another book chapter" not in texts
    assert result.answer.context is not None
    query = store.get_query(result.answer.context.query_id, community_id="42")
    assert query is not None
    assert query.subject_scope == "kid-1"


# ---------------------------------------------------------------------------
# Decision rows are per-call
# ---------------------------------------------------------------------------


def test_every_call_writes_exactly_one_decision_row() -> None:
    store = MockDomainStore()
    service = _wire(store)
    service.chat(_chat_msg("book"))
    service.chat(_chat_msg("what is model_only awareness"))
    service.chat(_chat_msg(""))
    assert store.len_chat_route_decisions() == 3
