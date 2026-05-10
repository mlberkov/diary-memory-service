"""Integration tests for ``PostgresDiaryStore``.

Skipped unless ``DIARY_RAG_PG_TEST_DSN`` is set, so the offline test
flow stays green. Mirrors the case set in ``tests/test_sqlite_store.py``
(round-trip, family scoping, top-k, case-insensitive, empty inputs,
R-3 guard, restart survival).
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


def _source(*, sid: str = "s1", family_id: str = "fam-A") -> SourceMessage:
    return SourceMessage(
        source_message_id=sid,
        family_id=family_id,
        author_user_id="u1",
        external_chat_id=family_id,
        external_user_id="u1",
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


def test_search_chunks_family_scoping(store: PostgresDiaryStore) -> None:
    store.save_source_message(_source(sid="s1", family_id="fam-A"))
    store.save_diary_entry(_entry(eid="e1", sid="s1", family_id="fam-A"))
    store.save_event_chunks(
        [_chunk(cid="c1", eid="e1", sid="s1", family_id="fam-A", text="Walked the dog")]
    )

    store.save_source_message(_source(sid="s2", family_id="fam-B"))
    store.save_diary_entry(_entry(eid="e2", sid="s2", family_id="fam-B"))
    store.save_event_chunks(
        [_chunk(cid="c2", eid="e2", sid="s2", family_id="fam-B", text="Walked the dog")]
    )

    assert [h.chunk_id for h in store.search_chunks("fam-A", "dog", top_k=10)] == ["c1"]
    assert [h.chunk_id for h in store.search_chunks("fam-B", "dog", top_k=10)] == ["c2"]
    assert store.search_chunks("fam-C", "dog", top_k=10) == []


def test_search_chunks_insertion_order_and_topk_clamp(store: PostgresDiaryStore) -> None:
    store.save_source_message(_source())
    store.save_diary_entry(_entry())
    store.save_event_chunks(
        [
            _chunk(cid="c1", text="dog walk #1", idx=0),
            _chunk(cid="c2", text="dog walk #2", idx=1),
            _chunk(cid="c3", text="dog walk #3", idx=2),
        ]
    )

    hits = store.search_chunks("fam-A", "dog", top_k=2)
    assert [h.chunk_id for h in hits] == ["c1", "c2"]


def test_search_chunks_case_insensitive(store: PostgresDiaryStore) -> None:
    store.save_source_message(_source())
    store.save_diary_entry(_entry())
    store.save_event_chunks([_chunk(text="Walked the DOG")])

    assert [h.chunk_id for h in store.search_chunks("fam-A", "dog", top_k=10)] == ["c1"]


def test_search_chunks_empty_query_or_zero_topk(store: PostgresDiaryStore) -> None:
    store.save_source_message(_source())
    store.save_diary_entry(_entry())
    store.save_event_chunks([_chunk(text="Walked the dog")])

    assert store.search_chunks("fam-A", "", top_k=10) == []
    assert store.search_chunks("fam-A", "   ", top_k=10) == []
    assert store.search_chunks("fam-A", "dog", top_k=0) == []


def test_search_chunks_empty_family_id_raises(store: PostgresDiaryStore) -> None:
    with pytest.raises(ValueError):
        store.search_chunks("", "dog", top_k=5)


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

        hits = second.search_chunks("fam-A", "dog", top_k=10)
        assert [h.chunk_id for h in hits] == ["c1"]
    finally:
        second.close()
