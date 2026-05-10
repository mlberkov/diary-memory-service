"""Diary service tests against the in-memory mock store."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from diary_rag.core.diary import EventChunk, FallbackMode
from diary_rag.core.routing import InboundMessage, RouteKind
from diary_rag.services import DiaryService
from diary_rag.storage.mock import MockDiaryStore


def _entry_message(
    payload: str,
    *,
    chat: str = "42",
    user: str = "7",
    message_id: str = "100",
    edit_seq: int = 0,
) -> InboundMessage:
    return InboundMessage(
        external_message_id=message_id,
        external_chat_id=chat,
        external_user_id=user,
        text=f"/entry {payload}",
        route=RouteKind.ENTRY,
        received_at=datetime.now(tz=UTC),
        route_source="command",
        payload=payload,
        edit_seq=edit_seq,
    )


def test_ingest_persists_source_entry_and_chunks() -> None:
    store = MockDiaryStore()
    service = DiaryService(store)

    result = service.ingest(_entry_message("2026-05-09\nMorning routine\nTried a new book"))

    assert result.fallback is FallbackMode.NONE
    assert result.entry_date == date(2026, 5, 9)
    assert result.events_count == 2
    assert result.replayed is False
    assert store.len_sources() == 1
    assert store.len_entries() == 1
    assert store.len_chunks() == 2


def test_ingest_records_source_even_when_parser_rejects() -> None:
    store = MockDiaryStore()
    service = DiaryService(store)

    result = service.ingest(_entry_message("not-a-date\nstray line"))

    assert result.fallback is FallbackMode.INVALID_INPUT
    assert result.invalid_first_line == "not-a-date"
    assert store.len_sources() == 1
    assert store.len_entries() == 0
    assert store.len_chunks() == 0


def test_ingest_preserves_authorship_on_every_chunk() -> None:
    store = MockDiaryStore()
    service = DiaryService(store)

    service.ingest(_entry_message("2026-05-09\nA\nB\nC", chat="42", user="alice"))

    assert {c.author_user_id for c in _all_chunks(store)} == {"alice"}
    assert {c.family_id for c in _all_chunks(store)} == {"42"}


def test_ingest_records_route_on_source_message() -> None:
    store = MockDiaryStore()
    service = DiaryService(store)

    service.ingest(_entry_message("2026-05-09\nA"))

    sources = list(store._sources.values())
    assert len(sources) == 1
    assert sources[0].detected_route is RouteKind.ENTRY


def test_chunks_carry_lineage_back_to_source_and_entry() -> None:
    store = MockDiaryStore()
    service = DiaryService(store)

    result = service.ingest(_entry_message("2026-05-09\nA\nB"))

    chunks = _all_chunks(store)
    assert all(c.source_message_id == result.source_message_id for c in chunks)
    diary_entry_ids = {c.diary_entry_id for c in chunks}
    assert len(diary_entry_ids) == 1
    assert next(iter(diary_entry_ids)) in store._entries


def test_ingest_assigns_event_index_in_order() -> None:
    store = MockDiaryStore()
    service = DiaryService(store)

    service.ingest(_entry_message("2026-05-09\nFirst\nSecond\nThird"))

    chunks_sorted = sorted(_all_chunks(store), key=lambda c: c.event_index)
    assert [c.event_index for c in chunks_sorted] == [0, 1, 2]
    assert [c.chunk_text for c in chunks_sorted] == ["First", "Second", "Third"]


@pytest.mark.parametrize("payload", ["", "   ", "\n\n"])
def test_empty_payload_is_invalid_input(payload: str) -> None:
    store = MockDiaryStore()
    service = DiaryService(store)

    result = service.ingest(_entry_message(payload))

    assert result.fallback is FallbackMode.INVALID_INPUT
    assert store.len_entries() == 0


def test_ingest_replay_short_circuits_and_does_not_duplicate() -> None:
    store = MockDiaryStore()
    service = DiaryService(store)
    msg = _entry_message("2026-05-09\nMorning routine\nTried a new book", message_id="m1")

    first = service.ingest(msg)
    second = service.ingest(msg)

    assert first.replayed is False
    assert second.replayed is True
    assert second.source_message_id == first.source_message_id
    assert second.entry_date == first.entry_date
    assert second.events_count == first.events_count
    assert second.fallback is FallbackMode.NONE
    assert store.len_sources() == 1
    assert store.len_entries() == 1
    assert store.len_chunks() == 2


def test_ingest_replay_preserves_invalid_input_outcome() -> None:
    store = MockDiaryStore()
    service = DiaryService(store)
    msg = _entry_message("not-a-date\nstray line", message_id="m1")

    first = service.ingest(msg)
    second = service.ingest(msg)

    assert first.fallback is FallbackMode.INVALID_INPUT
    assert second.fallback is FallbackMode.INVALID_INPUT
    assert second.replayed is True
    assert second.invalid_first_line == first.invalid_first_line
    assert store.len_sources() == 1
    assert store.len_entries() == 0
    assert store.len_chunks() == 0


def test_ingest_distinct_edit_seq_creates_separate_state() -> None:
    store = MockDiaryStore()
    service = DiaryService(store)
    original = _entry_message("2026-05-09\nA\nB", message_id="m1", edit_seq=0)
    edited = _entry_message("2026-05-09\nA\nB\nC", message_id="m1", edit_seq=1715300100)

    res_original = service.ingest(original)
    res_edited = service.ingest(edited)

    assert res_original.replayed is False
    assert res_edited.replayed is False
    assert res_original.source_message_id != res_edited.source_message_id
    assert store.len_sources() == 2
    assert store.len_entries() == 2
    assert store.len_chunks() == 5


def _all_chunks(store: MockDiaryStore) -> list[EventChunk]:
    return list(store._chunks.values())
