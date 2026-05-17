"""Backend-parity tests for the failed-embedding discovery seam (OP-3.1).

Covers ``DomainRepository.list_failed_event_chunks`` across the three
backends (mock, sqlite, postgres). The method is the read-only discovery
query behind failed-embedding reconciliation: it returns chunks stuck at
``embedding_status='failed'`` for a community, oldest failure first.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from memory_rag.core.domain.models import EventChunk, Note, SourceMessage
from memory_rag.core.embeddings.models import EmbeddingStatus
from memory_rag.core.routing import RouteKind
from memory_rag.storage.mock import MockDomainStore
from memory_rag.storage.repository import DomainRepository
from memory_rag.storage.sqlite import SqliteDomainStore

PG_DSN = os.environ.get("MEMORY_RAG_PG_TEST_DSN")

_NOTE_DATE = date(2026, 5, 9)


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


def _note(nid: str, sid: str, community_id: str) -> Note:
    return Note(
        note_id=nid,
        source_message_id=sid,
        community_id=community_id,
        author_user_id="u1",
        note_date=_NOTE_DATE,
        note_text="Walked the dog",
        created_at=_at(12),
    )


def _chunk(
    *,
    cid: str,
    nid: str = "n1",
    sid: str = "s1",
    community_id: str = "fam-A",
    status: EmbeddingStatus = EmbeddingStatus.FAILED,
    created_at: datetime | None = None,
) -> EventChunk:
    return EventChunk(
        chunk_id=cid,
        note_id=nid,
        source_message_id=sid,
        community_id=community_id,
        author_user_id="u1",
        note_date=_NOTE_DATE,
        event_index=0,
        chunk_text="Walked the dog",
        created_at=created_at if created_at is not None else _at(12),
        embedding_status=status,
    )


# A shared fixture corpus exercised identically against every backend.
#
# fam-A: c-old (failed, 10:00), c-new (failed, 12:00), c-tie-b / c-tie-a
#        (failed, 11:00 — tie broken on chunk_id), c-ready (ready), c-pending.
# fam-B: c-other (failed) — must never leak into a fam-A query.
def _seed(store: DomainRepository) -> None:
    store.save_source_message(_source("s1", "fam-A"))
    store.save_source_message(_source("s2", "fam-B"))
    store.save_note(_note("n1", "s1", "fam-A"))
    store.save_note(_note("n2", "s2", "fam-B"))
    store.save_event_chunks(
        [
            _chunk(cid="c-new", created_at=_at(12)),
            _chunk(cid="c-old", created_at=_at(10)),
            _chunk(cid="c-tie-b", created_at=_at(11)),
            _chunk(cid="c-tie-a", created_at=_at(11)),
            _chunk(cid="c-ready", status=EmbeddingStatus.READY),
            _chunk(cid="c-pending", status=EmbeddingStatus.PENDING),
            _chunk(cid="c-other", nid="n2", sid="s2", community_id="fam-B"),
        ]
    )


# Expected fam-A failed chunks, oldest-first with chunk_id tie-break.
_EXPECTED_FAM_A = ["c-old", "c-tie-a", "c-tie-b", "c-new"]


def _assert_discovery(store: DomainRepository) -> None:
    """Shared assertions — every backend must satisfy them identically."""
    failed = store.list_failed_event_chunks("fam-A")
    # Only failed chunks, oldest-first, chunk_id tie-break, fam-B excluded.
    assert [c.chunk_id for c in failed] == _EXPECTED_FAM_A
    assert all(c.embedding_status is EmbeddingStatus.FAILED for c in failed)

    # limit caps the slice (still oldest-first).
    capped = store.list_failed_event_chunks("fam-A", limit=2)
    assert [c.chunk_id for c in capped] == ["c-old", "c-tie-a"]

    # limit=None is the same as omitting it.
    assert store.list_failed_event_chunks("fam-A", limit=None) == failed

    # A community with no failed chunks yields an empty list.
    assert store.list_failed_event_chunks("fam-empty") == []

    # Validation parity: empty community_id and negative limit both raise.
    with pytest.raises(ValueError):
        store.list_failed_event_chunks("")
    with pytest.raises(ValueError):
        store.list_failed_event_chunks("fam-A", limit=-1)


# ---------------------------------------------------------------------------
# MockDomainStore
# ---------------------------------------------------------------------------


def test_mock_list_failed_event_chunks() -> None:
    store = MockDomainStore()
    _seed(store)
    _assert_discovery(store)


# ---------------------------------------------------------------------------
# SqliteDomainStore
# ---------------------------------------------------------------------------


def test_sqlite_list_failed_event_chunks(tmp_path: Path) -> None:
    store = SqliteDomainStore(str(tmp_path / "diary.db"))
    _seed(store)
    _assert_discovery(store)


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
        yield s
    finally:
        s.close()


@pgmark
def test_pg_list_failed_event_chunks(pg_store: PostgresDomainStore) -> None:
    _seed(pg_store)
    _assert_discovery(pg_store)
