"""Storage-backend tests for the rewrite-trace seam (RC-3, D-108).

Covers ``save_chat_query_rewrite`` / ``get_chat_query_rewrite_for_decision``
across the three backends (mock, sqlite, postgres). The rewrite row is
ingest-shaped, not retrieval-shaped, so SQLite implements it for real
(the D-022 / D-025 retrieval-only restriction does not apply). At most
one rewrite row exists per decision.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from memory_rag.core.chat.models import ChatQueryRewrite, ChatRoute, ChatRouteDecision
from memory_rag.storage.mock import MockDomainStore
from memory_rag.storage.sqlite import SqliteDomainStore

PG_DSN = os.environ.get("MEMORY_RAG_PG_TEST_DSN")


def _now() -> datetime:
    return datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)


def _decision(*, did: str = "d1", community_id: str = "fam-A") -> ChatRouteDecision:
    return ChatRouteDecision(
        decision_id=did,
        community_id=community_id,
        question_text="what games suit him now",
        requested_route=ChatRoute.NOTES_PLUS_MODEL,
        effective_route=ChatRoute.NOTES_PLUS_MODEL,
        classifier_model_name="mock",
        classifier_raw_output='{"route": "notes_plus_model"}',
        classifier_latency_ms=0,
        query_id=None,
        created_at=_now(),
    )


def _rewrite(
    *,
    rid: str = "r1",
    decision_id: str = "d1",
    community_id: str = "fam-A",
    rewritten_query: str | None = "toddler games",
    date_start: date | None = date(2026, 5, 1),
    date_end: date | None = date(2026, 5, 31),
    raw_output: str = '{"retrieval_query": "toddler games"}',
) -> ChatQueryRewrite:
    return ChatQueryRewrite(
        rewrite_id=rid,
        decision_id=decision_id,
        community_id=community_id,
        rewritten_query=rewritten_query,
        date_start=date_start,
        date_end=date_end,
        subject_scope=None,
        rewriter_model_name="mock",
        rewriter_raw_output=raw_output,
        rewriter_latency_ms=0,
        created_at=_now(),
    )


# ---------------------------------------------------------------------------
# MockDomainStore
# ---------------------------------------------------------------------------


def test_mock_save_and_get_rewrite_round_trip() -> None:
    store = MockDomainStore()
    store.save_chat_route_decision(_decision())
    store.save_chat_query_rewrite(_rewrite())
    fetched = store.get_chat_query_rewrite_for_decision("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.rewritten_query == "toddler games"
    assert fetched.date_start == date(2026, 5, 1)
    assert fetched.date_end == date(2026, 5, 31)
    assert fetched.subject_scope is None
    assert fetched.rewriter_model_name == "mock"


def test_mock_degraded_rewrite_round_trip() -> None:
    """``rewritten_query=None`` + empty raw output is the no-usable-rewrite
    shape (rewriter unavailable / no rewriter wired)."""
    store = MockDomainStore()
    store.save_chat_route_decision(_decision())
    store.save_chat_query_rewrite(
        _rewrite(rewritten_query=None, date_start=None, date_end=None, raw_output="")
    )
    fetched = store.get_chat_query_rewrite_for_decision("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.rewritten_query is None
    assert fetched.date_start is None
    assert fetched.date_end is None
    assert fetched.rewriter_raw_output == ""


def test_mock_get_rewrite_missing_returns_none() -> None:
    store = MockDomainStore()
    assert store.get_chat_query_rewrite_for_decision("missing", community_id="fam-A") is None


def test_mock_get_rewrite_requires_community_id() -> None:
    store = MockDomainStore()
    store.save_chat_route_decision(_decision())
    store.save_chat_query_rewrite(_rewrite())
    with pytest.raises(ValueError):
        store.get_chat_query_rewrite_for_decision("d1", community_id="")


def test_mock_get_rewrite_fails_closed_across_communities() -> None:
    store = MockDomainStore()
    store.save_chat_route_decision(_decision())
    store.save_chat_query_rewrite(_rewrite())
    assert store.get_chat_query_rewrite_for_decision("d1", community_id="fam-B") is None


def test_mock_second_rewrite_for_a_decision_raises() -> None:
    store = MockDomainStore()
    store.save_chat_route_decision(_decision())
    store.save_chat_query_rewrite(_rewrite(rid="r1"))
    with pytest.raises(ValueError):
        store.save_chat_query_rewrite(_rewrite(rid="r2"))


def test_mock_rewrite_for_an_unknown_decision_raises() -> None:
    store = MockDomainStore()
    with pytest.raises(ValueError):
        store.save_chat_query_rewrite(_rewrite(decision_id="missing"))


# ---------------------------------------------------------------------------
# SqliteDomainStore
# ---------------------------------------------------------------------------


def _sqlite_store(tmp_path: Path) -> SqliteDomainStore:
    return SqliteDomainStore(str(tmp_path / "diary.db"))


def test_sqlite_save_and_get_rewrite_round_trip(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_chat_route_decision(_decision())
    store.save_chat_query_rewrite(_rewrite())
    fetched = store.get_chat_query_rewrite_for_decision("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.rewritten_query == "toddler games"
    assert fetched.date_start == date(2026, 5, 1)
    assert fetched.date_end == date(2026, 5, 31)
    assert fetched.subject_scope is None
    assert fetched.created_at == _now()


def test_sqlite_degraded_rewrite_round_trip(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_chat_route_decision(_decision())
    store.save_chat_query_rewrite(
        _rewrite(rewritten_query=None, date_start=None, date_end=None, raw_output="")
    )
    fetched = store.get_chat_query_rewrite_for_decision("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.rewritten_query is None
    assert fetched.date_start is None
    assert fetched.date_end is None


def test_sqlite_get_rewrite_requires_community_id(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_chat_route_decision(_decision())
    store.save_chat_query_rewrite(_rewrite())
    with pytest.raises(ValueError):
        store.get_chat_query_rewrite_for_decision("d1", community_id="")


def test_sqlite_get_rewrite_fails_closed_across_communities(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_chat_route_decision(_decision())
    store.save_chat_query_rewrite(_rewrite())
    assert store.get_chat_query_rewrite_for_decision("d1", community_id="fam-B") is None


def test_sqlite_second_rewrite_for_a_decision_raises(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_chat_route_decision(_decision())
    store.save_chat_query_rewrite(_rewrite(rid="r1"))
    with pytest.raises(sqlite3.IntegrityError):
        store.save_chat_query_rewrite(_rewrite(rid="r2"))


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
            "TRUNCATE chat_query_rewrites, chat_route_decisions, retrieval_hits, "
            "queries, embedding_records, event_chunks, notes, source_messages "
            "RESTART IDENTITY CASCADE"
        )


@pytest.fixture
def pg_store() -> Iterator[PostgresDomainStore]:
    assert PG_DSN is not None
    s = PostgresDomainStore(PG_DSN)
    try:
        _truncate(PG_DSN)
        yield s
    finally:
        s.close()


@pgmark
def test_pg_save_and_get_rewrite_round_trip(pg_store: PostgresDomainStore) -> None:
    pg_store.save_chat_route_decision(_decision())
    pg_store.save_chat_query_rewrite(_rewrite())
    fetched = pg_store.get_chat_query_rewrite_for_decision("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.rewritten_query == "toddler games"
    assert fetched.date_start == date(2026, 5, 1)
    assert fetched.date_end == date(2026, 5, 31)
    assert fetched.subject_scope is None


@pgmark
def test_pg_degraded_rewrite_round_trip(pg_store: PostgresDomainStore) -> None:
    pg_store.save_chat_route_decision(_decision())
    pg_store.save_chat_query_rewrite(
        _rewrite(rewritten_query=None, date_start=None, date_end=None, raw_output="")
    )
    fetched = pg_store.get_chat_query_rewrite_for_decision("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.rewritten_query is None
    assert fetched.date_start is None
    assert fetched.date_end is None


@pgmark
def test_pg_get_rewrite_requires_community_id(pg_store: PostgresDomainStore) -> None:
    pg_store.save_chat_route_decision(_decision())
    pg_store.save_chat_query_rewrite(_rewrite())
    with pytest.raises(ValueError):
        pg_store.get_chat_query_rewrite_for_decision("d1", community_id="")


@pgmark
def test_pg_get_rewrite_fails_closed_across_communities(pg_store: PostgresDomainStore) -> None:
    pg_store.save_chat_route_decision(_decision())
    pg_store.save_chat_query_rewrite(_rewrite())
    assert pg_store.get_chat_query_rewrite_for_decision("d1", community_id="fam-B") is None


@pgmark
def test_pg_rewrite_requires_an_existing_decision(pg_store: PostgresDomainStore) -> None:
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        pg_store.save_chat_query_rewrite(_rewrite(decision_id="missing"))


@pgmark
def test_pg_second_rewrite_for_a_decision_raises(pg_store: PostgresDomainStore) -> None:
    pg_store.save_chat_route_decision(_decision())
    pg_store.save_chat_query_rewrite(_rewrite(rid="r1"))
    with pytest.raises(psycopg.errors.UniqueViolation):
        pg_store.save_chat_query_rewrite(_rewrite(rid="r2"))
