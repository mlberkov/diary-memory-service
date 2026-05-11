"""Integration tests for ``PostgresDiaryStore`` (ingest contract only).

Skipped unless ``DIARY_RAG_PG_TEST_DSN`` is set, so the offline test
flow stays green. Retrieval coverage lives in
``tests/test_search_repository_postgres.py`` (Slice 3.3 / D-025).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest

from diary_rag.core.diary.models import DiaryEntry, EventChunk, SourceMessage
from diary_rag.core.routing import RouteKind

PG_DSN = os.environ.get("DIARY_RAG_PG_TEST_DSN")

pytestmark = pytest.mark.skipif(
    PG_DSN is None,
    reason="DIARY_RAG_PG_TEST_DSN not set; Postgres integration tests skipped.",
)

if PG_DSN is not None:
    import psycopg

    from diary_rag.storage.postgres import PostgresDiaryStore


def _truncate(dsn: str) -> None:
    """Reset the three diary tables. Schema is bootstrapped on store init."""
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE event_chunks, diary_entries, source_messages " "RESTART IDENTITY CASCADE"
        )


@pytest.fixture
def store() -> Iterator[PostgresDiaryStore]:
    assert PG_DSN is not None
    s = PostgresDiaryStore(PG_DSN)
    try:
        _truncate(PG_DSN)
        yield s
    finally:
        s.close()


def _now() -> datetime:
    return datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC)


def _source(
    *,
    sid: str = "s1",
    family_id: str = "fam-A",
    external_message_id: str | None = None,
    edit_seq: int = 0,
) -> SourceMessage:
    return SourceMessage(
        source_message_id=sid,
        family_id=family_id,
        author_user_id="u1",
        external_chat_id=family_id,
        external_user_id="u1",
        external_message_id=external_message_id if external_message_id is not None else sid,
        edit_seq=edit_seq,
        raw_text="2026-05-09\nWalked the dog",
        detected_route=RouteKind.ENTRY,
        created_at=_now(),
    )


def _entry(*, eid: str = "e1", sid: str = "s1", family_id: str = "fam-A") -> DiaryEntry:
    return DiaryEntry(
        diary_entry_id=eid,
        source_message_id=sid,
        family_id=family_id,
        author_user_id="u1",
        entry_date=date(2026, 5, 9),
        entry_text="Walked the dog",
        created_at=_now(),
    )


def _chunk(
    *,
    cid: str = "c1",
    eid: str = "e1",
    sid: str = "s1",
    family_id: str = "fam-A",
    text: str = "Walked the dog",
    idx: int = 0,
) -> EventChunk:
    return EventChunk(
        chunk_id=cid,
        diary_entry_id=eid,
        source_message_id=sid,
        family_id=family_id,
        author_user_id="u1",
        entry_date=date(2026, 5, 9),
        event_index=idx,
        chunk_text=text,
        created_at=_now(),
    )


def test_round_trip_source_message(store: PostgresDiaryStore) -> None:
    src = _source()
    store.save_source_message(src)
    assert store.get_source_message("s1") == src


def test_get_source_message_missing_returns_none(store: PostgresDiaryStore) -> None:
    assert store.get_source_message("nope") is None


def test_restart_survival() -> None:
    """Two separate stores against the same DSN: writes from A visible to B."""
    assert PG_DSN is not None
    _truncate(PG_DSN)

    first = PostgresDiaryStore(PG_DSN)
    try:
        first.save_source_message(_source(sid="s1", family_id="fam-A"))
        first.save_diary_entry(_entry(eid="e1", sid="s1", family_id="fam-A"))
        first.save_event_chunks(
            [_chunk(cid="c1", eid="e1", sid="s1", family_id="fam-A", text="Walked the dog")]
        )
    finally:
        first.close()

    second = PostgresDiaryStore(PG_DSN)
    try:
        fetched = second.get_source_message("s1")
        assert fetched is not None
        assert fetched.source_message_id == "s1"

        chunk = second.get_event_chunk("c1")
        assert chunk is not None
        assert chunk.chunk_text == "Walked the dog"
    finally:
        second.close()


def test_get_or_create_source_message_returns_false_on_first_insert(
    store: PostgresDiaryStore,
) -> None:
    src = _source(sid="s1", external_message_id="42", edit_seq=0)

    persisted, replayed = store.get_or_create_source_message(src)

    assert replayed is False
    assert persisted == src
    assert store.get_source_message("s1") == src


def test_get_or_create_source_message_returns_true_on_replay(
    store: PostgresDiaryStore,
) -> None:
    original = _source(sid="s1", external_message_id="42", edit_seq=0)
    duplicate = _source(sid="different-uuid", external_message_id="42", edit_seq=0)

    store.get_or_create_source_message(original)
    persisted, replayed = store.get_or_create_source_message(duplicate)

    assert replayed is True
    assert persisted.source_message_id == "s1"
    assert persisted == original


def test_get_or_create_source_message_distinguishes_edit_seq(
    store: PostgresDiaryStore,
) -> None:
    original = _source(sid="s1", external_message_id="42", edit_seq=0)
    edited = _source(sid="s2", external_message_id="42", edit_seq=1715300100)

    _, replayed_a = store.get_or_create_source_message(original)
    _, replayed_b = store.get_or_create_source_message(edited)

    assert replayed_a is False
    assert replayed_b is False
    assert store.get_source_message("s1") is not None
    assert store.get_source_message("s2") is not None


def test_save_source_message_raises_on_duplicate_triple(store: PostgresDiaryStore) -> None:
    import psycopg.errors

    store.save_source_message(_source(sid="s1", external_message_id="42", edit_seq=0))

    with pytest.raises(psycopg.errors.UniqueViolation):
        store.save_source_message(_source(sid="s2", external_message_id="42", edit_seq=0))


def test_get_diary_entry_by_source_message_id(store: PostgresDiaryStore) -> None:
    store.save_source_message(_source(sid="s1"))
    store.save_diary_entry(_entry(eid="e1", sid="s1"))

    fetched = store.get_diary_entry_by_source_message_id("s1")
    assert fetched is not None
    assert fetched.diary_entry_id == "e1"


def test_get_diary_entry_by_source_message_id_missing_returns_none(
    store: PostgresDiaryStore,
) -> None:
    assert store.get_diary_entry_by_source_message_id("nope") is None


def test_count_event_chunks_for_source(store: PostgresDiaryStore) -> None:
    store.save_source_message(_source(sid="s1"))
    store.save_diary_entry(_entry(eid="e1", sid="s1"))
    store.save_event_chunks(
        [
            _chunk(cid="c1", eid="e1", sid="s1", idx=0),
            _chunk(cid="c2", eid="e1", sid="s1", text="Read a book", idx=1),
        ]
    )

    assert store.count_event_chunks_for_source("s1") == 2
    assert store.count_event_chunks_for_source("nope") == 0
