"""Query service tests against the in-memory mock store."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

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
        text=f"/entry {payload}",
        route=RouteKind.ENTRY,
        received_at=datetime.now(tz=UTC),
        route_source="command",
        payload=payload,
    )


def test_empty_store_returns_no_evidence() -> None:
    store = MockDiaryStore()
    query = QueryService(store)

    result = query.answer(_ask("anything"))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert result.evidence == []
    assert result.context_chunk_ids == []


def test_substring_match_returns_evidence_in_insertion_order() -> None:
    store = MockDiaryStore()
    DiaryService(store).ingest(
        _entry("2026-05-09\nMorning routine\nTried a new book\nAnother book chapter")
    )
    query = QueryService(store)

    result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.NONE
    assert [e.chunk_text for e in result.evidence] == [
        "Tried a new book",
        "Another book chapter",
    ]


def test_match_is_case_insensitive() -> None:
    store = MockDiaryStore()
    DiaryService(store).ingest(_entry("2026-05-09\nTried a new BOOK"))
    query = QueryService(store)

    result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.NONE
    assert len(result.evidence) == 1


def test_no_match_returns_no_evidence() -> None:
    store = MockDiaryStore()
    DiaryService(store).ingest(_entry("2026-05-09\nMorning routine"))
    query = QueryService(store)

    result = query.answer(_ask("snowstorm"))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert result.evidence == []


def test_cross_chat_isolation() -> None:
    store = MockDiaryStore()
    diary = DiaryService(store)
    diary.ingest(_entry("2026-05-09\nFamily A book", chat="42"))
    diary.ingest(_entry("2026-05-09\nFamily B novel", chat="99"))

    result_a = QueryService(store).answer(_ask("book", chat="42"))
    result_b = QueryService(store).answer(_ask("book", chat="99"))

    assert [e.chunk_text for e in result_a.evidence] == ["Family A book"]
    assert result_b.evidence == []


def test_top_k_caps_evidence_count() -> None:
    store = MockDiaryStore()
    DiaryService(store).ingest(_entry("2026-05-09\nbook one\nbook two\nbook three\nbook four"))
    query = QueryService(store, top_k=2)

    result = query.answer(_ask("book"))

    assert len(result.evidence) == 2


def test_missing_family_id_raises() -> None:
    store = MockDiaryStore()
    query = QueryService(store)

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
    DiaryService(store).ingest(_entry("2026-05-09\nMorning routine"))
    query = QueryService(store)

    result = query.answer(_ask("   "))

    assert result.fallback is FallbackMode.NO_EVIDENCE
