"""Storage-backend tests for the retrieval-trace seam (Slice 3.5).

Covers ``save_query`` / ``save_retrieval_hits`` /
``get_query`` / ``get_retrieval_hits_for_query`` across the three
backends (mock, sqlite, postgres). SQLite is a real implementation
here — the trace tables and methods are ingest-shaped, not retrieval-
shaped, so the D-022 / D-025 retrieval-only restriction does not apply.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from memory_rag.core.domain.models import (
    EventChunk,
    FallbackMode,
    Note,
    Query,
    RetrievalHit,
    RetrievalLeg,
    SourceMessage,
)
from memory_rag.core.routing import RouteKind
from memory_rag.storage.mock import MockDomainStore
from memory_rag.storage.repository import DomainRepository
from memory_rag.storage.sqlite import SqliteDomainStore

PG_DSN = os.environ.get("MEMORY_RAG_PG_TEST_DSN")


def _now() -> datetime:
    return datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC)


def _query(
    *,
    qid: str = "q1",
    community_id: str = "fam-A",
    text: str = "book",
    model_name: str = "mock",
    fallback: FallbackMode = FallbackMode.NONE,
    subject_scope: str | None = None,
) -> Query:
    return Query(
        query_id=qid,
        community_id=community_id,
        query_text=text,
        model_name=model_name,
        fallback=fallback,
        created_at=_now(),
        subject_scope=subject_scope,
    )


def _hit(
    *,
    hid: str,
    qid: str = "q1",
    chunk_id: str = "c1",
    leg: RetrievalLeg = RetrievalLeg.DENSE,
    rank: int = 1,
    score: float = 0.5,
    model_name: str = "mock",
) -> RetrievalHit:
    return RetrievalHit(
        retrieval_hit_id=hid,
        query_id=qid,
        chunk_id=chunk_id,
        leg=leg,
        rank=rank,
        score=score,
        model_name=model_name,
        created_at=_now(),
    )


def _source(sid: str = "s1", community_id: str = "fam-A") -> SourceMessage:
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
        created_at=_now(),
    )


def _note(eid: str = "e1", sid: str = "s1") -> Note:
    return Note(
        note_id=eid,
        source_message_id=sid,
        community_id="fam-A",
        author_user_id="u1",
        note_date=date(2026, 5, 9),
        note_text="Walked the dog",
        created_at=_now(),
    )


def _chunk(cid: str = "c1", eid: str = "e1", sid: str = "s1", idx: int = 0) -> EventChunk:
    return EventChunk(
        chunk_id=cid,
        note_id=eid,
        source_message_id=sid,
        community_id="fam-A",
        author_user_id="u1",
        note_date=date(2026, 5, 9),
        event_index=idx,
        chunk_text="Walked the dog",
        created_at=_now(),
    )


# ---------------------------------------------------------------------------
# MockDomainStore
# ---------------------------------------------------------------------------


def test_mock_save_and_get_query_round_trip() -> None:
    store = MockDomainStore()
    store.save_query(_query(qid="q1", text="book"))
    fetched = store.get_query("q1", community_id="fam-A")
    assert fetched is not None
    assert fetched.query_id == "q1"
    assert fetched.query_text == "book"
    assert fetched.fallback is FallbackMode.NONE


def test_mock_query_subject_scope_round_trip() -> None:
    """``Query.subject_scope`` round-trips (H-3, D-107); default stays None."""
    store = MockDomainStore()
    store.save_query(_query(qid="q1", subject_scope="subj-1"))
    store.save_query(_query(qid="q2"))
    scoped = store.get_query("q1", community_id="fam-A")
    unscoped = store.get_query("q2", community_id="fam-A")
    assert scoped is not None and scoped.subject_scope == "subj-1"
    assert unscoped is not None and unscoped.subject_scope is None


def test_mock_get_query_missing_returns_none() -> None:
    store = MockDomainStore()
    assert store.get_query("missing", community_id="fam-A") is None


def test_mock_save_retrieval_hits_round_trip_orders_by_leg_then_rank() -> None:
    store = MockDomainStore()
    store.save_query(_query(qid="q1"))
    store.save_retrieval_hits(
        [
            _hit(hid="h-m1", chunk_id="c1", leg=RetrievalLeg.MERGED, rank=1),
            _hit(hid="h-s1", chunk_id="c1", leg=RetrievalLeg.SPARSE, rank=1),
            _hit(hid="h-d1", chunk_id="c1", leg=RetrievalLeg.DENSE, rank=1),
            _hit(hid="h-d2", chunk_id="c2", leg=RetrievalLeg.DENSE, rank=2),
        ]
    )
    rows = store.get_retrieval_hits_for_query("q1", community_id="fam-A")
    assert [(r.leg, r.rank) for r in rows] == [
        (RetrievalLeg.DENSE, 1),
        (RetrievalLeg.DENSE, 2),
        (RetrievalLeg.MERGED, 1),
        (RetrievalLeg.SPARSE, 1),
    ]


def test_mock_no_evidence_query_has_no_hits() -> None:
    store = MockDomainStore()
    store.save_query(_query(qid="q1", fallback=FallbackMode.NO_EVIDENCE))
    assert store.get_query("q1", community_id="fam-A") is not None
    assert store.get_retrieval_hits_for_query("q1", community_id="fam-A") == []


def test_mock_duplicate_query_id_raises() -> None:
    store = MockDomainStore()
    store.save_query(_query(qid="q1"))
    with pytest.raises(ValueError):
        store.save_query(_query(qid="q1"))


def test_mock_duplicate_retrieval_hit_id_raises() -> None:
    store = MockDomainStore()
    store.save_query(_query(qid="q1"))
    store.save_retrieval_hits([_hit(hid="h1")])
    with pytest.raises(ValueError):
        store.save_retrieval_hits([_hit(hid="h1")])


# ---------------------------------------------------------------------------
# SqliteDomainStore
# ---------------------------------------------------------------------------


def _sqlite_store(tmp_path: Path) -> SqliteDomainStore:
    store = SqliteDomainStore(str(tmp_path / "diary.db"))
    # Hits reference event_chunks via FK; satisfy the FK before writing hits.
    store.save_source_message(_source())
    store.save_note(_note())
    store.save_event_chunks([_chunk("c1", idx=0), _chunk("c2", idx=1)])
    return store


def test_sqlite_save_and_get_query_round_trip(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_query(_query(qid="q1", text="book"))
    fetched = store.get_query("q1", community_id="fam-A")
    assert fetched is not None
    assert fetched.query_id == "q1"
    assert fetched.query_text == "book"
    assert fetched.fallback is FallbackMode.NONE


def test_sqlite_query_subject_scope_round_trip(tmp_path: Path) -> None:
    """``Query.subject_scope`` round-trips (H-3, D-107); default stays None."""
    store = _sqlite_store(tmp_path)
    store.save_query(_query(qid="q1", subject_scope="subj-1"))
    store.save_query(_query(qid="q2"))
    scoped = store.get_query("q1", community_id="fam-A")
    unscoped = store.get_query("q2", community_id="fam-A")
    assert scoped is not None and scoped.subject_scope == "subj-1"
    assert unscoped is not None and unscoped.subject_scope is None


def test_sqlite_save_retrieval_hits_round_trip_orders_by_leg_then_rank(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_query(_query(qid="q1"))
    store.save_retrieval_hits(
        [
            _hit(hid="h-m1", chunk_id="c1", leg=RetrievalLeg.MERGED, rank=1),
            _hit(hid="h-s1", chunk_id="c1", leg=RetrievalLeg.SPARSE, rank=1),
            _hit(hid="h-d1", chunk_id="c1", leg=RetrievalLeg.DENSE, rank=1),
            _hit(hid="h-d2", chunk_id="c2", leg=RetrievalLeg.DENSE, rank=2),
        ]
    )
    rows = store.get_retrieval_hits_for_query("q1", community_id="fam-A")
    assert [(r.leg, r.rank) for r in rows] == [
        (RetrievalLeg.DENSE, 1),
        (RetrievalLeg.DENSE, 2),
        (RetrievalLeg.MERGED, 1),
        (RetrievalLeg.SPARSE, 1),
    ]


def test_sqlite_no_evidence_query_persists_with_zero_hits(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_query(_query(qid="q1", fallback=FallbackMode.NO_EVIDENCE))
    fetched = store.get_query("q1", community_id="fam-A")
    assert fetched is not None
    assert fetched.fallback is FallbackMode.NO_EVIDENCE
    assert store.get_retrieval_hits_for_query("q1", community_id="fam-A") == []


def test_sqlite_unique_constraint_on_query_chunk_leg(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_query(_query(qid="q1"))
    store.save_retrieval_hits([_hit(hid="h1", leg=RetrievalLeg.DENSE, rank=1)])
    with pytest.raises(sqlite3.IntegrityError):
        store.save_retrieval_hits([_hit(hid="h2", leg=RetrievalLeg.DENSE, rank=2)])


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
            "TRUNCATE retrieval_hits, queries, embedding_records, "
            "event_chunks, notes, source_messages "
            "RESTART IDENTITY CASCADE"
        )


@pytest.fixture
def pg_store() -> Iterator[PostgresDomainStore]:
    assert PG_DSN is not None
    s = PostgresDomainStore(PG_DSN)
    try:
        _truncate(PG_DSN)
        # Seed FK targets so retrieval_hits.chunk_id references a real row.
        s.save_source_message(_source())
        s.save_note(_note())
        s.save_event_chunks([_chunk("c1", idx=0), _chunk("c2", idx=1)])
        yield s
    finally:
        s.close()


@pgmark
def test_pg_save_and_get_query_round_trip(pg_store: PostgresDomainStore) -> None:
    pg_store.save_query(_query(qid="q1", text="book"))
    fetched = pg_store.get_query("q1", community_id="fam-A")
    assert fetched is not None
    assert fetched.query_id == "q1"
    assert fetched.query_text == "book"
    assert fetched.fallback is FallbackMode.NONE


@pgmark
def test_pg_query_subject_scope_round_trip(pg_store: PostgresDomainStore) -> None:
    """``Query.subject_scope`` round-trips (H-3, D-107); default stays None."""
    pg_store.save_query(_query(qid="q1", subject_scope="subj-1"))
    pg_store.save_query(_query(qid="q2"))
    scoped = pg_store.get_query("q1", community_id="fam-A")
    unscoped = pg_store.get_query("q2", community_id="fam-A")
    assert scoped is not None and scoped.subject_scope == "subj-1"
    assert unscoped is not None and unscoped.subject_scope is None


@pgmark
def test_pg_save_retrieval_hits_round_trip_orders_by_leg_then_rank(
    pg_store: PostgresDomainStore,
) -> None:
    pg_store.save_query(_query(qid="q1"))
    pg_store.save_retrieval_hits(
        [
            _hit(hid="h-m1", chunk_id="c1", leg=RetrievalLeg.MERGED, rank=1),
            _hit(hid="h-s1", chunk_id="c1", leg=RetrievalLeg.SPARSE, rank=1),
            _hit(hid="h-d1", chunk_id="c1", leg=RetrievalLeg.DENSE, rank=1),
            _hit(hid="h-d2", chunk_id="c2", leg=RetrievalLeg.DENSE, rank=2),
        ]
    )
    rows = pg_store.get_retrieval_hits_for_query("q1", community_id="fam-A")
    assert [(r.leg, r.rank) for r in rows] == [
        (RetrievalLeg.DENSE, 1),
        (RetrievalLeg.DENSE, 2),
        (RetrievalLeg.MERGED, 1),
        (RetrievalLeg.SPARSE, 1),
    ]


@pgmark
def test_pg_no_evidence_query_persists_with_zero_hits(pg_store: PostgresDomainStore) -> None:
    pg_store.save_query(_query(qid="q1", fallback=FallbackMode.NO_EVIDENCE))
    fetched = pg_store.get_query("q1", community_id="fam-A")
    assert fetched is not None
    assert fetched.fallback is FallbackMode.NO_EVIDENCE
    assert pg_store.get_retrieval_hits_for_query("q1", community_id="fam-A") == []


@pgmark
def test_pg_unique_constraint_on_query_chunk_leg(pg_store: PostgresDomainStore) -> None:
    pg_store.save_query(_query(qid="q1"))
    pg_store.save_retrieval_hits([_hit(hid="h1", leg=RetrievalLeg.DENSE, rank=1)])
    with pytest.raises(psycopg.errors.UniqueViolation):
        pg_store.save_retrieval_hits([_hit(hid="h2", leg=RetrievalLeg.DENSE, rank=2)])


# ---------------------------------------------------------------------------
# Read-access enforcement (Slice 8.1.1 / D-088)
#
# get_query filters its own community_id column; get_retrieval_hits_for_query
# scopes via the query_id -> queries.community_id join. These tests run across
# every backend from one parametrized fixture so the fail-closed behavior
# cannot drift by backend (mock / sqlite / postgres).
# ---------------------------------------------------------------------------


@pytest.fixture(params=["mock", "sqlite"] + (["postgres"] if PG_DSN else []))
def scoped_store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[DomainRepository]:
    """A store with the source/note/chunk FK targets seeded for trace writes."""
    if request.param == "mock":
        store: DomainRepository = MockDomainStore()
    elif request.param == "sqlite":
        store = SqliteDomainStore(str(tmp_path / "scoped.db"))
    else:
        assert PG_DSN is not None
        _truncate(PG_DSN)
        pg = PostgresDomainStore(PG_DSN)
        pg.save_source_message(_source())
        pg.save_note(_note())
        pg.save_event_chunks([_chunk("c1", idx=0), _chunk("c2", idx=1)])
        try:
            yield pg
        finally:
            pg.close()
        return
    store.save_source_message(_source())
    store.save_note(_note())
    store.save_event_chunks([_chunk("c1", idx=0), _chunk("c2", idx=1)])
    yield store


def test_get_query_rejects_empty_community_id(
    scoped_store: DomainRepository,
) -> None:
    scoped_store.save_query(_query(qid="q1"))
    with pytest.raises(ValueError, match="community_id is required"):
        scoped_store.get_query("q1", community_id="")


def test_get_retrieval_hits_rejects_empty_community_id(
    scoped_store: DomainRepository,
) -> None:
    scoped_store.save_query(_query(qid="q1"))
    with pytest.raises(ValueError, match="community_id is required"):
        scoped_store.get_retrieval_hits_for_query("q1", community_id="")


def test_get_query_cross_community_reads_as_none(
    scoped_store: DomainRepository,
) -> None:
    scoped_store.save_query(_query(qid="q1", community_id="fam-A"))
    assert scoped_store.get_query("q1", community_id="fam-A") is not None
    # Same query_id, different community: no leak.
    assert scoped_store.get_query("q1", community_id="fam-B") is None


def test_get_retrieval_hits_cross_community_reads_as_empty(
    scoped_store: DomainRepository,
) -> None:
    scoped_store.save_query(_query(qid="q1", community_id="fam-A"))
    scoped_store.save_retrieval_hits([_hit(hid="h1", leg=RetrievalLeg.DENSE, rank=1)])
    assert scoped_store.get_retrieval_hits_for_query("q1", community_id="fam-A") != []
    # Same query_id, different community: the queries join filters it out.
    assert scoped_store.get_retrieval_hits_for_query("q1", community_id="fam-B") == []


def test_get_retrieval_hits_missing_parent_query_reads_as_empty(
    scoped_store: DomainRepository,
) -> None:
    """Fail-closed when no parent query row exists for the id (shared across backends)."""
    assert scoped_store.get_retrieval_hits_for_query("no-such-q", community_id="fam-A") == []
