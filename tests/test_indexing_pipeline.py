"""Cross-backend round-trip tests for embedding persistence (D-024).

The mock and SQLite backends run unconditionally. The Postgres backend
runs only when ``DIARY_RAG_PG_TEST_DSN`` is set (matches the existing
``test_postgres_store.py`` gating). Each backend must:

- Accept a list of ``EmbeddingRecord`` and dedupe by ``(chunk_id, model_name)``.
- Count embedding rows per source.
- Transition ``embedding_status`` on a target chunk to ``ready`` / ``failed``
  and surface the new status in subsequent reads.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from diary_rag.core.domain.models import EventChunk, Note, SourceMessage
from diary_rag.core.embeddings.models import EmbeddingRecord, EmbeddingStatus
from diary_rag.core.routing import RouteKind
from diary_rag.storage.mock import MockDomainStore
from diary_rag.storage.repository import DomainRepository
from diary_rag.storage.sqlite import SqliteDomainStore

PG_DSN = os.environ.get("DIARY_RAG_PG_TEST_DSN")


def _now() -> datetime:
    return datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)


def _source(sid: str = "s1") -> SourceMessage:
    return SourceMessage(
        source_message_id=sid,
        family_id="fam-A",
        author_user_id="u1",
        external_chat_id="fam-A",
        external_user_id="u1",
        external_message_id=sid,
        edit_seq=0,
        raw_text="2026-05-11\nWalked the dog",
        detected_route=RouteKind.NOTE,
        created_at=_now(),
    )


def _note(eid: str = "e1", sid: str = "s1") -> Note:
    return Note(
        note_id=eid,
        source_message_id=sid,
        family_id="fam-A",
        author_user_id="u1",
        note_date=date(2026, 5, 11),
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
        note_date=date(2026, 5, 11),
        event_index=idx,
        chunk_text="Walked the dog",
        created_at=_now(),
    )


def _record(rid: str, cid: str, sid: str = "s1", dim: int = 3072) -> EmbeddingRecord:
    return EmbeddingRecord(
        embedding_record_id=rid,
        chunk_id=cid,
        source_message_id=sid,
        family_id="fam-A",
        model_name="mock",
        dimension=dim,
        embedding=[0.0] * dim,
        created_at=_now(),
    )


@pytest.fixture(params=["mock", "sqlite"] + (["postgres"] if PG_DSN else []))
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[DomainRepository]:
    if request.param == "mock":
        yield MockDomainStore()
    elif request.param == "sqlite":
        yield SqliteDomainStore(str(tmp_path / "indexing.db"))
    else:
        import psycopg

        from diary_rag.storage.postgres import PostgresDomainStore

        assert PG_DSN is not None
        with psycopg.connect(PG_DSN, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                "TRUNCATE embedding_records, event_chunks, notes, source_messages "
                "RESTART IDENTITY CASCADE"
            )
        s = PostgresDomainStore(PG_DSN)
        try:
            yield s
        finally:
            s.close()


def _seed_chunk(store: DomainRepository, cid: str = "c1") -> None:
    store.save_source_message(_source())
    store.save_note(_note())
    store.save_event_chunks([_chunk(cid=cid)])


def test_save_embedding_records_round_trip(store: DomainRepository) -> None:
    _seed_chunk(store)
    store.save_embedding_records([_record("r1", "c1")])
    assert store.count_embedding_records_for_source("s1") == 1


def test_count_embedding_records_for_unknown_source_is_zero(store: DomainRepository) -> None:
    assert store.count_embedding_records_for_source("nope") == 0


def test_set_chunk_embedding_status_ready(store: DomainRepository) -> None:
    _seed_chunk(store)
    store.set_chunk_embedding_status("c1", EmbeddingStatus.READY)

    chunk = store.get_event_chunk("c1")
    assert chunk is not None
    assert chunk.embedding_status is EmbeddingStatus.READY


def test_set_chunk_embedding_status_failed(store: DomainRepository) -> None:
    _seed_chunk(store)
    store.set_chunk_embedding_status("c1", EmbeddingStatus.FAILED)

    chunk = store.get_event_chunk("c1")
    assert chunk is not None
    assert chunk.embedding_status is EmbeddingStatus.FAILED


def test_set_chunk_embedding_status_unknown_chunk_raises(store: DomainRepository) -> None:
    with pytest.raises(KeyError):
        store.set_chunk_embedding_status("nope", EmbeddingStatus.READY)


def test_freshly_saved_chunk_is_pending(store: DomainRepository) -> None:
    _seed_chunk(store)
    chunk = store.get_event_chunk("c1")
    assert chunk is not None
    assert chunk.embedding_status is EmbeddingStatus.PENDING


def test_get_event_chunk_missing_returns_none(store: DomainRepository) -> None:
    assert store.get_event_chunk("nope") is None


def test_duplicate_embedding_for_same_chunk_and_model_raises(store: DomainRepository) -> None:
    _seed_chunk(store)
    store.save_embedding_records([_record("r1", "c1")])
    with pytest.raises(Exception, match=r".*"):
        store.save_embedding_records([_record("r2", "c1")])
