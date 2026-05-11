"""Diary service tests against the in-memory mock store."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from diary_rag.adapters.embeddings import MockEmbeddingClient
from diary_rag.core.diary import EventChunk, FallbackMode
from diary_rag.core.embeddings import EmbeddingStatus
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


class _RaisingEmbeddingClient:
    """Forces the embedding step to fail so failure semantics can be asserted."""

    model_name = "boom"
    dimension = 3072

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("provider down")


def test_ingest_without_embedding_client_leaves_chunks_pending() -> None:
    store = MockDiaryStore()
    service = DiaryService(store)

    service.ingest(_entry_message("2026-05-09\nA\nB"))

    assert {c.embedding_status for c in _all_chunks(store)} == {EmbeddingStatus.PENDING}
    assert store.len_embeddings() == 0


def test_ingest_with_embedding_client_persists_embeddings_and_flips_status() -> None:
    store = MockDiaryStore()
    client = MockEmbeddingClient(dimension=64)
    service = DiaryService(store, embedding_client=client)

    result = service.ingest(_entry_message("2026-05-09\nA\nB"))

    assert result.fallback is FallbackMode.NONE
    assert store.len_embeddings() == 2
    assert {c.embedding_status for c in _all_chunks(store)} == {EmbeddingStatus.READY}
    assert store.count_embedding_records_for_source(result.source_message_id) == 2


def test_ingest_embedding_failure_marks_chunks_failed_and_keeps_lineage() -> None:
    store = MockDiaryStore()
    service = DiaryService(store, embedding_client=_RaisingEmbeddingClient())

    result = service.ingest(_entry_message("2026-05-09\nA\nB"))

    assert result.fallback is FallbackMode.NONE  # raw + chunks survived (I-2, I-3)
    assert result.events_count == 2
    assert store.len_embeddings() == 0
    assert {c.embedding_status for c in _all_chunks(store)} == {EmbeddingStatus.FAILED}
    assert store.count_embedding_records_for_source(result.source_message_id) == 0


def test_ingest_replay_does_not_call_embedding_client() -> None:
    store = MockDiaryStore()

    class _CountingClient:
        model_name = "mock"
        dimension = 64
        calls = 0

        def embed(self, texts: list[str]) -> list[list[float]]:
            type(self).calls += 1
            return [[0.0] * 64 for _ in texts]

    client = _CountingClient()
    service = DiaryService(store, embedding_client=client)
    msg = _entry_message("2026-05-09\nA\nB", message_id="m1")

    service.ingest(msg)
    service.ingest(msg)

    assert _CountingClient.calls == 1
    assert store.len_embeddings() == 2


def test_ingest_with_invalid_payload_does_not_call_embedding_client() -> None:
    store = MockDiaryStore()

    class _CountingClient:
        model_name = "mock"
        dimension = 64
        calls = 0

        def embed(self, texts: list[str]) -> list[list[float]]:
            type(self).calls += 1
            return [[0.0] * 64 for _ in texts]

    client = _CountingClient()
    service = DiaryService(store, embedding_client=client)

    service.ingest(_entry_message("not-a-date\nstray line"))

    assert _CountingClient.calls == 0
    assert store.len_embeddings() == 0


def _draft_message(
    payload: str,
    *,
    chat: str = "42",
    user: str = "7",
    message_id: str = "300",
    edit_seq: int = 0,
    route_source: str = "command",
) -> InboundMessage:
    return InboundMessage(
        external_message_id=message_id,
        external_chat_id=chat,
        external_user_id=user,
        text=f"/draft {payload}" if route_source == "command" else payload,
        route=RouteKind.DRAFT,
        received_at=datetime.now(tz=UTC),
        route_source=route_source,  # type: ignore[arg-type]
        payload=payload,
        edit_seq=edit_seq,
    )


def test_ingest_draft_persists_raw_only() -> None:
    store = MockDiaryStore()
    service = DiaryService(store)

    result = service.ingest(_draft_message("just thinking out loud"))

    assert result.fallback is FallbackMode.NONE
    assert result.entry_date is None
    assert result.events_count == 0
    assert result.replayed is False
    assert store.len_sources() == 1
    assert store.len_entries() == 0
    assert store.len_chunks() == 0


def test_ingest_draft_records_draft_route_on_source_message() -> None:
    store = MockDiaryStore()
    service = DiaryService(store)

    service.ingest(_draft_message("just thinking out loud"))

    sources = list(store._sources.values())
    assert len(sources) == 1
    assert sources[0].detected_route is RouteKind.DRAFT
    assert sources[0].raw_text == "just thinking out loud"


def test_ingest_draft_does_not_call_embedding_client() -> None:
    store = MockDiaryStore()

    class _CountingClient:
        model_name = "mock"
        dimension = 64
        calls = 0

        def embed(self, texts: list[str]) -> list[list[float]]:
            type(self).calls += 1
            return [[0.0] * 64 for _ in texts]

    client = _CountingClient()
    service = DiaryService(store, embedding_client=client)

    service.ingest(_draft_message("ambiguous text"))

    assert _CountingClient.calls == 0
    assert store.len_embeddings() == 0


def test_ingest_draft_replay_short_circuits_without_duplicating() -> None:
    store = MockDiaryStore()
    service = DiaryService(store)
    msg = _draft_message("recipe yesterday", message_id="d1")

    first = service.ingest(msg)
    second = service.ingest(msg)

    assert first.replayed is False
    assert second.replayed is True
    assert second.fallback is FallbackMode.NONE
    assert second.source_message_id == first.source_message_id
    assert second.events_count == 0
    assert store.len_sources() == 1
    assert store.len_entries() == 0
    assert store.len_chunks() == 0


def test_ingest_draft_then_distinct_entry_message_keeps_both_states() -> None:
    store = MockDiaryStore()
    service = DiaryService(store)

    draft = service.ingest(_draft_message("idea, not yet committed", message_id="d1"))
    note = service.ingest(_entry_message("2026-05-09\nMorning routine", message_id="n1"))

    assert draft.source_message_id != note.source_message_id
    assert store.len_sources() == 2
    assert store.len_entries() == 1
    assert store.len_chunks() == 1
