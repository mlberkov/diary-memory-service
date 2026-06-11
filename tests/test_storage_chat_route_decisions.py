"""Storage-backend tests for the routing-decision trace seam (RC-2, D-108).

Covers ``save_chat_route_decision`` / ``get_chat_route_decision`` across
the three backends (mock, sqlite, postgres). SQLite is a real
implementation here — the decision table is ingest-shaped, not
retrieval-shaped, so the D-022 / D-025 retrieval-only restriction does
not apply.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from memory_rag.core.chat.models import ChatRoute, ChatRouteDecision
from memory_rag.core.domain.models import FallbackMode, Query
from memory_rag.storage.mock import MockDomainStore
from memory_rag.storage.sqlite import SqliteDomainStore

PG_DSN = os.environ.get("MEMORY_RAG_PG_TEST_DSN")


def _now() -> datetime:
    return datetime(2026, 6, 11, 12, 0, 0, tzinfo=UTC)


def _decision(
    *,
    did: str = "d1",
    community_id: str = "fam-A",
    question: str = "what is phonemic awareness",
    requested: ChatRoute | None = ChatRoute.MODEL_ONLY,
    effective: ChatRoute = ChatRoute.MODEL_ONLY,
    raw_output: str = '{"route": "model_only"}',
    query_id: str | None = None,
) -> ChatRouteDecision:
    return ChatRouteDecision(
        decision_id=did,
        community_id=community_id,
        question_text=question,
        requested_route=requested,
        effective_route=effective,
        classifier_model_name="mock",
        classifier_raw_output=raw_output,
        classifier_latency_ms=0,
        query_id=query_id,
        created_at=_now(),
    )


def _query(*, qid: str = "q1", community_id: str = "fam-A") -> Query:
    return Query(
        query_id=qid,
        community_id=community_id,
        query_text="book",
        model_name="mock",
        fallback=FallbackMode.NONE,
        created_at=_now(),
        subject_scope=None,
    )


# ---------------------------------------------------------------------------
# MockDomainStore
# ---------------------------------------------------------------------------


def test_mock_save_and_get_decision_round_trip() -> None:
    store = MockDomainStore()
    store.save_chat_route_decision(_decision(did="d1"))
    fetched = store.get_chat_route_decision("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.requested_route is ChatRoute.MODEL_ONLY
    assert fetched.effective_route is ChatRoute.MODEL_ONLY
    assert fetched.classifier_raw_output == '{"route": "model_only"}'
    assert fetched.query_id is None


def test_mock_unclassified_decision_round_trip() -> None:
    """``requested_route=None`` + empty raw output is the no-usable-
    classification shape (classifier unavailable / empty question)."""
    store = MockDomainStore()
    store.save_chat_route_decision(
        _decision(did="d1", requested=None, effective=ChatRoute.NOTES_LOOKUP, raw_output="")
    )
    fetched = store.get_chat_route_decision("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.requested_route is None
    assert fetched.effective_route is ChatRoute.NOTES_LOOKUP
    assert fetched.classifier_raw_output == ""


def test_mock_decision_links_query_id() -> None:
    store = MockDomainStore()
    store.save_query(_query(qid="q1"))
    store.save_chat_route_decision(
        _decision(
            did="d1",
            requested=ChatRoute.NOTES_LOOKUP,
            effective=ChatRoute.NOTES_LOOKUP,
            query_id="q1",
        )
    )
    fetched = store.get_chat_route_decision("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.query_id == "q1"


def test_mock_get_decision_missing_returns_none() -> None:
    store = MockDomainStore()
    assert store.get_chat_route_decision("missing", community_id="fam-A") is None


def test_mock_get_decision_requires_community_id() -> None:
    store = MockDomainStore()
    store.save_chat_route_decision(_decision(did="d1"))
    with pytest.raises(ValueError):
        store.get_chat_route_decision("d1", community_id="")


def test_mock_get_decision_fails_closed_across_communities() -> None:
    store = MockDomainStore()
    store.save_chat_route_decision(_decision(did="d1", community_id="fam-A"))
    assert store.get_chat_route_decision("d1", community_id="fam-B") is None


def test_mock_duplicate_decision_id_raises() -> None:
    store = MockDomainStore()
    store.save_chat_route_decision(_decision(did="d1"))
    with pytest.raises(ValueError):
        store.save_chat_route_decision(_decision(did="d1"))


# ---------------------------------------------------------------------------
# SqliteDomainStore
# ---------------------------------------------------------------------------


def _sqlite_store(tmp_path: Path) -> SqliteDomainStore:
    return SqliteDomainStore(str(tmp_path / "diary.db"))


def test_sqlite_save_and_get_decision_round_trip(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_chat_route_decision(_decision(did="d1"))
    fetched = store.get_chat_route_decision("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.requested_route is ChatRoute.MODEL_ONLY
    assert fetched.effective_route is ChatRoute.MODEL_ONLY
    assert fetched.classifier_raw_output == '{"route": "model_only"}'
    assert fetched.created_at == _now()
    assert fetched.query_id is None


def test_sqlite_unclassified_decision_round_trip(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_chat_route_decision(
        _decision(did="d1", requested=None, effective=ChatRoute.NOTES_LOOKUP, raw_output="")
    )
    fetched = store.get_chat_route_decision("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.requested_route is None
    assert fetched.effective_route is ChatRoute.NOTES_LOOKUP


def test_sqlite_decision_links_query_id(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_query(_query(qid="q1"))
    store.save_chat_route_decision(
        _decision(
            did="d1",
            requested=ChatRoute.NOTES_LOOKUP,
            effective=ChatRoute.NOTES_LOOKUP,
            query_id="q1",
        )
    )
    fetched = store.get_chat_route_decision("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.query_id == "q1"


def test_sqlite_get_decision_requires_community_id(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_chat_route_decision(_decision(did="d1"))
    with pytest.raises(ValueError):
        store.get_chat_route_decision("d1", community_id="")


def test_sqlite_get_decision_fails_closed_across_communities(tmp_path: Path) -> None:
    store = _sqlite_store(tmp_path)
    store.save_chat_route_decision(_decision(did="d1", community_id="fam-A"))
    assert store.get_chat_route_decision("d1", community_id="fam-B") is None


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
            "TRUNCATE chat_route_decisions, retrieval_hits, queries, "
            "embedding_records, event_chunks, notes, source_messages "
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
def test_pg_save_and_get_decision_round_trip(pg_store: PostgresDomainStore) -> None:
    pg_store.save_chat_route_decision(_decision(did="d1"))
    fetched = pg_store.get_chat_route_decision("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.requested_route is ChatRoute.MODEL_ONLY
    assert fetched.effective_route is ChatRoute.MODEL_ONLY
    assert fetched.classifier_raw_output == '{"route": "model_only"}'
    assert fetched.query_id is None


@pgmark
def test_pg_unclassified_decision_round_trip(pg_store: PostgresDomainStore) -> None:
    pg_store.save_chat_route_decision(
        _decision(did="d1", requested=None, effective=ChatRoute.NOTES_LOOKUP, raw_output="")
    )
    fetched = pg_store.get_chat_route_decision("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.requested_route is None
    assert fetched.effective_route is ChatRoute.NOTES_LOOKUP


@pgmark
def test_pg_decision_links_query_id(pg_store: PostgresDomainStore) -> None:
    pg_store.save_query(_query(qid="q1"))
    pg_store.save_chat_route_decision(
        _decision(
            did="d1",
            requested=ChatRoute.NOTES_LOOKUP,
            effective=ChatRoute.NOTES_LOOKUP,
            query_id="q1",
        )
    )
    fetched = pg_store.get_chat_route_decision("d1", community_id="fam-A")
    assert fetched is not None
    assert fetched.query_id == "q1"


@pgmark
def test_pg_get_decision_requires_community_id(pg_store: PostgresDomainStore) -> None:
    pg_store.save_chat_route_decision(_decision(did="d1"))
    with pytest.raises(ValueError):
        pg_store.get_chat_route_decision("d1", community_id="")


@pgmark
def test_pg_get_decision_fails_closed_across_communities(pg_store: PostgresDomainStore) -> None:
    pg_store.save_chat_route_decision(_decision(did="d1", community_id="fam-A"))
    assert pg_store.get_chat_route_decision("d1", community_id="fam-B") is None
