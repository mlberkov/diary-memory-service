"""Storage-backend tests for the answer-trace seam (Slice 4.3a, D-034).

Covers ``save_answer_trace`` / ``get_answer_trace_for_query`` across the
three backends (mock, sqlite, postgres). Mirrors the structure of
``test_storage_query_traces.py`` (Slice 3.5 / D-032).
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from diary_rag.core.domain.models import (
    AnswerTrace,
    EventChunk,
    FallbackMode,
    Note,
    Query,
    SourceMessage,
)
from diary_rag.core.routing import RouteKind
from diary_rag.storage.mock import MockDomainStore
from diary_rag.storage.sqlite import SqliteDomainStore

PG_DSN = os.environ.get("DIARY_RAG_PG_TEST_DSN")


def _now() -> datetime:
    return datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC)


def _query(*, qid: str = "q1", fallback: FallbackMode = FallbackMode.NONE) -> Query:
    return Query(
        query_id=qid,
        family_id="fam-A",
        query_text="book",
        model_name="mock",
        fallback=fallback,
        created_at=_now(),
    )


def _trace(
    *,
    aid: str = "a1",
    qid: str = "q1",
    context_chunk_ids: tuple[str, ...] = ("c1",),
    answer_text: str = "Mock answer.",
    fallback_mode: FallbackMode = FallbackMode.NONE,
    token_counts: dict[str, int] | None = None,
    latency_ms: int = 0,
) -> AnswerTrace:
    return AnswerTrace(
        answer_trace_id=aid,
        query_id=qid,
        prompt_version="v1",
        context_chunk_ids=context_chunk_ids,
        answer_text=answer_text,
        fallback_mode=fallback_mode,
        model_name="mock",
        token_counts=token_counts if token_counts is not None else {"prompt": 10, "completion": 5},
        latency_ms=latency_ms,
        created_at=_now(),
    )


def _source(sid: str = "s1") -> SourceMessage:
    return SourceMessage(
        source_message_id=sid,
        family_id="fam-A",
        author_user_id="u1",
        external_chat_id="fam-A",
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
        family_id="fam-A",
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
        family_id="fam-A",
        author_user_id="u1",
        note_date=date(2026, 5, 9),
        event_index=idx,
        chunk_text="Walked the dog",
        created_at=_now(),
    )


# ---------------------------------------------------------------------------
# MockDomainStore
# ---------------------------------------------------------------------------


def test_mock_save_and_get_answer_trace_round_trip() -> None:
    store = MockDomainStore()
    store.save_query(_query())
    trace = _trace(latency_ms=42, token_counts={"prompt": 100, "completion": 25})
    store.save_answer_trace(trace)
    fetched = store.get_answer_trace_for_query("q1")
    assert fetched == trace
    assert store.len_answer_traces() == 1


def test_mock_get_answer_trace_missing_returns_none() -> None:
    store = MockDomainStore()
    assert store.get_answer_trace_for_query("missing") is None


def test_mock_save_answer_trace_rejects_duplicate_query_id() -> None:
    store = MockDomainStore()
    store.save_query(_query())
    store.save_answer_trace(_trace(aid="a1"))
    with pytest.raises(ValueError):
        store.save_answer_trace(_trace(aid="a2"))


def test_mock_save_answer_trace_with_empty_context_chunk_ids() -> None:
    store = MockDomainStore()
    store.save_query(_query(fallback=FallbackMode.NO_EVIDENCE))
    trace = _trace(
        context_chunk_ids=(),
        answer_text="",
        fallback_mode=FallbackMode.NO_EVIDENCE,
        token_counts={},
        latency_ms=0,
    )
    store.save_answer_trace(trace)
    fetched = store.get_answer_trace_for_query("q1")
    assert fetched is not None
    assert fetched.context_chunk_ids == ()
    assert fetched.answer_text == ""
    assert fetched.fallback_mode is FallbackMode.NO_EVIDENCE
    assert fetched.token_counts == {}
    assert fetched.latency_ms == 0


_NEW_FALLBACK_MODES = [
    FallbackMode.WEAK_EVIDENCE,
    FallbackMode.AMBIGUOUS,
    FallbackMode.PROVIDER_UNAVAILABLE,
    FallbackMode.PARSE_FAILURE,
]


@pytest.mark.parametrize("mode", _NEW_FALLBACK_MODES)
def test_mock_round_trips_new_fallback_modes(mode: FallbackMode) -> None:
    """Slice 4.3b: each new FallbackMode round-trips through the mock store."""
    store = MockDomainStore()
    store.save_query(_query(fallback=mode))
    trace = _trace(fallback_mode=mode, latency_ms=11, token_counts={"prompt": 3})
    store.save_answer_trace(trace)
    fetched = store.get_answer_trace_for_query("q1")
    assert fetched is not None
    assert fetched.fallback_mode is mode


# ---------------------------------------------------------------------------
# SqliteDomainStore
# ---------------------------------------------------------------------------


def _sqlite_store(tmp_path: Path) -> SqliteDomainStore:
    store = SqliteDomainStore(str(tmp_path / "diary.db"))
    store.save_source_message(_source())
    store.save_note(_note())
    store.save_event_chunks([_chunk("c1", idx=0)])
    return store


def test_sqlite_save_and_get_answer_trace_round_trip(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_query(_query())
    trace = _trace(latency_ms=42, token_counts={"prompt": 100, "completion": 25})
    store.save_answer_trace(trace)
    fetched = store.get_answer_trace_for_query("q1")
    assert fetched == trace


def test_sqlite_get_answer_trace_missing_returns_none(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    assert store.get_answer_trace_for_query("missing") is None


def test_sqlite_save_answer_trace_rejects_duplicate_query_id(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_query(_query())
    store.save_answer_trace(_trace(aid="a1"))
    with pytest.raises(sqlite3.IntegrityError):
        store.save_answer_trace(_trace(aid="a2"))


def test_sqlite_save_answer_trace_with_empty_context_chunk_ids(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_query(_query(fallback=FallbackMode.NO_EVIDENCE))
    trace = _trace(
        context_chunk_ids=(),
        answer_text="",
        fallback_mode=FallbackMode.NO_EVIDENCE,
        token_counts={},
        latency_ms=0,
    )
    store.save_answer_trace(trace)
    fetched = store.get_answer_trace_for_query("q1")
    assert fetched is not None
    assert fetched.context_chunk_ids == ()
    assert fetched.token_counts == {}


@pytest.mark.parametrize("mode", _NEW_FALLBACK_MODES)
def test_sqlite_round_trips_new_fallback_modes(tmp_path: Path, mode: FallbackMode) -> None:
    """Slice 4.3b: the widened CHECK admits each new mode on sqlite."""
    store = _sqlite_store(tmp_path)
    store.save_query(_query(fallback=mode))
    trace = _trace(fallback_mode=mode, latency_ms=11, token_counts={"prompt": 3})
    store.save_answer_trace(trace)
    fetched = store.get_answer_trace_for_query("q1")
    assert fetched is not None
    assert fetched.fallback_mode is mode


# ---------------------------------------------------------------------------
# PostgresDomainStore
# ---------------------------------------------------------------------------


pgmark = pytest.mark.skipif(
    PG_DSN is None,
    reason="DIARY_RAG_PG_TEST_DSN not set; Postgres integration tests skipped.",
)


if PG_DSN is not None:
    import psycopg
    from psycopg.types.json import Jsonb

    from diary_rag.storage.postgres import PostgresDomainStore


def _truncate(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE answer_traces, retrieval_hits, queries, embedding_records, "
            "event_chunks, notes, source_messages "
            "RESTART IDENTITY CASCADE"
        )


@pytest.fixture
def pg_store() -> Iterator[PostgresDomainStore]:
    assert PG_DSN is not None
    s = PostgresDomainStore(PG_DSN)
    try:
        _truncate(PG_DSN)
        s.save_source_message(_source())
        s.save_note(_note())
        s.save_event_chunks([_chunk("c1", idx=0)])
        yield s
    finally:
        s.close()


@pgmark
def test_pg_save_and_get_answer_trace_round_trip(pg_store: PostgresDomainStore) -> None:
    pg_store.save_query(_query())
    trace = _trace(latency_ms=42, token_counts={"prompt": 100, "completion": 25})
    pg_store.save_answer_trace(trace)
    fetched = pg_store.get_answer_trace_for_query("q1")
    assert fetched == trace


@pgmark
def test_pg_get_answer_trace_missing_returns_none(pg_store: PostgresDomainStore) -> None:
    assert pg_store.get_answer_trace_for_query("missing") is None


@pgmark
def test_pg_save_answer_trace_rejects_duplicate_query_id(pg_store: PostgresDomainStore) -> None:
    pg_store.save_query(_query())
    pg_store.save_answer_trace(_trace(aid="a1"))
    with pytest.raises(psycopg.errors.UniqueViolation):
        pg_store.save_answer_trace(_trace(aid="a2"))


@pgmark
def test_pg_save_answer_trace_with_empty_context_chunk_ids(
    pg_store: PostgresDomainStore,
) -> None:
    pg_store.save_query(_query(fallback=FallbackMode.NO_EVIDENCE))
    trace = _trace(
        context_chunk_ids=(),
        answer_text="",
        fallback_mode=FallbackMode.NO_EVIDENCE,
        token_counts={},
        latency_ms=0,
    )
    pg_store.save_answer_trace(trace)
    fetched = pg_store.get_answer_trace_for_query("q1")
    assert fetched is not None
    assert fetched.context_chunk_ids == ()
    assert fetched.token_counts == {}


@pgmark
@pytest.mark.parametrize("mode", _NEW_FALLBACK_MODES)
def test_pg_round_trips_new_fallback_modes(
    pg_store: PostgresDomainStore, mode: FallbackMode
) -> None:
    """Slice 4.3b: the widened CHECK admits each new mode on postgres."""
    pg_store.save_query(_query(fallback=mode))
    trace = _trace(fallback_mode=mode, latency_ms=11, token_counts={"prompt": 3})
    pg_store.save_answer_trace(trace)
    fetched = pg_store.get_answer_trace_for_query("q1")
    assert fetched is not None
    assert fetched.fallback_mode is mode


@pgmark
def test_pg_rejects_unknown_answer_trace_fallback_mode(
    pg_store: PostgresDomainStore,
) -> None:
    """The CHECK constraint still rejects values outside the FallbackMode set."""
    pg_store.save_query(_query())
    assert PG_DSN is not None
    with (
        psycopg.connect(PG_DSN, autocommit=True) as conn,
        conn.cursor() as cur,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        cur.execute(
            "INSERT INTO answer_traces (answer_trace_id, query_id, prompt_version, "
            "context_chunk_ids, answer_text, fallback_mode, model_name, token_counts, "
            "latency_ms, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                "a-bad",
                "q1",
                "v1",
                [],
                "",
                "not_a_real_mode",
                "mock",
                Jsonb({}),
                0,
                _now(),
            ),
        )
