"""Tests for the failed-embedding reconciliation discovery service (OP-3.1).

Covers ``ReconciliationService.discover_failed_chunks`` (read-only
discovery), ``render_report``, and the ``_main`` operator entrypoint.
The CLI targets Postgres in production; ``_main`` is exercised here with
an injected store so the wiring is covered offline under ``make check``.
A Postgres-gated case exercises the service against the real backend.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest

from memory_rag.core.domain.models import EventChunk, Note, SourceMessage
from memory_rag.core.embeddings.models import EmbeddingStatus
from memory_rag.core.routing import RouteKind
from memory_rag.services.reconciliation import (
    DEFAULT_DISCOVERY_LIMIT,
    FailedEmbeddingReport,
    ReconciliationService,
    _main,
    render_report,
)
from memory_rag.storage.mock import MockDomainStore

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


def _chunk(cid: str, status: EmbeddingStatus, created_at: datetime) -> EventChunk:
    return EventChunk(
        chunk_id=cid,
        note_id="n1",
        source_message_id="s1",
        community_id="fam-A",
        author_user_id="u1",
        note_date=_NOTE_DATE,
        event_index=0,
        chunk_text="Walked the dog",
        created_at=created_at,
        embedding_status=status,
    )


def _seeded_mock_store() -> MockDomainStore:
    store = MockDomainStore()
    store.save_source_message(_source("s1", "fam-A"))
    store.save_note(_note("n1", "s1", "fam-A"))
    store.save_event_chunks(
        [
            _chunk("c-new", EmbeddingStatus.FAILED, _at(12)),
            _chunk("c-old", EmbeddingStatus.FAILED, _at(10)),
            _chunk("c-ready", EmbeddingStatus.READY, _at(11)),
        ]
    )
    return store


# ---------------------------------------------------------------------------
# ReconciliationService.discover_failed_chunks
# ---------------------------------------------------------------------------


def test_discover_returns_failed_chunks_oldest_first() -> None:
    report = ReconciliationService(_seeded_mock_store()).discover_failed_chunks("fam-A")
    assert isinstance(report, FailedEmbeddingReport)
    assert report.community_id == "fam-A"
    assert [c.chunk_id for c in report.chunks] == ["c-old", "c-new"]
    assert report.count == 2


def test_discover_empty_community_reports_zero() -> None:
    report = ReconciliationService(_seeded_mock_store()).discover_failed_chunks("fam-none")
    assert report.chunks == ()
    assert report.count == 0


def test_discover_respects_limit() -> None:
    report = ReconciliationService(_seeded_mock_store()).discover_failed_chunks("fam-A", limit=1)
    assert [c.chunk_id for c in report.chunks] == ["c-old"]
    assert report.count == 1


def test_discover_is_read_only() -> None:
    """Discovery transitions no status and adds/removes no chunk."""
    store = _seeded_mock_store()
    ReconciliationService(store).discover_failed_chunks("fam-A")
    statuses = {}
    for cid in ("c-old", "c-new", "c-ready"):
        chunk = store.get_event_chunk(cid)
        assert chunk is not None
        statuses[cid] = chunk.embedding_status
    assert statuses["c-old"] is EmbeddingStatus.FAILED
    assert statuses["c-new"] is EmbeddingStatus.FAILED
    assert statuses["c-ready"] is EmbeddingStatus.READY
    assert store.len_chunks() == 3


# ---------------------------------------------------------------------------
# render_report
# ---------------------------------------------------------------------------


def test_render_report_lists_each_failed_chunk() -> None:
    report = ReconciliationService(_seeded_mock_store()).discover_failed_chunks("fam-A")
    text = render_report(report)
    assert "community_id=fam-A failed_chunks=2" in text
    assert "chunk_id=c-old" in text
    assert "chunk_id=c-new" in text
    assert text.count("chunk_id=") == 2


def test_render_report_empty_result() -> None:
    text = render_report(FailedEmbeddingReport(community_id="fam-A", chunks=()))
    assert "failed_chunks=0" in text
    assert "No failed-embedding chunks." in text


# ---------------------------------------------------------------------------
# _main operator entrypoint
# ---------------------------------------------------------------------------


def test_main_requires_community() -> None:
    """`--community` is mandatory; argparse exits before any store is built."""
    with pytest.raises(SystemExit):
        _main(["--limit", "5"])


class _ClosableMockStore(MockDomainStore):
    """MockDomainStore with the `close()` the CLI calls on a Postgres store."""

    def close(self) -> None:  # pragma: no cover - trivial
        pass


def test_main_lists_failed_chunks_with_injected_store(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`_main` wires parse -> discover -> render -> print with a stand-in store."""
    store = _ClosableMockStore()
    store.save_source_message(_source("s1", "fam-A"))
    store.save_note(_note("n1", "s1", "fam-A"))
    store.save_event_chunks([_chunk("c-old", EmbeddingStatus.FAILED, _at(10))])

    class _FakeSettings:
        def postgres_dsn(self) -> str:
            return "postgresql://unused/in-this-test"

    monkeypatch.setattr("memory_rag.config.Settings", _FakeSettings)
    monkeypatch.setattr("memory_rag.storage.postgres.PostgresDomainStore", lambda _dsn: store)

    exit_code = _main(["--community", "fam-A"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "community_id=fam-A failed_chunks=1" in out
    assert "chunk_id=c-old" in out


def test_default_discovery_limit_is_bounded() -> None:
    assert isinstance(DEFAULT_DISCOVERY_LIMIT, int)
    assert DEFAULT_DISCOVERY_LIMIT > 0


# ---------------------------------------------------------------------------
# PostgresDomainStore (gated)
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
def test_pg_discover_failed_chunks(pg_store: PostgresDomainStore) -> None:
    pg_store.save_source_message(_source("s1", "fam-A"))
    pg_store.save_note(_note("n1", "s1", "fam-A"))
    pg_store.save_event_chunks(
        [
            _chunk("c-new", EmbeddingStatus.FAILED, _at(12)),
            _chunk("c-old", EmbeddingStatus.FAILED, _at(10)),
            _chunk("c-ready", EmbeddingStatus.READY, _at(11)),
        ]
    )
    report = ReconciliationService(pg_store).discover_failed_chunks("fam-A")
    assert [c.chunk_id for c in report.chunks] == ["c-old", "c-new"]
    assert report.count == 2
    assert "chunk_id=c-old" in render_report(report)
