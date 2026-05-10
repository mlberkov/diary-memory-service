"""Unit tests for ``SqliteDiaryStore``.

Covers round-trip save/fetch, family-scoped substring search,
top-k clamping, empty-input behaviour, end-to-end restart
survival, and the R-2 / D-023 idempotency contract enforced by
``UNIQUE (external_chat_id, external_message_id, edit_seq)`` plus
``INSERT OR IGNORE`` in ``get_or_create_source_message``.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from diary_rag.core.diary.models import DiaryEntry, EventChunk, SourceMessage
from diary_rag.core.routing import RouteKind
from diary_rag.storage.sqlite import SqliteDiaryStore


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


def test_round_trip_source_message(tmp_path: Path) -> None:
    store = SqliteDiaryStore(str(tmp_path / "diary.db"))
    src = _source()

    store.save_source_message(src)

    assert store.get_source_message("s1") == src


def test_get_source_message_missing_returns_none(tmp_path: Path) -> None:
    store = SqliteDiaryStore(str(tmp_path / "diary.db"))
    assert store.get_source_message("nope") is None


def test_search_chunks_family_scoping(tmp_path: Path) -> None:
    store = SqliteDiaryStore(str(tmp_path / "diary.db"))

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


def test_search_chunks_insertion_order_and_topk_clamp(tmp_path: Path) -> None:
    store = SqliteDiaryStore(str(tmp_path / "diary.db"))
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


def test_search_chunks_case_insensitive(tmp_path: Path) -> None:
    store = SqliteDiaryStore(str(tmp_path / "diary.db"))
    store.save_source_message(_source())
    store.save_diary_entry(_entry())
    store.save_event_chunks([_chunk(text="Walked the DOG")])

    assert [h.chunk_id for h in store.search_chunks("fam-A", "dog", top_k=10)] == ["c1"]


def test_search_chunks_empty_query_or_zero_topk(tmp_path: Path) -> None:
    store = SqliteDiaryStore(str(tmp_path / "diary.db"))
    store.save_source_message(_source())
    store.save_diary_entry(_entry())
    store.save_event_chunks([_chunk(text="Walked the dog")])

    assert store.search_chunks("fam-A", "", top_k=10) == []
    assert store.search_chunks("fam-A", "   ", top_k=10) == []
    assert store.search_chunks("fam-A", "dog", top_k=0) == []


def test_search_chunks_empty_family_id_raises(tmp_path: Path) -> None:
    store = SqliteDiaryStore(str(tmp_path / "diary.db"))
    with pytest.raises(ValueError):
        store.search_chunks("", "dog", top_k=5)


def test_restart_survival(tmp_path: Path) -> None:
    db_path = tmp_path / "diary.db"

    first = SqliteDiaryStore(str(db_path))
    first.save_source_message(_source(sid="s1", family_id="fam-A"))
    first.save_diary_entry(_entry(eid="e1", sid="s1", family_id="fam-A"))
    first.save_event_chunks(
        [_chunk(cid="c1", eid="e1", sid="s1", family_id="fam-A", text="Walked the dog")]
    )
    del first

    second = SqliteDiaryStore(str(db_path))
    fetched = second.get_source_message("s1")
    assert fetched is not None
    assert fetched.source_message_id == "s1"

    hits = second.search_chunks("fam-A", "dog", top_k=10)
    assert [h.chunk_id for h in hits] == ["c1"]


def test_get_or_create_source_message_returns_false_on_first_insert(tmp_path: Path) -> None:
    store = SqliteDiaryStore(str(tmp_path / "diary.db"))
    src = _source(sid="s1", external_message_id="42", edit_seq=0)

    persisted, replayed = store.get_or_create_source_message(src)

    assert replayed is False
    assert persisted == src
    assert store.get_source_message("s1") == src


def test_get_or_create_source_message_returns_true_on_replay(tmp_path: Path) -> None:
    store = SqliteDiaryStore(str(tmp_path / "diary.db"))
    original = _source(sid="s1", external_message_id="42", edit_seq=0)
    duplicate = _source(sid="different-uuid", external_message_id="42", edit_seq=0)

    store.get_or_create_source_message(original)
    persisted, replayed = store.get_or_create_source_message(duplicate)

    assert replayed is True
    assert persisted.source_message_id == "s1"
    assert persisted == original


def test_get_or_create_source_message_distinguishes_edit_seq(tmp_path: Path) -> None:
    store = SqliteDiaryStore(str(tmp_path / "diary.db"))
    original = _source(sid="s1", external_message_id="42", edit_seq=0)
    edited = _source(sid="s2", external_message_id="42", edit_seq=1715300100)

    _, replayed_a = store.get_or_create_source_message(original)
    _, replayed_b = store.get_or_create_source_message(edited)

    assert replayed_a is False
    assert replayed_b is False
    assert store.get_source_message("s1") is not None
    assert store.get_source_message("s2") is not None


def test_save_source_message_raises_on_duplicate_triple(tmp_path: Path) -> None:
    store = SqliteDiaryStore(str(tmp_path / "diary.db"))
    store.save_source_message(_source(sid="s1", external_message_id="42", edit_seq=0))

    with pytest.raises(sqlite3.IntegrityError):
        store.save_source_message(_source(sid="s2", external_message_id="42", edit_seq=0))


def test_get_diary_entry_by_source_message_id(tmp_path: Path) -> None:
    store = SqliteDiaryStore(str(tmp_path / "diary.db"))
    store.save_source_message(_source(sid="s1"))
    store.save_diary_entry(_entry(eid="e1", sid="s1"))

    fetched = store.get_diary_entry_by_source_message_id("s1")
    assert fetched is not None
    assert fetched.diary_entry_id == "e1"


def test_get_diary_entry_by_source_message_id_missing_returns_none(tmp_path: Path) -> None:
    store = SqliteDiaryStore(str(tmp_path / "diary.db"))
    assert store.get_diary_entry_by_source_message_id("nope") is None


def test_count_event_chunks_for_source(tmp_path: Path) -> None:
    store = SqliteDiaryStore(str(tmp_path / "diary.db"))
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
