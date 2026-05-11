"""QueryService tests for the baseline hybrid path (D-025).

Mock backend exercises both retrieval legs: sparse matches via token
overlap, dense matches via deterministic cosine over the mock embeddings
(only identical text qualifies — see ``MockDiaryStore`` for why). RRF
fuses the two ranked lists in the service layer.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from diary_rag.adapters.embeddings import MockEmbeddingClient
from diary_rag.core.diary import FallbackMode
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
    return QueryService(store, MockEmbeddingClient(), top_k=top_k)


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


def test_invalid_constructor_arguments() -> None:
    store = MockDiaryStore()
    client = MockEmbeddingClient()

    with pytest.raises(ValueError, match="top_k"):
        QueryService(store, client, top_k=0)
    with pytest.raises(ValueError, match="candidate_k"):
        QueryService(store, client, top_k=5, candidate_k=2)
