"""Storage-backend tests for the knowledge-search trace seam (RC-4, D-108).

Covers ``save_chat_knowledge_search`` /
``get_chat_knowledge_search_for_decision`` across the three backends
(mock, sqlite, postgres). The search row is ingest-shaped, not
retrieval-shaped, so SQLite implements it for real (the D-022 / D-025
retrieval-only restriction does not apply). At most one search row
exists per decision.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from memory_rag.core.chat.models import ChatKnowledgeSearch, ChatRoute, ChatRouteDecision
from memory_rag.storage.mock import MockDomainStore
from memory_rag.storage.sqlite import SqliteDomainStore

PG_DSN = os.environ.get("MEMORY_RAG_PG_TEST_DSN")


def _now() -> datetime:
    return datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)


def _decision(*, did: str = "d1", community_id: str = "fam-A") -> ChatRouteDecision:
    return ChatRouteDecision(
        decision_id=did,
        community_id=community_id,
        question_text="why does he refuse naps",
        requested_route=ChatRoute.NOTES_PLUS_KNOWLEDGE,
        effective_route=ChatRoute.NOTES_PLUS_KNOWLEDGE,
        classifier_model_name="mock",
        classifier_raw_output='{"route": "notes_plus_knowledge"}',
        classifier_latency_ms=0,
        query_id=None,
        created_at=_now(),
    )


def _search(
    *,
    sid: str = "s1",
    decision_id: str = "d1",
    community_id: str = "fam-A",
    outward_query: str = "2 year old nap refusal",
    result_count: int = 2,
    raw_output: str = '{"results": []}',
) -> ChatKnowledgeSearch:
    return ChatKnowledgeSearch(
        search_id=sid,
        decision_id=decision_id,
        community_id=community_id,
        outward_query=outward_query,
        outward_rewriter_model_name="mock",
        outward_rewriter_raw_output='{"search_query": "2 year old nap refusal"}',
        outward_rewriter_latency_ms=0,
        provider_name="mock",
        result_count=result_count,
        raw_output=raw_output,
        latency_ms=0,
        created_at=_now(),
    )


# ---------------------------------------------------------------------------
# MockDomainStore
# ---------------------------------------------------------------------------


def test_mock_save_and_get_search_round_trip() -> None:
    store = MockDomainStore()
    store.save_chat_route_decision(_decision())
    store.save_chat_knowledge_search(_search())
    fetched = store.get_chat_knowledge_search_for_decision("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.outward_query == "2 year old nap refusal"
    assert fetched.provider_name == "mock"
    assert fetched.result_count == 2


def test_mock_failed_search_round_trip() -> None:
    """``raw_output=""`` + ``result_count=0`` is the failed-search shape
    (D-035 truthful provenance applied to the search seam)."""
    store = MockDomainStore()
    store.save_chat_route_decision(_decision())
    store.save_chat_knowledge_search(_search(result_count=0, raw_output=""))
    fetched = store.get_chat_knowledge_search_for_decision("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.result_count == 0
    assert fetched.raw_output == ""


def test_mock_get_search_missing_returns_none() -> None:
    store = MockDomainStore()
    assert store.get_chat_knowledge_search_for_decision("missing", community_id="fam-A") is None


def test_mock_get_search_requires_community_id() -> None:
    store = MockDomainStore()
    store.save_chat_route_decision(_decision())
    store.save_chat_knowledge_search(_search())
    with pytest.raises(ValueError):
        store.get_chat_knowledge_search_for_decision("d1", community_id="")


def test_mock_get_search_fails_closed_across_communities() -> None:
    store = MockDomainStore()
    store.save_chat_route_decision(_decision())
    store.save_chat_knowledge_search(_search())
    assert store.get_chat_knowledge_search_for_decision("d1", community_id="fam-B") is None


def test_mock_second_search_for_a_decision_raises() -> None:
    store = MockDomainStore()
    store.save_chat_route_decision(_decision())
    store.save_chat_knowledge_search(_search(sid="s1"))
    with pytest.raises(ValueError):
        store.save_chat_knowledge_search(_search(sid="s2"))


def test_mock_search_for_an_unknown_decision_raises() -> None:
    store = MockDomainStore()
    with pytest.raises(ValueError):
        store.save_chat_knowledge_search(_search(decision_id="missing"))


# ---------------------------------------------------------------------------
# SqliteDomainStore
# ---------------------------------------------------------------------------


def _sqlite_store(tmp_path: Path) -> SqliteDomainStore:
    return SqliteDomainStore(str(tmp_path / "diary.db"))


def test_sqlite_save_and_get_search_round_trip(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_chat_route_decision(_decision())
    store.save_chat_knowledge_search(_search())
    fetched = store.get_chat_knowledge_search_for_decision("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.outward_query == "2 year old nap refusal"
    assert fetched.provider_name == "mock"
    assert fetched.created_at == _now()


def test_sqlite_failed_search_round_trip(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_chat_route_decision(_decision())
    store.save_chat_knowledge_search(_search(result_count=0, raw_output=""))
    fetched = store.get_chat_knowledge_search_for_decision("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.result_count == 0
    assert fetched.raw_output == ""


def test_sqlite_get_search_requires_community_id(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_chat_route_decision(_decision())
    store.save_chat_knowledge_search(_search())
    with pytest.raises(ValueError):
        store.get_chat_knowledge_search_for_decision("d1", community_id="")


def test_sqlite_get_search_fails_closed_across_communities(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_chat_route_decision(_decision())
    store.save_chat_knowledge_search(_search())
    assert store.get_chat_knowledge_search_for_decision("d1", community_id="fam-B") is None


def test_sqlite_second_search_for_a_decision_raises(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_chat_route_decision(_decision())
    store.save_chat_knowledge_search(_search(sid="s1"))
    with pytest.raises(sqlite3.IntegrityError):
        store.save_chat_knowledge_search(_search(sid="s2"))


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
            "TRUNCATE chat_knowledge_searches, chat_query_rewrites, chat_route_decisions, "
            "retrieval_hits, queries, embedding_records, event_chunks, notes, source_messages "
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
def test_pg_save_and_get_search_round_trip(pg_store: PostgresDomainStore) -> None:
    pg_store.save_chat_route_decision(_decision())
    pg_store.save_chat_knowledge_search(_search())
    fetched = pg_store.get_chat_knowledge_search_for_decision("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.outward_query == "2 year old nap refusal"
    assert fetched.provider_name == "mock"
    assert fetched.result_count == 2


@pgmark
def test_pg_failed_search_round_trip(pg_store: PostgresDomainStore) -> None:
    pg_store.save_chat_route_decision(_decision())
    pg_store.save_chat_knowledge_search(_search(result_count=0, raw_output=""))
    fetched = pg_store.get_chat_knowledge_search_for_decision("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.result_count == 0
    assert fetched.raw_output == ""


@pgmark
def test_pg_get_search_requires_community_id(pg_store: PostgresDomainStore) -> None:
    pg_store.save_chat_route_decision(_decision())
    pg_store.save_chat_knowledge_search(_search())
    with pytest.raises(ValueError):
        pg_store.get_chat_knowledge_search_for_decision("d1", community_id="")


@pgmark
def test_pg_get_search_fails_closed_across_communities(pg_store: PostgresDomainStore) -> None:
    pg_store.save_chat_route_decision(_decision())
    pg_store.save_chat_knowledge_search(_search())
    assert pg_store.get_chat_knowledge_search_for_decision("d1", community_id="fam-B") is None


@pgmark
def test_pg_search_requires_an_existing_decision(pg_store: PostgresDomainStore) -> None:
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        pg_store.save_chat_knowledge_search(_search(decision_id="missing"))


@pgmark
def test_pg_second_search_for_a_decision_raises(pg_store: PostgresDomainStore) -> None:
    pg_store.save_chat_route_decision(_decision())
    pg_store.save_chat_knowledge_search(_search(sid="s1"))
    with pytest.raises(psycopg.errors.UniqueViolation):
        pg_store.save_chat_knowledge_search(_search(sid="s2"))
