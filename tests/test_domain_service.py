"""Diary service tests against the in-memory mock store."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from memory_rag.adapters.embeddings import MockEmbeddingClient
from memory_rag.core.domain import EventChunk, FallbackMode, IndexingDeadLetter
from memory_rag.core.embeddings import EmbeddingStatus
from memory_rag.core.routing import InboundMessage, RouteKind
from memory_rag.services import DomainService
from memory_rag.storage.mock import MockDomainStore


def _note_message(
    payload: str,
    *,
    chat: str = "42",
    user: str = "7",
    message_id: str = "100",
    edit_seq: int = 0,
    subject_id: str | None = None,
) -> InboundMessage:
    return InboundMessage(
        external_message_id=message_id,
        external_chat_id=chat,
        external_user_id=user,
        community_id=chat,
        text=f"/note {payload}",
        route=RouteKind.NOTE,
        received_at=datetime.now(tz=UTC),
        route_source="command",
        payload=payload,
        edit_seq=edit_seq,
        subject_id=subject_id,
    )


def test_ingest_persists_source_note_and_chunks() -> None:
    store = MockDomainStore()
    service = DomainService(store)

    result = service.ingest(_note_message("2026-05-09\nMorning routine\nTried a new book"))

    assert result.fallback is FallbackMode.NONE
    assert result.note_date == date(2026, 5, 9)
    assert result.events_count == 1
    assert result.replayed is False
    assert store.len_sources() == 1
    assert store.len_notes() == 1
    assert store.len_chunks() == 1


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


def test_subject_id_defaults_to_none_through_ingest() -> None:
    # H-2 behavior-preserving guard: under the default single-subject mapping
    # the adapter supplies subject_id=None, so the persisted Note and every
    # EventChunk carry subject_id=None (community-wide; D-097), byte-identical
    # to pre-H-2 data.
    store = MockDomainStore()
    service = DomainService(store)

    service.ingest(_note_message("2026-05-09\nMorning routine"))

    assert {n.subject_id for n in store._notes.values()} == {None}
    assert {c.subject_id for c in _all_chunks(store)} == {None}


def test_subject_id_threads_from_inbound_to_note_and_chunks() -> None:
    # H-2 seam guard: a non-None subject_id assigned by a (future) non-default
    # adapter mapping crosses on InboundMessage and is carried onto the
    # persisted Note and EventChunk without further plumbing.
    store = MockDomainStore()
    service = DomainService(store)

    service.ingest(_note_message("2026-05-09\nMorning routine", subject_id="subj-1"))

    assert {n.subject_id for n in store._notes.values()} == {"subj-1"}
    assert {c.subject_id for c in _all_chunks(store)} == {"subj-1"}


def test_multiline_note_is_a_single_chunk() -> None:
    # I-5 / D-106 positive guard: a newline-containing /note yields exactly
    # one EventChunk (event_index=0) holding the whole body verbatim — the
    # interior newlines are content, not event separators.
    store = MockDomainStore()
    service = DomainService(store)

    result = service.ingest(_note_message("2026-05-09\nFirst\nSecond\nThird"))

    chunks = _all_chunks(store)
    assert len(chunks) == 1
    assert result.events_count == 1
    assert chunks[0].event_index == 0
    assert chunks[0].chunk_text == "First\nSecond\nThird"
    # note_text and the single chunk agree (the join site is reconciled).
    assert next(iter(store._notes.values())).note_text == "First\nSecond\nThird"


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
    assert store.len_chunks() == 1


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
    # One chunk per note (I-5 / D-106): the "A\nB" and "A\nB\nC" bodies are
    # two distinct single chunks.
    assert store.len_chunks() == 2


def _all_chunks(store: MockDomainStore) -> list[EventChunk]:
    return list(store._chunks.values())


class _RaisingEmbeddingClient:
    """Forces the embedding step to fail so failure semantics can be asserted."""

    model_name = "boom"
    dimension = 3072

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("provider down")


class _DeadLetterWriteFailsStore(MockDomainStore):
    """Mock store whose dead-letter write always raises (Slice 6.2)."""

    def save_indexing_dead_letter(self, record: IndexingDeadLetter) -> None:
        raise RuntimeError("dead-letter store down")


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
    assert store.len_embeddings() == 1
    assert {c.embedding_status for c in _all_chunks(store)} == {EmbeddingStatus.READY}
    assert store.count_embedding_records_for_source(result.source_message_id) == 1
    # The success path writes no dead-letter row (Slice 6.2).
    assert store.len_indexing_dead_letters() == 0


def test_ingest_embedding_failure_marks_chunks_failed_and_keeps_lineage() -> None:
    store = MockDomainStore()
    service = DomainService(store, embedding_client=_RaisingEmbeddingClient())

    result = service.ingest(_note_message("2026-05-09\nA\nB"))

    assert result.fallback is FallbackMode.NONE  # raw + chunks survived (I-2, I-3)
    assert result.events_count == 1
    assert store.len_embeddings() == 0
    assert {c.embedding_status for c in _all_chunks(store)} == {EmbeddingStatus.FAILED}
    assert store.count_embedding_records_for_source(result.source_message_id) == 0


def test_ingest_embedding_failure_records_one_dead_letter() -> None:
    store = MockDomainStore()
    service = DomainService(store, embedding_client=_RaisingEmbeddingClient())

    result = service.ingest(_note_message("2026-05-09\nA\nB"))

    dead_letters = store.list_indexing_dead_letters("42")  # community_id == chat id
    assert len(dead_letters) == 1
    record = dead_letters[0]
    assert record.source_message_id == result.source_message_id
    assert record.community_id == "42"
    assert set(record.chunk_ids) == {c.chunk_id for c in _all_chunks(store)}
    assert record.model_name == "boom"
    assert record.error_class == "RuntimeError"


def test_ingest_dead_letter_write_failure_is_swallowed_and_chunks_stay_failed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing dead-letter write must not undo the A-35 failure marking."""
    store = _DeadLetterWriteFailsStore()
    service = DomainService(store, embedding_client=_RaisingEmbeddingClient())

    with caplog.at_level("WARNING"):
        result = service.ingest(_note_message("2026-05-09\nA\nB"))

    # The dead-letter write failure is swallowed — ingest never raises.
    assert result.fallback is FallbackMode.NONE
    assert result.events_count == 1
    # embedding_status='failed' stays authoritative despite the write failure.
    assert {c.embedding_status for c in _all_chunks(store)} == {EmbeddingStatus.FAILED}
    assert store.len_indexing_dead_letters() == 0
    assert "dead_letter.write_failed" in caplog.text


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
    assert store.len_embeddings() == 1


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
        community_id=chat,
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
