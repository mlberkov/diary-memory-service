"""Integration tests for ``PostgresDomainStore`` (ingest contract only).

Skipped unless ``MEMORY_RAG_PG_TEST_DSN`` is set, so the offline test
flow stays green. Retrieval coverage lives in
``tests/test_search_repository_postgres.py`` (Slice 3.3 / D-025).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest

from memory_rag.core.domain.models import EventChunk, Note, SourceMessage
from memory_rag.core.routing import RouteKind

PG_DSN = os.environ.get("MEMORY_RAG_PG_TEST_DSN")

pytestmark = pytest.mark.skipif(
    PG_DSN is None,
    reason="MEMORY_RAG_PG_TEST_DSN not set; Postgres integration tests skipped.",
)

if PG_DSN is not None:
    import psycopg

    from memory_rag.storage.postgres import PostgresDomainStore


def _truncate(dsn: str) -> None:
    """Reset the three diary tables. Schema is bootstrapped on store init."""
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE event_chunks, notes, source_messages " "RESTART IDENTITY CASCADE")


@pytest.fixture
def store() -> Iterator[PostgresDomainStore]:
    assert PG_DSN is not None
    s = PostgresDomainStore(PG_DSN)
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
    community_id: str = "fam-A",
    external_message_id: str | None = None,
    edit_seq: int = 0,
) -> SourceMessage:
    return SourceMessage(
        source_message_id=sid,
        community_id=community_id,
        author_user_id="u1",
        external_chat_id=community_id,
        external_user_id="u1",
        external_message_id=external_message_id if external_message_id is not None else sid,
        edit_seq=edit_seq,
        raw_text="2026-05-09\nWalked the dog",
        detected_route=RouteKind.NOTE,
        created_at=_now(),
    )


def _note(*, eid: str = "e1", sid: str = "s1", community_id: str = "fam-A") -> Note:
    return Note(
        note_id=eid,
        source_message_id=sid,
        community_id=community_id,
        author_user_id="u1",
        note_date=date(2026, 5, 9),
        note_text="Walked the dog",
        created_at=_now(),
    )


def _chunk(
    *,
    cid: str = "c1",
    eid: str = "e1",
    sid: str = "s1",
    community_id: str = "fam-A",
    text: str = "Walked the dog",
    idx: int = 0,
) -> EventChunk:
    return EventChunk(
        chunk_id=cid,
        note_id=eid,
        source_message_id=sid,
        community_id=community_id,
        author_user_id="u1",
        note_date=date(2026, 5, 9),
        event_index=idx,
        chunk_text=text,
        created_at=_now(),
    )


def test_round_trip_source_message(store: PostgresDomainStore) -> None:
    src = _source()
    store.save_source_message(src)
    assert store.get_source_message("s1", community_id="fam-A") == src


def test_get_source_message_missing_returns_none(store: PostgresDomainStore) -> None:
    assert store.get_source_message("nope", community_id="fam-A") is None


def test_restart_survival() -> None:
    """Two separate stores against the same DSN: writes from A visible to B."""
    assert PG_DSN is not None
    _truncate(PG_DSN)

    first = PostgresDomainStore(PG_DSN)
    try:
        first.save_source_message(_source(sid="s1", community_id="fam-A"))
        first.save_note(_note(eid="e1", sid="s1", community_id="fam-A"))
        first.save_event_chunks(
            [_chunk(cid="c1", eid="e1", sid="s1", community_id="fam-A", text="Walked the dog")]
        )
    finally:
        first.close()

    second = PostgresDomainStore(PG_DSN)
    try:
        fetched = second.get_source_message("s1", community_id="fam-A")
        assert fetched is not None
        assert fetched.source_message_id == "s1"

        chunk = second.get_event_chunk("c1", community_id="fam-A")
        assert chunk is not None
        assert chunk.chunk_text == "Walked the dog"
    finally:
        second.close()


def test_get_or_create_source_message_returns_false_on_first_insert(
    store: PostgresDomainStore,
) -> None:
    src = _source(sid="s1", external_message_id="42", edit_seq=0)

    persisted, replayed = store.get_or_create_source_message(src)

    assert replayed is False
    assert persisted == src
    assert store.get_source_message("s1", community_id="fam-A") == src


def test_get_or_create_source_message_returns_true_on_replay(
    store: PostgresDomainStore,
) -> None:
    original = _source(sid="s1", external_message_id="42", edit_seq=0)
    duplicate = _source(sid="different-uuid", external_message_id="42", edit_seq=0)

    store.get_or_create_source_message(original)
    persisted, replayed = store.get_or_create_source_message(duplicate)

    assert replayed is True
    assert persisted.source_message_id == "s1"
    assert persisted == original


def test_get_or_create_source_message_distinguishes_edit_seq(
    store: PostgresDomainStore,
) -> None:
    original = _source(sid="s1", external_message_id="42", edit_seq=0)
    edited = _source(sid="s2", external_message_id="42", edit_seq=1715300100)

    _, replayed_a = store.get_or_create_source_message(original)
    _, replayed_b = store.get_or_create_source_message(edited)

    assert replayed_a is False
    assert replayed_b is False
    assert store.get_source_message("s1", community_id="fam-A") is not None
    assert store.get_source_message("s2", community_id="fam-A") is not None


def test_save_source_message_raises_on_duplicate_triple(store: PostgresDomainStore) -> None:
    import psycopg.errors

    store.save_source_message(_source(sid="s1", external_message_id="42", edit_seq=0))

    with pytest.raises(psycopg.errors.UniqueViolation):
        store.save_source_message(_source(sid="s2", external_message_id="42", edit_seq=0))


def test_get_note_by_source_message_id(store: PostgresDomainStore) -> None:
    store.save_source_message(_source(sid="s1"))
    store.save_note(_note(eid="e1", sid="s1"))

    fetched = store.get_note_by_source_message_id("s1")
    assert fetched is not None
    assert fetched.note_id == "e1"


def test_get_note_by_source_message_id_missing_returns_none(
    store: PostgresDomainStore,
) -> None:
    assert store.get_note_by_source_message_id("nope") is None


def test_count_event_chunks_for_source(store: PostgresDomainStore) -> None:
    store.save_source_message(_source(sid="s1"))
    store.save_note(_note(eid="e1", sid="s1"))
    store.save_event_chunks(
        [
            _chunk(cid="c1", eid="e1", sid="s1", idx=0),
            _chunk(cid="c2", eid="e1", sid="s1", text="Read a book", idx=1),
        ]
    )

    assert store.count_event_chunks_for_source("s1") == 2
    assert store.count_event_chunks_for_source("nope") == 0


def test_save_source_message_accepts_draft_route(store: PostgresDomainStore) -> None:
    """D-027: the CHECK constraint on ``detected_route`` includes ``'draft'``."""
    draft = SourceMessage(
        source_message_id="d1",
        community_id="fam-A",
        author_user_id="u1",
        external_chat_id="fam-A",
        external_user_id="u1",
        external_message_id="m-draft",
        edit_seq=0,
        raw_text="ambiguous text without a date",
        detected_route=RouteKind.DRAFT,
        created_at=_now(),
    )

    store.save_source_message(draft)

    fetched = store.get_source_message("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.detected_route is RouteKind.DRAFT


def test_get_or_create_source_message_idempotent_for_draft_route(
    store: PostgresDomainStore,
) -> None:
    """R-2 holds for drafts: replay returns the existing row, no duplicate."""
    draft = SourceMessage(
        source_message_id="d1",
        community_id="fam-A",
        author_user_id="u1",
        external_chat_id="fam-A",
        external_user_id="u1",
        external_message_id="m-draft",
        edit_seq=0,
        raw_text="ambiguous text",
        detected_route=RouteKind.DRAFT,
        created_at=_now(),
    )
    duplicate = SourceMessage(
        source_message_id="d2",
        community_id="fam-A",
        author_user_id="u1",
        external_chat_id="fam-A",
        external_user_id="u1",
        external_message_id="m-draft",
        edit_seq=0,
        raw_text="ambiguous text",
        detected_route=RouteKind.DRAFT,
        created_at=_now(),
    )

    store.get_or_create_source_message(draft)
    persisted, replayed = store.get_or_create_source_message(duplicate)

    assert replayed is True
    assert persisted.source_message_id == "d1"
    assert persisted.detected_route is RouteKind.DRAFT


def test_list_source_messages_is_family_scoped_and_ordered(
    store: PostgresDomainStore,
) -> None:
    base = datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC)
    store.save_source_message(
        SourceMessage(
            source_message_id="a",
            community_id="fam-A",
            author_user_id="u1",
            external_chat_id="fam-A",
            external_user_id="u1",
            external_message_id="1",
            edit_seq=0,
            raw_text="first",
            detected_route=RouteKind.NOTE,
            created_at=base,
        )
    )
    store.save_source_message(
        SourceMessage(
            source_message_id="b",
            community_id="fam-A",
            author_user_id="u1",
            external_chat_id="fam-A",
            external_user_id="u1",
            external_message_id="2",
            edit_seq=0,
            raw_text="second",
            detected_route=RouteKind.DRAFT,
            created_at=base.replace(hour=11),
        )
    )
    store.save_source_message(
        SourceMessage(
            source_message_id="other",
            community_id="fam-B",
            author_user_id="u2",
            external_chat_id="fam-B",
            external_user_id="u2",
            external_message_id="3",
            edit_seq=0,
            raw_text="other family",
            detected_route=RouteKind.NOTE,
            created_at=base,
        )
    )

    rows = store.list_source_messages("fam-A")
    assert [r.source_message_id for r in rows] == ["a", "b"]
    assert [r.detected_route for r in rows] == [RouteKind.NOTE, RouteKind.DRAFT]

    rows_limited = store.list_source_messages("fam-A", limit=1)
    assert [r.source_message_id for r in rows_limited] == ["a"]
