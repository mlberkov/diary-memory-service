"""Storage-backend tests for ``DomainRepository.list_recent_drafts`` (D-030)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from diary_rag.core.domain.models import SourceMessage
from diary_rag.core.routing import RouteKind
from diary_rag.storage.mock import MockDomainStore
from diary_rag.storage.sqlite import SqliteDomainStore

PG_DSN = os.environ.get("DIARY_RAG_PG_TEST_DSN")


def _source(
    *,
    sid: str,
    community_id: str = "fam-A",
    msg_id: str,
    raw_text: str = "draft body",
    route: RouteKind = RouteKind.DRAFT,
    created_at: datetime,
) -> SourceMessage:
    return SourceMessage(
        source_message_id=sid,
        community_id=community_id,
        author_user_id="user-1",
        external_chat_id=community_id,
        external_user_id="user-1",
        external_message_id=msg_id,
        edit_seq=0,
        raw_text=raw_text,
        detected_route=route,
        created_at=created_at,
    )


# ---------------------------------------------------------------------------
# MockDomainStore parity tests
# ---------------------------------------------------------------------------


def test_mock_list_recent_drafts_returns_drafts_only() -> None:
    store = MockDomainStore()
    base = datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC)
    store.save_source_message(_source(sid="d", msg_id="1", route=RouteKind.DRAFT, created_at=base))
    store.save_source_message(_source(sid="n", msg_id="2", route=RouteKind.NOTE, created_at=base))

    rows = store.list_recent_drafts("fam-A", limit=10)
    assert [r.source_message_id for r in rows] == ["d"]


def test_mock_list_recent_drafts_is_family_scoped() -> None:
    store = MockDomainStore()
    base = datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC)
    store.save_source_message(_source(sid="a", community_id="fam-A", msg_id="1", created_at=base))
    store.save_source_message(_source(sid="b", community_id="fam-B", msg_id="2", created_at=base))

    rows = store.list_recent_drafts("fam-A", limit=10)
    assert [r.source_message_id for r in rows] == ["a"]


def test_mock_list_recent_drafts_orders_most_recent_first() -> None:
    store = MockDomainStore()
    base = datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC)
    store.save_source_message(_source(sid="old", msg_id="1", created_at=base))
    store.save_source_message(_source(sid="newer", msg_id="2", created_at=base.replace(hour=11)))
    store.save_source_message(_source(sid="newest", msg_id="3", created_at=base.replace(hour=12)))

    rows = store.list_recent_drafts("fam-A", limit=10)
    assert [r.source_message_id for r in rows] == ["newest", "newer", "old"]


def test_mock_list_recent_drafts_respects_limit() -> None:
    store = MockDomainStore()
    base = datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC)
    for i in range(5):
        store.save_source_message(
            _source(sid=f"d{i}", msg_id=str(i), created_at=base.replace(minute=i))
        )

    rows = store.list_recent_drafts("fam-A", limit=2)
    assert len(rows) == 2


def test_mock_list_recent_drafts_empty_when_no_drafts() -> None:
    store = MockDomainStore()
    assert store.list_recent_drafts("fam-A", limit=10) == []


def test_mock_list_recent_drafts_rejects_empty_community_id() -> None:
    store = MockDomainStore()
    with pytest.raises(ValueError):
        store.list_recent_drafts("", limit=10)


def test_mock_list_recent_drafts_rejects_zero_limit() -> None:
    store = MockDomainStore()
    with pytest.raises(ValueError):
        store.list_recent_drafts("fam-A", limit=0)


# ---------------------------------------------------------------------------
# SqliteDomainStore — NotImplementedError per D-022 / D-030 pattern
# ---------------------------------------------------------------------------


def test_sqlite_list_recent_drafts_raises_not_implemented(tmp_path: Path) -> None:
    store = SqliteDomainStore(str(tmp_path / "diary.db"))
    with pytest.raises(NotImplementedError):
        store.list_recent_drafts("fam-A", limit=5)


# ---------------------------------------------------------------------------
# PostgresDomainStore parity tests (skipped without DSN)
# ---------------------------------------------------------------------------


pgmark = pytest.mark.skipif(
    PG_DSN is None,
    reason="DIARY_RAG_PG_TEST_DSN not set; Postgres integration tests skipped.",
)


if PG_DSN is not None:
    from diary_rag.storage.postgres import PostgresDomainStore


def _truncate(dsn: str) -> None:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE event_chunks, notes, source_messages " "RESTART IDENTITY CASCADE")


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
def test_pg_list_recent_drafts_returns_drafts_only_most_recent_first(
    pg_store: PostgresDomainStore,
) -> None:
    base = datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC)
    pg_store.save_source_message(
        _source(sid="note", msg_id="1", route=RouteKind.NOTE, created_at=base)
    )
    pg_store.save_source_message(
        _source(sid="d-old", msg_id="2", route=RouteKind.DRAFT, created_at=base)
    )
    pg_store.save_source_message(
        _source(
            sid="d-new",
            msg_id="3",
            route=RouteKind.DRAFT,
            created_at=base.replace(hour=11),
        )
    )

    rows = pg_store.list_recent_drafts("fam-A", limit=10)
    assert [r.source_message_id for r in rows] == ["d-new", "d-old"]


@pgmark
def test_pg_list_recent_drafts_respects_family_scope_and_limit(
    pg_store: PostgresDomainStore,
) -> None:
    base = datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC)
    for i in range(3):
        pg_store.save_source_message(
            _source(
                sid=f"a{i}",
                community_id="fam-A",
                msg_id=f"a{i}",
                route=RouteKind.DRAFT,
                created_at=base.replace(minute=i),
            )
        )
    pg_store.save_source_message(
        _source(
            sid="other",
            community_id="fam-B",
            msg_id="z",
            route=RouteKind.DRAFT,
            created_at=base.replace(minute=10),
        )
    )

    rows = pg_store.list_recent_drafts("fam-A", limit=2)
    assert len(rows) == 2
    assert all(r.community_id == "fam-A" for r in rows)
