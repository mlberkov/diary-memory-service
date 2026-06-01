"""Storage-backend read-access tests for ``get_source_message`` (Slice 8.1.2 / D-089).

``get_source_message`` carries a mandatory keyword-only ``community_id`` and
filters its own ``source_messages.community_id`` column (the analog of 8.1.1's
``get_event_chunk``). These tests run across every backend from one parametrized
fixture so the fail-closed behavior cannot drift by backend (mock / sqlite /
postgres). Round-trip / idempotency coverage stays in
``test_sqlite_store.py`` and ``test_postgres_store.py``; this file pins the
community-scoping contract.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from memory_rag.core.domain.models import SourceMessage
from memory_rag.core.routing import RouteKind
from memory_rag.storage.mock import MockDomainStore
from memory_rag.storage.repository import DomainRepository
from memory_rag.storage.sqlite import SqliteDomainStore

PG_DSN = os.environ.get("MEMORY_RAG_PG_TEST_DSN")


def _now() -> datetime:
    return datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC)


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


@pytest.fixture(params=["mock", "sqlite"] + (["postgres"] if PG_DSN else []))
def scoped_store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[DomainRepository]:
    if request.param == "mock":
        yield MockDomainStore()
    elif request.param == "sqlite":
        yield SqliteDomainStore(str(tmp_path / "scoped.db"))
    else:
        import psycopg

        from memory_rag.storage.postgres import PostgresDomainStore

        assert PG_DSN is not None
        with psycopg.connect(PG_DSN, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("TRUNCATE event_chunks, notes, source_messages RESTART IDENTITY CASCADE")
        s = PostgresDomainStore(PG_DSN)
        try:
            yield s
        finally:
            s.close()


def test_get_source_message_rejects_empty_community_id(scoped_store: DomainRepository) -> None:
    scoped_store.save_source_message(_source("s1"))
    with pytest.raises(ValueError, match="community_id is required"):
        scoped_store.get_source_message("s1", community_id="")


def test_get_source_message_cross_community_reads_as_none(
    scoped_store: DomainRepository,
) -> None:
    scoped_store.save_source_message(_source("s1", community_id="fam-A"))
    assert scoped_store.get_source_message("s1", community_id="fam-A") is not None
    # Same source_message_id, different community: no leak.
    assert scoped_store.get_source_message("s1", community_id="fam-B") is None


def test_get_source_message_missing_id_reads_as_none(scoped_store: DomainRepository) -> None:
    assert scoped_store.get_source_message("no-such-source", community_id="fam-A") is None
