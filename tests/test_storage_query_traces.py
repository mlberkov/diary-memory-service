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
) -> Query:
    return Query(
        query_id=qid,
        community_id=community_id,
        query_text=text,
        model_name=model_name,
        fallback=fallback,
        created_at=_now(),
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
    fetched = store.get_query("q1")
    assert fetched is not None
    assert fetched.query_id == "q1"
    assert fetched.query_text == "book"
    assert fetched.fallback is FallbackMode.NONE


def test_mock_get_query_missing_returns_none() -> None:
    store = MockDomainStore()
    assert store.get_query("missing") is None


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
    rows = store.get_retrieval_hits_for_query("q1")
    assert [(r.leg, r.rank) for r in rows] == [
        (RetrievalLeg.DENSE, 1),
        (RetrievalLeg.DENSE, 2),
        (RetrievalLeg.MERGED, 1),
        (RetrievalLeg.SPARSE, 1),
    ]


def test_mock_no_evidence_query_has_no_hits() -> None:
    store = MockDomainStore()
    store.save_query(_query(qid="q1", fallback=FallbackMode.NO_EVIDENCE))
    assert store.get_query("q1") is not None
    assert store.get_retrieval_hits_for_query("q1") == []


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
    fetched = store.get_query("q1")
    assert fetched is not None
    assert fetched.query_id == "q1"
    assert fetched.query_text == "book"
    assert fetched.fallback is FallbackMode.NONE


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
    rows = store.get_retrieval_hits_for_query("q1")
    assert [(r.leg, r.rank) for r in rows] == [
        (RetrievalLeg.DENSE, 1),
        (RetrievalLeg.DENSE, 2),
        (RetrievalLeg.MERGED, 1),
        (RetrievalLeg.SPARSE, 1),
    ]


def test_sqlite_no_evidence_query_persists_with_zero_hits(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_query(_query(qid="q1", fallback=FallbackMode.NO_EVIDENCE))
    fetched = store.get_query("q1")
    assert fetched is not None
    assert fetched.fallback is FallbackMode.NO_EVIDENCE
    assert store.get_retrieval_hits_for_query("q1") == []


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
    fetched = pg_store.get_query("q1")
    assert fetched is not None
    assert fetched.query_id == "q1"
    assert fetched.query_text == "book"
    assert fetched.fallback is FallbackMode.NONE


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
    rows = pg_store.get_retrieval_hits_for_query("q1")
    assert [(r.leg, r.rank) for r in rows] == [
        (RetrievalLeg.DENSE, 1),
        (RetrievalLeg.DENSE, 2),
        (RetrievalLeg.MERGED, 1),
        (RetrievalLeg.SPARSE, 1),
    ]


@pgmark
def test_pg_no_evidence_query_persists_with_zero_hits(pg_store: PostgresDomainStore) -> None:
    pg_store.save_query(_query(qid="q1", fallback=FallbackMode.NO_EVIDENCE))
    fetched = pg_store.get_query("q1")
    assert fetched is not None
    assert fetched.fallback is FallbackMode.NO_EVIDENCE
    assert pg_store.get_retrieval_hits_for_query("q1") == []


@pgmark
def test_pg_unique_constraint_on_query_chunk_leg(pg_store: PostgresDomainStore) -> None:
    pg_store.save_query(_query(qid="q1"))
    pg_store.save_retrieval_hits([_hit(hid="h1", leg=RetrievalLeg.DENSE, rank=1)])
    with pytest.raises(psycopg.errors.UniqueViolation):
        pg_store.save_retrieval_hits([_hit(hid="h2", leg=RetrievalLeg.DENSE, rank=2)])
