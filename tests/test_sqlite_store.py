"""Unit tests for ``SqliteDomainStore``.

Covers round-trip save/fetch, restart survival, idempotent ingest (R-2 /
D-023), and the Slice 3.3 retirement of the substring search path:
SQLite is opt-in ingest only, so the new ``dense_candidates`` and
``sparse_candidates`` raise ``NotImplementedError`` (D-025). Retrieval
lives on Postgres only.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from memory_rag.core.domain.models import EventChunk, Note, SourceMessage
from memory_rag.core.routing import RouteKind
from memory_rag.storage.sqlite import SqliteDomainStore


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


def test_round_trip_source_message(tmp_path: Path) -> None:
    store = SqliteDomainStore(str(tmp_path / "diary.db"))
    src = _source()

    store.save_source_message(src)

    assert store.get_source_message("s1", community_id="fam-A") == src


def test_get_source_message_missing_returns_none(tmp_path: Path) -> None:
    store = SqliteDomainStore(str(tmp_path / "diary.db"))
    assert store.get_source_message("nope", community_id="fam-A") is None


def test_hybrid_retrieval_unsupported_on_sqlite(tmp_path: Path) -> None:
    store = SqliteDomainStore(str(tmp_path / "diary.db"))

    with pytest.raises(NotImplementedError, match="sqlite"):
        store.dense_candidates("fam-A", [0.0], "mock", 5)
    with pytest.raises(NotImplementedError, match="sqlite"):
        store.sparse_candidates("fam-A", "dog", 5)


def test_restart_survival(tmp_path: Path) -> None:
    db_path = tmp_path / "diary.db"

    first = SqliteDomainStore(str(db_path))
    first.save_source_message(_source(sid="s1", community_id="fam-A"))
    first.save_note(_note(eid="e1", sid="s1", community_id="fam-A"))
    first.save_event_chunks(
        [_chunk(cid="c1", eid="e1", sid="s1", community_id="fam-A", text="Walked the dog")]
    )
    del first

    second = SqliteDomainStore(str(db_path))
    fetched = second.get_source_message("s1", community_id="fam-A")
    assert fetched is not None
    assert fetched.source_message_id == "s1"

    chunk = second.get_event_chunk("c1", community_id="fam-A")
    assert chunk is not None
    assert chunk.chunk_text == "Walked the dog"


def test_get_or_create_source_message_returns_false_on_first_insert(tmp_path: Path) -> None:
    store = SqliteDomainStore(str(tmp_path / "diary.db"))
    src = _source(sid="s1", external_message_id="42", edit_seq=0)

    persisted, replayed = store.get_or_create_source_message(src)

    assert replayed is False
    assert persisted == src
    assert store.get_source_message("s1", community_id="fam-A") == src


def test_get_or_create_source_message_returns_true_on_replay(tmp_path: Path) -> None:
    store = SqliteDomainStore(str(tmp_path / "diary.db"))
    original = _source(sid="s1", external_message_id="42", edit_seq=0)
    duplicate = _source(sid="different-uuid", external_message_id="42", edit_seq=0)

    store.get_or_create_source_message(original)
    persisted, replayed = store.get_or_create_source_message(duplicate)

    assert replayed is True
    assert persisted.source_message_id == "s1"
    assert persisted == original


def test_get_or_create_source_message_distinguishes_edit_seq(tmp_path: Path) -> None:
    store = SqliteDomainStore(str(tmp_path / "diary.db"))
    original = _source(sid="s1", external_message_id="42", edit_seq=0)
    edited = _source(sid="s2", external_message_id="42", edit_seq=1715300100)

    _, replayed_a = store.get_or_create_source_message(original)
    _, replayed_b = store.get_or_create_source_message(edited)

    assert replayed_a is False
    assert replayed_b is False
    assert store.get_source_message("s1", community_id="fam-A") is not None
    assert store.get_source_message("s2", community_id="fam-A") is not None


def test_save_source_message_raises_on_duplicate_triple(tmp_path: Path) -> None:
    store = SqliteDomainStore(str(tmp_path / "diary.db"))
    store.save_source_message(_source(sid="s1", external_message_id="42", edit_seq=0))

    with pytest.raises(sqlite3.IntegrityError):
        store.save_source_message(_source(sid="s2", external_message_id="42", edit_seq=0))


def test_get_note_by_source_message_id(tmp_path: Path) -> None:
    store = SqliteDomainStore(str(tmp_path / "diary.db"))
    store.save_source_message(_source(sid="s1"))
    store.save_note(_note(eid="e1", sid="s1"))

    fetched = store.get_note_by_source_message_id("s1")
    assert fetched is not None
    assert fetched.note_id == "e1"


def test_get_note_by_source_message_id_missing_returns_none(tmp_path: Path) -> None:
    store = SqliteDomainStore(str(tmp_path / "diary.db"))
    assert store.get_note_by_source_message_id("nope") is None


def test_count_event_chunks_for_source(tmp_path: Path) -> None:
    store = SqliteDomainStore(str(tmp_path / "diary.db"))
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


def test_list_source_messages_raises_not_implemented(tmp_path: Path) -> None:
    store = SqliteDomainStore(str(tmp_path / "diary.db"))
    with pytest.raises(NotImplementedError, match="sqlite raw export not supported"):
        store.list_source_messages("fam-A")
