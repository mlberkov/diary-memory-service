"""QueryService tests for the baseline hybrid path (D-025).

Mock backend exercises both retrieval legs: sparse matches via token
overlap, dense matches via deterministic cosine over the mock embeddings
(only identical text qualifies — see ``MockDiaryStore`` for why). RRF
fuses the two ranked lists in the service layer.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from diary_rag.adapters.answers import MockChatClient
from diary_rag.adapters.embeddings import MockEmbeddingClient
from diary_rag.core.diary import FallbackMode, RetrievalLeg
from diary_rag.core.routing import InboundMessage, RouteKind
from diary_rag.services import DiaryService, QueryService
from diary_rag.storage.mock import MockDiaryStore


def _ask(query: str, *, chat: str = "42", user: str = "7") -> InboundMessage:
    return InboundMessage(
        external_message_id="200",
        external_chat_id=chat,
        external_user_id=user,
        text=f"/ask {query}",
        route=RouteKind.ASK,
        received_at=datetime.now(tz=UTC),
        route_source="command",
        payload=query,
    )


def _entry(payload: str, *, chat: str = "42", user: str = "7") -> InboundMessage:
    return InboundMessage(
        external_message_id="100",
        external_chat_id=chat,
        external_user_id=user,
        text=f"/note {payload}",
        route=RouteKind.ENTRY,
        received_at=datetime.now(tz=UTC),
        route_source="command",
        payload=payload,
    )


def _wire(store: MockDiaryStore, *, top_k: int = 5) -> QueryService:
    return QueryService(store, store, MockEmbeddingClient(), MockChatClient(), top_k=top_k)


def _ingest(store: MockDiaryStore, payload: str, *, chat: str = "42") -> None:
    DiaryService(store, embedding_client=MockEmbeddingClient()).ingest(_entry(payload, chat=chat))


def test_empty_store_returns_no_evidence() -> None:
    store = MockDiaryStore()
    query = _wire(store)

    result = query.answer(_ask("anything"))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert result.evidence == []
    assert result.context_chunk_ids == []


def test_sparse_leg_recovers_keyword_match() -> None:
    store = MockDiaryStore()
    _ingest(store, "2026-05-09\nMorning routine\nTried a new book\nAnother book chapter")
    query = _wire(store)

    result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.NONE
    matched = {e.chunk_text for e in result.evidence}
    assert "Tried a new book" in matched
    assert "Another book chapter" in matched
    assert "Morning routine" not in matched


def test_dense_leg_returns_identical_text_match() -> None:
    store = MockDiaryStore()
    _ingest(store, "2026-05-09\nWalked the dog")
    query = _wire(store)

    result = query.answer(_ask("Walked the dog"))

    assert result.fallback is FallbackMode.NONE
    assert [e.chunk_text for e in result.evidence] == ["Walked the dog"]


def test_unrelated_query_returns_no_evidence() -> None:
    store = MockDiaryStore()
    _ingest(store, "2026-05-09\nMorning routine")
    query = _wire(store)

    result = query.answer(_ask("snowstorm"))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert result.evidence == []


def test_cross_chat_isolation() -> None:
    store = MockDiaryStore()
    _ingest(store, "2026-05-09\nFamily A book", chat="42")
    _ingest(store, "2026-05-09\nFamily B novel", chat="99")
    query = _wire(store)

    result_a = query.answer(_ask("book", chat="42"))
    result_b = query.answer(_ask("book", chat="99"))

    assert [e.chunk_text for e in result_a.evidence] == ["Family A book"]
    assert result_b.evidence == []


def test_top_k_caps_evidence_count() -> None:
    store = MockDiaryStore()
    _ingest(store, "2026-05-09\nbook one\nbook two\nbook three\nbook four")
    query = _wire(store, top_k=2)

    result = query.answer(_ask("book"))

    assert len(result.evidence) == 2


def test_missing_family_id_raises() -> None:
    store = MockDiaryStore()
    query = _wire(store)

    with pytest.raises(ValueError, match="external_chat_id"):
        query.answer(
            InboundMessage(
                external_message_id="200",
                external_chat_id="",
                external_user_id="7",
                text="/ask book",
                route=RouteKind.ASK,
                received_at=datetime.now(tz=UTC),
                route_source="command",
                payload="book",
            )
        )
    assert store.len_queries() == 0  # R-3 rejection happens before persistence


def test_blank_query_returns_no_evidence() -> None:
    store = MockDiaryStore()
    _ingest(store, "2026-05-09\nMorning routine")
    query = _wire(store)

    result = query.answer(_ask("   "))

    assert result.fallback is FallbackMode.NO_EVIDENCE


def test_terminal_punctuation_does_not_block_match() -> None:
    """``recipe?`` normalizes to ``recipe`` before sparse tokenization."""
    store = MockDiaryStore()
    _ingest(store, "2026-05-10\nLearned a new recipe")
    query = _wire(store)

    result = query.answer(_ask("recipe?"))

    assert result.fallback is FallbackMode.NONE
    assert [e.chunk_text for e in result.evidence] == ["Learned a new recipe"]


def test_successful_retrieval_persists_query_and_hits() -> None:
    store = MockDiaryStore()
    _ingest(store, "2026-05-09\nMorning routine\nTried a new book")
    query = _wire(store)

    result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.NONE
    assert store.len_queries() == 1
    # Persisted Query mirrors the AnswerResult.
    persisted = next(iter(store._queries.values()))
    assert persisted.family_id == "42"
    assert persisted.query_text == "book"
    assert persisted.fallback is FallbackMode.NONE
    assert persisted.model_name == MockEmbeddingClient().model_name

    hits = store.get_retrieval_hits_for_query(persisted.query_id)
    legs = {h.leg for h in hits}
    assert RetrievalLeg.SPARSE in legs  # sparse matched "book"
    assert RetrievalLeg.MERGED in legs  # merged carries the surviving evidence
    merged_chunk_ids = [h.chunk_id for h in hits if h.leg is RetrievalLeg.MERGED]
    assert merged_chunk_ids == [e.chunk_id for e in result.evidence]
    # All ranks are 1-based and unique per leg.
    for leg in legs:
        leg_ranks = sorted(h.rank for h in hits if h.leg is leg)
        assert leg_ranks == list(range(1, len(leg_ranks) + 1))


def test_no_evidence_persists_query_with_zero_hits() -> None:
    store = MockDiaryStore()
    _ingest(store, "2026-05-09\nMorning routine")
    query = _wire(store)

    result = query.answer(_ask("snowstorm"))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert store.len_queries() == 1
    persisted = next(iter(store._queries.values()))
    assert persisted.fallback is FallbackMode.NO_EVIDENCE
    assert persisted.query_text == "snowstorm"
    assert store.get_retrieval_hits_for_query(persisted.query_id) == []
    assert store.len_retrieval_hits() == 0


def test_empty_query_persists_query_with_zero_hits() -> None:
    store = MockDiaryStore()
    _ingest(store, "2026-05-09\nMorning routine")
    query = _wire(store)

    result = query.answer(_ask("   "))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert store.len_queries() == 1
    persisted = next(iter(store._queries.values()))
    assert persisted.query_text == ""
    assert persisted.fallback is FallbackMode.NO_EVIDENCE
    assert store.len_retrieval_hits() == 0


def test_successful_retrieval_attaches_answer_context() -> None:
    """Slice 4.1: every successful retrieval carries an assembled context."""
    store = MockDiaryStore()
    _ingest(store, "2026-05-09\nMorning routine\nTried a new book")
    query = _wire(store)

    result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.NONE
    assert result.context is not None
    persisted = next(iter(store._queries.values()))
    assert result.context.query_id == persisted.query_id
    assert result.context.query_text == "book"
    assert result.context.model_name == MockEmbeddingClient().model_name
    assert result.context.created_at == persisted.created_at
    # Context chunk order matches the evidence (RRF rank).
    assert [c.chunk_id for c in result.context.ordered_chunks] == [
        e.chunk_id for e in result.evidence
    ]


def test_no_evidence_attaches_empty_answer_context() -> None:
    store = MockDiaryStore()
    _ingest(store, "2026-05-09\nMorning routine")
    query = _wire(store)

    result = query.answer(_ask("snowstorm"))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert result.context is not None
    assert result.context.query_text == "snowstorm"
    assert result.context.ordered_chunks == ()


def test_empty_query_attaches_empty_answer_context() -> None:
    store = MockDiaryStore()
    query = _wire(store)

    result = query.answer(_ask("   "))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert result.context is not None
    assert result.context.query_text == ""
    assert result.context.ordered_chunks == ()


def test_invalid_constructor_arguments() -> None:
    store = MockDiaryStore()
    client = MockEmbeddingClient()
    chat = MockChatClient()

    with pytest.raises(ValueError, match="top_k"):
        QueryService(store, store, client, chat, top_k=0)
    with pytest.raises(ValueError, match="candidate_k"):
        QueryService(store, store, client, chat, top_k=5, candidate_k=2)


def test_successful_answer_persists_answer_trace_with_chat_output() -> None:
    """Slice 4.3a: success persists an ``AnswerTrace`` with the LLM output."""
    store = MockDiaryStore()
    _ingest(store, "2026-05-09\nMorning routine\nTried a new book")
    query = _wire(store)

    result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.NONE
    assert store.len_answer_traces() == 1
    persisted_query = next(iter(store._queries.values()))
    trace = store.get_answer_trace_for_query(persisted_query.query_id)
    assert trace is not None
    assert trace.fallback_mode is FallbackMode.NONE
    assert trace.prompt_version == "v1"
    assert trace.model_name == "mock"
    assert trace.latency_ms == 0
    assert trace.token_counts.keys() == {"prompt", "completion"}
    assert tuple(trace.context_chunk_ids) == tuple(
        c.chunk_id
        for c in result.context.ordered_chunks  # type: ignore[union-attr]
    )
    assert trace.answer_text  # non-empty mock answer
    # AnswerResult carries the LLM-produced text alongside the existing evidence.
    assert result.answer_text == trace.answer_text


def test_no_evidence_persists_answer_trace_with_empty_context() -> None:
    """Slice 4.3a: no-evidence persists a trace with no chat call."""
    store = MockDiaryStore()
    _ingest(store, "2026-05-09\nMorning routine")
    query = _wire(store)

    result = query.answer(_ask("snowstorm"))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert result.answer_text is None
    assert store.len_answer_traces() == 1
    persisted_query = next(iter(store._queries.values()))
    trace = store.get_answer_trace_for_query(persisted_query.query_id)
    assert trace is not None
    assert trace.fallback_mode is FallbackMode.NO_EVIDENCE
    assert trace.context_chunk_ids == ()
    assert trace.answer_text == ""
    assert trace.token_counts == {}
    assert trace.latency_ms == 0
    assert trace.model_name == "mock"


def test_empty_query_persists_answer_trace_with_empty_context() -> None:
    """Slice 4.3a: empty-query persists a trace with no chat call."""
    store = MockDiaryStore()
    query = _wire(store)

    result = query.answer(_ask("   "))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert result.answer_text is None
    assert store.len_answer_traces() == 1
    persisted_query = next(iter(store._queries.values()))
    trace = store.get_answer_trace_for_query(persisted_query.query_id)
    assert trace is not None
    assert trace.fallback_mode is FallbackMode.NO_EVIDENCE
    assert trace.context_chunk_ids == ()
    assert trace.answer_text == ""
    assert trace.token_counts == {}
    assert trace.latency_ms == 0
