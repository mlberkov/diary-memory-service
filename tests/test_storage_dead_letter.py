"""Storage-backend tests for the indexing dead-letter seam (Slice 6.2).

Covers ``save_indexing_dead_letter`` / ``list_indexing_dead_letters`` /
``get_indexing_dead_letter`` across the three backends (mock, sqlite,
postgres). The dead-letter surface is operational inspection — every
backend implements it fully (full parity), unlike the raw-export seam.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from memory_rag.core.domain.models import IndexingDeadLetter, SourceMessage
from memory_rag.core.routing import RouteKind
from memory_rag.storage.mock import MockDomainStore
from memory_rag.storage.sqlite import SqliteDomainStore

PG_DSN = os.environ.get("MEMORY_RAG_PG_TEST_DSN")


def _at(hour: int) -> datetime:
    return datetime(2026, 5, 9, hour, 0, 0, tzinfo=UTC)


def _source(sid: str, community_id: str) -> SourceMessage:
    return SourceMessage(
        source_message_id=sid,
        community_id=community_id,
        author_user_id="u1",
        external_chat_id=community_id,
        external_user_id="u1",
        external_message_id=sid,
        edit_seq=0,
        raw_text="2026-05-09\nWalked the dog",
        detected_route=RouteKind.NOTE,
        created_at=_at(12),
    )


def _dead_letter(
    *,
    dlid: str = "dl1",
    sid: str = "s1",
    community_id: str = "fam-A",
    chunk_ids: tuple[str, ...] = ("c1", "c2"),
    model_name: str = "text-embedding-3-large",
    error_class: str = "APITimeoutError",
    created_at: datetime | None = None,
) -> IndexingDeadLetter:
    return IndexingDeadLetter(
        dead_letter_id=dlid,
        source_message_id=sid,
        community_id=community_id,
        chunk_ids=chunk_ids,
        model_name=model_name,
        error_class=error_class,
        created_at=created_at if created_at is not None else _at(12),
    )


# ---------------------------------------------------------------------------
# MockDomainStore
# ---------------------------------------------------------------------------


def test_mock_save_and_get_dead_letter_round_trip() -> None:
    store = MockDomainStore()
    store.save_indexing_dead_letter(_dead_letter(chunk_ids=("c1", "c2", "c3")))
    fetched = store.get_indexing_dead_letter("dl1")
    assert fetched is not None
    assert fetched.dead_letter_id == "dl1"
    assert fetched.source_message_id == "s1"
    assert fetched.chunk_ids == ("c1", "c2", "c3")
    assert fetched.model_name == "text-embedding-3-large"
    assert fetched.error_class == "APITimeoutError"


def test_mock_get_dead_letter_missing_returns_none() -> None:
    store = MockDomainStore()
    assert store.get_indexing_dead_letter("missing") is None


def test_mock_list_dead_letters_orders_most_recent_first() -> None:
    store = MockDomainStore()
    store.save_indexing_dead_letter(_dead_letter(dlid="dl1", created_at=_at(10)))
    store.save_indexing_dead_letter(_dead_letter(dlid="dl2", created_at=_at(12)))
    store.save_indexing_dead_letter(_dead_letter(dlid="dl3", created_at=_at(11)))
    rows = store.list_indexing_dead_letters("fam-A")
    assert [r.dead_letter_id for r in rows] == ["dl2", "dl3", "dl1"]


def test_mock_list_dead_letters_is_community_scoped() -> None:
    store = MockDomainStore()
    store.save_indexing_dead_letter(_dead_letter(dlid="dl-a", community_id="fam-A"))
    store.save_indexing_dead_letter(_dead_letter(dlid="dl-b", community_id="fam-B"))
    rows = store.list_indexing_dead_letters("fam-A")
    assert [r.dead_letter_id for r in rows] == ["dl-a"]


def test_mock_list_dead_letters_respects_limit() -> None:
    store = MockDomainStore()
    for i in range(5):
        store.save_indexing_dead_letter(_dead_letter(dlid=f"dl{i}", created_at=_at(10 + i)))
    rows = store.list_indexing_dead_letters("fam-A", limit=2)
    assert [r.dead_letter_id for r in rows] == ["dl4", "dl3"]


def test_mock_duplicate_dead_letter_id_raises() -> None:
    store = MockDomainStore()
    store.save_indexing_dead_letter(_dead_letter(dlid="dl1"))
    with pytest.raises(ValueError):
        store.save_indexing_dead_letter(_dead_letter(dlid="dl1"))


# ---------------------------------------------------------------------------
# SqliteDomainStore
# ---------------------------------------------------------------------------


def _sqlite_store(tmp_path: Path) -> SqliteDomainStore:
    store = SqliteDomainStore(str(tmp_path / "diary.db"))
    # The dead-letter row references source_messages via FK; seed the targets.
    store.save_source_message(_source("s1", "fam-A"))
    store.save_source_message(_source("s2", "fam-B"))
    return store


def test_sqlite_save_and_get_dead_letter_round_trip(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_indexing_dead_letter(_dead_letter(chunk_ids=("c1", "c2", "c3")))
    fetched = store.get_indexing_dead_letter("dl1")
    assert fetched is not None
    assert fetched.dead_letter_id == "dl1"
    assert fetched.source_message_id == "s1"
    assert fetched.chunk_ids == ("c1", "c2", "c3")
    assert fetched.model_name == "text-embedding-3-large"
    assert fetched.error_class == "APITimeoutError"
    assert fetched.created_at == _at(12)


def test_sqlite_get_dead_letter_missing_returns_none(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    assert store.get_indexing_dead_letter("missing") is None


def test_sqlite_list_dead_letters_orders_most_recent_first(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_indexing_dead_letter(_dead_letter(dlid="dl1", created_at=_at(10)))
    store.save_indexing_dead_letter(_dead_letter(dlid="dl2", created_at=_at(12)))
    store.save_indexing_dead_letter(_dead_letter(dlid="dl3", created_at=_at(11)))
    rows = store.list_indexing_dead_letters("fam-A")
    assert [r.dead_letter_id for r in rows] == ["dl2", "dl3", "dl1"]


def test_sqlite_list_dead_letters_is_community_scoped(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_indexing_dead_letter(_dead_letter(dlid="dl-a", sid="s1", community_id="fam-A"))
    store.save_indexing_dead_letter(_dead_letter(dlid="dl-b", sid="s2", community_id="fam-B"))
    rows = store.list_indexing_dead_letters("fam-A")
    assert [r.dead_letter_id for r in rows] == ["dl-a"]


def test_sqlite_list_dead_letters_respects_limit(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    for i in range(5):
        store.save_indexing_dead_letter(_dead_letter(dlid=f"dl{i}", created_at=_at(10 + i)))
    rows = store.list_indexing_dead_letters("fam-A", limit=2)
    assert [r.dead_letter_id for r in rows] == ["dl4", "dl3"]


def test_sqlite_duplicate_dead_letter_id_raises(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_indexing_dead_letter(_dead_letter(dlid="dl1"))
    with pytest.raises(sqlite3.IntegrityError):
        store.save_indexing_dead_letter(_dead_letter(dlid="dl1"))


# ---------------------------------------------------------------------------
# PostgresDomainStore
# ---------------------------------------------------------------------------


pgmark = pytest.mark.skipif(
    PG_DSN is None,
    reason="MEMORY_RAG_PG_TEST_DSN not set; Postgres integration tests skipped.",
)


if PG_DSN is not None:
    import psycopg

    from memory_rag.storage.postgres import PostgresDomainStore


def _truncate(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE indexing_dead_letters, retrieval_hits, queries, "
            "embedding_records, event_chunks, notes, source_messages "
            "RESTART IDENTITY CASCADE"
        )


@pytest.fixture
def pg_store() -> Iterator[PostgresDomainStore]:
    assert PG_DSN is not None
    s = PostgresDomainStore(PG_DSN)
    try:
        _truncate(PG_DSN)
        # Seed FK targets so indexing_dead_letters.source_message_id resolves.
        s.save_source_message(_source("s1", "fam-A"))
        s.save_source_message(_source("s2", "fam-B"))
        yield s
    finally:
        s.close()


@pgmark
def test_pg_save_and_get_dead_letter_round_trip(pg_store: PostgresDomainStore) -> None:
    pg_store.save_indexing_dead_letter(_dead_letter(chunk_ids=("c1", "c2", "c3")))
    fetched = pg_store.get_indexing_dead_letter("dl1")
    assert fetched is not None
    assert fetched.dead_letter_id == "dl1"
    assert fetched.source_message_id == "s1"
    assert fetched.chunk_ids == ("c1", "c2", "c3")
    assert fetched.model_name == "text-embedding-3-large"
    assert fetched.error_class == "APITimeoutError"
    assert fetched.created_at == _at(12)


@pgmark
def test_pg_get_dead_letter_missing_returns_none(pg_store: PostgresDomainStore) -> None:
    assert pg_store.get_indexing_dead_letter("missing") is None


@pgmark
def test_pg_list_dead_letters_orders_most_recent_first(pg_store: PostgresDomainStore) -> None:
    pg_store.save_indexing_dead_letter(_dead_letter(dlid="dl1", created_at=_at(10)))
    pg_store.save_indexing_dead_letter(_dead_letter(dlid="dl2", created_at=_at(12)))
    pg_store.save_indexing_dead_letter(_dead_letter(dlid="dl3", created_at=_at(11)))
    rows = pg_store.list_indexing_dead_letters("fam-A")
    assert [r.dead_letter_id for r in rows] == ["dl2", "dl3", "dl1"]


@pgmark
def test_pg_list_dead_letters_is_community_scoped(pg_store: PostgresDomainStore) -> None:
    pg_store.save_indexing_dead_letter(_dead_letter(dlid="dl-a", sid="s1", community_id="fam-A"))
    pg_store.save_indexing_dead_letter(_dead_letter(dlid="dl-b", sid="s2", community_id="fam-B"))
    rows = pg_store.list_indexing_dead_letters("fam-A")
    assert [r.dead_letter_id for r in rows] == ["dl-a"]


@pgmark
def test_pg_list_dead_letters_respects_limit(pg_store: PostgresDomainStore) -> None:
    for i in range(5):
        pg_store.save_indexing_dead_letter(_dead_letter(dlid=f"dl{i}", created_at=_at(10 + i)))
    rows = pg_store.list_indexing_dead_letters("fam-A", limit=2)
    assert [r.dead_letter_id for r in rows] == ["dl4", "dl3"]


@pgmark
def test_pg_duplicate_dead_letter_id_raises(pg_store: PostgresDomainStore) -> None:
    pg_store.save_indexing_dead_letter(_dead_letter(dlid="dl1"))
    with pytest.raises(psycopg.errors.UniqueViolation):
        pg_store.save_indexing_dead_letter(_dead_letter(dlid="dl1"))
