"""Diary service tests against the in-memory mock store."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from diary_rag.adapters.embeddings import MockEmbeddingClient
from diary_rag.core.domain import EventChunk, FallbackMode
from diary_rag.core.embeddings import EmbeddingStatus
from diary_rag.core.routing import InboundMessage, RouteKind
from diary_rag.services import DomainService
from diary_rag.storage.mock import MockDomainStore


def _note_message(
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
        text=f"/note {payload}",
        route=RouteKind.NOTE,
        received_at=datetime.now(tz=UTC),
        route_source="command",
        payload=payload,
        edit_seq=edit_seq,
    )


def test_ingest_persists_source_note_and_chunks() -> None:
    store = MockDomainStore()
    service = DomainService(store)

    result = service.ingest(_note_message("2026-05-09\nMorning routine\nTried a new book"))

    assert result.fallback is FallbackMode.NONE
    assert result.note_date == date(2026, 5, 9)
    assert result.events_count == 2
    assert result.replayed is False
    assert store.len_sources() == 1
    assert store.len_notes() == 1
    assert store.len_chunks() == 2


def test_ingest_records_source_even_when_parser_rejects() -> None:
    store = MockDomainStore()
    service = DomainService(store)

    result = service.ingest(_note_message("not-a-date\nstray line"))

    assert result.fallback is FallbackMode.INVALID_INPUT
    assert result.invalid_first_line == "not-a-date"
    assert store.len_sources() == 1
    assert store.len_notes() == 0
    assert store.len_chunks() == 0


def test_ingest_preserves_authorship_on_every_chunk() -> None:
    store = MockDomainStore()
    service = DomainService(store)

    service.ingest(_note_message("2026-05-09\nA\nB\nC", chat="42", user="alice"))

    assert {c.author_user_id for c in _all_chunks(store)} == {"alice"}
    assert {c.community_id for c in _all_chunks(store)} == {"42"}


def test_ingest_records_route_on_source_message() -> None:
    store = MockDomainStore()
    service = DomainService(store)

    service.ingest(_note_message("2026-05-09\nA"))

    sources = list(store._sources.values())
    assert len(sources) == 1
    assert sources[0].detected_route is RouteKind.NOTE


def test_chunks_carry_lineage_back_to_source_and_note() -> None:
    store = MockDomainStore()
    service = DomainService(store)

    result = service.ingest(_note_message("2026-05-09\nA\nB"))

    chunks = _all_chunks(store)
    assert all(c.source_message_id == result.source_message_id for c in chunks)
    note_ids = {c.note_id for c in chunks}
    assert len(note_ids) == 1
    assert next(iter(note_ids)) in store._notes


def test_ingest_assigns_event_index_in_order() -> None:
    store = MockDomainStore()
    service = DomainService(store)

    service.ingest(_note_message("2026-05-09\nFirst\nSecond\nThird"))

    chunks_sorted = sorted(_all_chunks(store), key=lambda c: c.event_index)
    assert [c.event_index for c in chunks_sorted] == [0, 1, 2]
    assert [c.chunk_text for c in chunks_sorted] == ["First", "Second", "Third"]


@pytest.mark.parametrize("payload", ["", "   ", "\n\n"])
def test_empty_payload_is_invalid_input(payload: str) -> None:
    store = MockDomainStore()
    service = DomainService(store)

    result = service.ingest(_note_message(payload))

    assert result.fallback is FallbackMode.INVALID_INPUT
    assert store.len_notes() == 0


def test_ingest_replay_short_circuits_and_does_not_duplicate() -> None:
    store = MockDomainStore()
    service = DomainService(store)
    msg = _note_message("2026-05-09\nMorning routine\nTried a new book", message_id="m1")

    first = service.ingest(msg)
    second = service.ingest(msg)

    assert first.replayed is False
    assert second.replayed is True
    assert second.source_message_id == first.source_message_id
    assert second.note_date == first.note_date
    assert second.events_count == first.events_count
    assert second.fallback is FallbackMode.NONE
    assert store.len_sources() == 1
    assert store.len_notes() == 1
    assert store.len_chunks() == 2


def test_ingest_replay_preserves_invalid_input_outcome() -> None:
    store = MockDomainStore()
    service = DomainService(store)
    msg = _note_message("not-a-date\nstray line", message_id="m1")

    first = service.ingest(msg)
    second = service.ingest(msg)

    assert first.fallback is FallbackMode.INVALID_INPUT
    assert second.fallback is FallbackMode.INVALID_INPUT
    assert second.replayed is True
    assert second.invalid_first_line == first.invalid_first_line
    assert store.len_sources() == 1
    assert store.len_notes() == 0
    assert store.len_chunks() == 0


def test_ingest_distinct_edit_seq_creates_separate_state() -> None:
    store = MockDomainStore()
    service = DomainService(store)
    original = _note_message("2026-05-09\nA\nB", message_id="m1", edit_seq=0)
    edited = _note_message("2026-05-09\nA\nB\nC", message_id="m1", edit_seq=1715300100)

    res_original = service.ingest(original)
    res_edited = service.ingest(edited)

    assert res_original.replayed is False
    assert res_edited.replayed is False
    assert res_original.source_message_id != res_edited.source_message_id
    assert store.len_sources() == 2
    assert store.len_notes() == 2
    assert store.len_chunks() == 5


def _all_chunks(store: MockDomainStore) -> list[EventChunk]:
    return list(store._chunks.values())


class _RaisingEmbeddingClient:
    """Forces the embedding step to fail so failure semantics can be asserted."""

    model_name = "boom"
    dimension = 3072

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("provider down")


def test_ingest_without_embedding_client_leaves_chunks_pending() -> None:
    store = MockDomainStore()
    service = DomainService(store)

    service.ingest(_note_message("2026-05-09\nA\nB"))

    assert {c.embedding_status for c in _all_chunks(store)} == {EmbeddingStatus.PENDING}
    assert store.len_embeddings() == 0


def test_ingest_with_embedding_client_persists_embeddings_and_flips_status() -> None:
    store = MockDomainStore()
    client = MockEmbeddingClient(dimension=64)
    service = DomainService(store, embedding_client=client)

    result = service.ingest(_note_message("2026-05-09\nA\nB"))

    assert result.fallback is FallbackMode.NONE
    assert store.len_embeddings() == 2
    assert {c.embedding_status for c in _all_chunks(store)} == {EmbeddingStatus.READY}
    assert store.count_embedding_records_for_source(result.source_message_id) == 2


def test_ingest_embedding_failure_marks_chunks_failed_and_keeps_lineage() -> None:
    store = MockDomainStore()
    service = DomainService(store, embedding_client=_RaisingEmbeddingClient())

    result = service.ingest(_note_message("2026-05-09\nA\nB"))

    assert result.fallback is FallbackMode.NONE  # raw + chunks survived (I-2, I-3)
    assert result.events_count == 2
    assert store.len_embeddings() == 0
    assert {c.embedding_status for c in _all_chunks(store)} == {EmbeddingStatus.FAILED}
    assert store.count_embedding_records_for_source(result.source_message_id) == 0


def test_ingest_replay_does_not_call_embedding_client() -> None:
    store = MockDomainStore()

    class _CountingClient:
        model_name = "mock"
        dimension = 64
        calls = 0

        def embed(self, texts: list[str]) -> list[list[float]]:
            type(self).calls += 1
            return [[0.0] * 64 for _ in texts]

    client = _CountingClient()
    service = DomainService(store, embedding_client=client)
    msg = _note_message("2026-05-09\nA\nB", message_id="m1")

    service.ingest(msg)
    service.ingest(msg)

    assert _CountingClient.calls == 1
    assert store.len_embeddings() == 2


def test_ingest_with_invalid_payload_does_not_call_embedding_client() -> None:
    store = MockDomainStore()

    class _CountingClient:
        model_name = "mock"
        dimension = 64
        calls = 0

        def embed(self, texts: list[str]) -> list[list[float]]:
            type(self).calls += 1
            return [[0.0] * 64 for _ in texts]

    client = _CountingClient()
    service = DomainService(store, embedding_client=client)

    service.ingest(_note_message("not-a-date\nstray line"))

    assert _CountingClient.calls == 0
    assert store.len_embeddings() == 0


def _draft_message(
    payload: str,
    *,
    chat: str = "42",
    user: str = "7",
    message_id: str = "300",
    edit_seq: int = 0,
) -> InboundMessage:
    """Construct a no-command-default DRAFT inbound (D-030: only path to a draft)."""
    return InboundMessage(
        external_message_id=message_id,
        external_chat_id=chat,
        external_user_id=user,
        text=payload,
        route=RouteKind.DRAFT,
        received_at=datetime.now(tz=UTC),
        route_source="heuristic",
        payload=payload,
        edit_seq=edit_seq,
    )


def test_ingest_draft_persists_raw_only() -> None:
    store = MockDomainStore()
    service = DomainService(store)

    result = service.ingest(_draft_message("just thinking out loud"))

    assert result.fallback is FallbackMode.NONE
    assert result.note_date is None
    assert result.events_count == 0
    assert result.replayed is False
    assert store.len_sources() == 1
    assert store.len_notes() == 0
    assert store.len_chunks() == 0


def test_ingest_draft_records_draft_route_on_source_message() -> None:
    store = MockDomainStore()
    service = DomainService(store)

    service.ingest(_draft_message("just thinking out loud"))

    sources = list(store._sources.values())
    assert len(sources) == 1
    assert sources[0].detected_route is RouteKind.DRAFT
    assert sources[0].raw_text == "just thinking out loud"


def test_ingest_draft_does_not_call_embedding_client() -> None:
    store = MockDomainStore()

    class _CountingClient:
        model_name = "mock"
        dimension = 64
        calls = 0

        def embed(self, texts: list[str]) -> list[list[float]]:
            type(self).calls += 1
            return [[0.0] * 64 for _ in texts]

    client = _CountingClient()
    service = DomainService(store, embedding_client=client)

    service.ingest(_draft_message("ambiguous text"))

    assert _CountingClient.calls == 0
    assert store.len_embeddings() == 0


def test_ingest_draft_replay_short_circuits_without_duplicating() -> None:
    store = MockDomainStore()
    service = DomainService(store)
    msg = _draft_message("recipe yesterday", message_id="d1")

    first = service.ingest(msg)
    second = service.ingest(msg)

    assert first.replayed is False
    assert second.replayed is True
    assert second.fallback is FallbackMode.NONE
    assert second.source_message_id == first.source_message_id
    assert second.events_count == 0
    assert store.len_sources() == 1
    assert store.len_notes() == 0
    assert store.len_chunks() == 0


def test_ingest_draft_then_distinct_note_message_keeps_both_states() -> None:
    store = MockDomainStore()
    service = DomainService(store)

    draft = service.ingest(_draft_message("idea, not yet committed", message_id="d1"))
    note = service.ingest(_note_message("2026-05-09\nMorning routine", message_id="n1"))

    assert draft.source_message_id != note.source_message_id
    assert store.len_sources() == 2
    assert store.len_notes() == 1
    assert store.len_chunks() == 1


def test_list_recent_drafts_returns_drafts_only_most_recent_first() -> None:
    store = MockDomainStore()
    service = DomainService(store)

    service.ingest(_draft_message("first draft", message_id="d1"))
    service.ingest(_note_message("2026-05-09\nA note", message_id="n1"))
    service.ingest(_draft_message("second draft", message_id="d2"))

    drafts = service.list_recent_drafts("42", limit=5)
    assert [d.raw_text for d in drafts] == ["second draft", "first draft"]


def test_list_recent_drafts_is_family_scoped() -> None:
    store = MockDomainStore()
    service = DomainService(store)

    service.ingest(_draft_message("fam-A draft", chat="fam-A", message_id="d1"))
    service.ingest(_draft_message("fam-B draft", chat="fam-B", message_id="d2"))

    drafts = service.list_recent_drafts("fam-A", limit=5)
    assert [d.raw_text for d in drafts] == ["fam-A draft"]


def test_list_recent_drafts_respects_limit() -> None:
    store = MockDomainStore()
    service = DomainService(store)

    for i in range(5):
        service.ingest(_draft_message(f"draft-{i}", message_id=f"d{i}"))

    drafts = service.list_recent_drafts("42", limit=2)
    assert len(drafts) == 2


def test_list_recent_drafts_empty_when_no_drafts() -> None:
    store = MockDomainStore()
    service = DomainService(store)

    service.ingest(_note_message("2026-05-09\nA note", message_id="n1"))

    drafts = service.list_recent_drafts("42", limit=5)
    assert drafts == []


def test_list_recent_drafts_rejects_zero_limit() -> None:
    store = MockDomainStore()
    service = DomainService(store)
    with pytest.raises(ValueError):
        service.list_recent_drafts("42", limit=0)
