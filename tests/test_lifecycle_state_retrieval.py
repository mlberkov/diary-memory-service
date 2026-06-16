"""Lifecycle-state retrieval + persistence suite (ED-1 / D-114).

Pins the ED-1 half of the edit/delete contract: the revision lifecycle
state model ``active | superseded | tombstoned`` carried on Note / EventChunk
and the generalized active-state retrieval filter (R-4) — both retrieval legs
return only ``active`` chunks; ``superseded`` and ``tombstoned`` revisions are
excluded, regardless of ``embedding_status``.

ED-1 introduces no state-transition writer: nothing in production writes a
non-active state yet (``/edit`` supersession is ED-2; ``/delete`` tombstone is
ED-3). These tests construct non-active rows directly to exercise the column,
the CHECK constraint, and the retrieval predicate that ED-2/ED-3 will rely on.

Harness boundaries:

- Retrieval coverage (``store`` fixture) is parametrized over **mock +
  PG-gated postgres** (``MEMORY_RAG_PG_TEST_DSN``). sqlite is excluded — its
  retrieval legs raise ``NotImplementedError`` (D-022 / D-025).
- Persistence/round-trip coverage (``persist_store`` fixture) additionally
  includes **sqlite**, which runs against a *freshly created* sqlite database
  (a ``tmp_path_factory`` file) — sqlite has no migration runner, so only a
  fresh ``CREATE TABLE`` carries the new columns.
- The enum/CHECK drift guard pins the three allowed values across the
  ``LifecycleState`` enum and (when the PG leg runs) the PostgreSQL CHECK.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from memory_rag.adapters.embeddings import MockEmbeddingClient
from memory_rag.core.domain.models import (
    DateRange,
    EventChunk,
    LifecycleState,
    Note,
    SourceMessage,
)
from memory_rag.core.embeddings.models import EmbeddingRecord, EmbeddingStatus
from memory_rag.core.routing import RouteKind
from memory_rag.storage.mock import MockDomainStore
from memory_rag.storage.sqlite import SqliteDomainStore

if TYPE_CHECKING:
    from memory_rag.storage.postgres import PostgresDomainStore

PG_DSN = os.environ.get("MEMORY_RAG_PG_TEST_DSN")

_NOW = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)
_DATE = date(2026, 5, 11)


def _truncate(dsn: str) -> None:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE embedding_records, event_chunks, notes, source_messages "
            "RESTART IDENTITY CASCADE"
        )


@pytest.fixture(params=["mock"] + (["postgres"] if PG_DSN else []))
def store(request: pytest.FixtureRequest) -> Iterator[MockDomainStore | PostgresDomainStore]:
    """Retrieval-capable store: mock + PG-gated postgres."""
    if request.param == "mock":
        yield MockDomainStore()
    else:
        from memory_rag.storage.postgres import PostgresDomainStore

        assert PG_DSN is not None
        pg = PostgresDomainStore(PG_DSN)
        try:
            _truncate(PG_DSN)
            yield pg
        finally:
            pg.close()


@pytest.fixture(params=["mock", "sqlite"] + (["postgres"] if PG_DSN else []))
def persist_store(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[MockDomainStore | SqliteDomainStore | PostgresDomainStore]:
    """Round-trip store: mock + sqlite (fresh DB) + PG-gated postgres."""
    if request.param == "mock":
        yield MockDomainStore()
    elif request.param == "sqlite":
        # Fresh sqlite DB — only a new CREATE TABLE carries the ED-1 columns.
        path = tmp_path_factory.mktemp("ed1") / "lifecycle.db"
        yield SqliteDomainStore(str(path))
    else:
        from memory_rag.storage.postgres import PostgresDomainStore

        assert PG_DSN is not None
        pg = PostgresDomainStore(PG_DSN)
        try:
            _truncate(PG_DSN)
            yield pg
        finally:
            pg.close()


def _seed(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
    *,
    cid: str,
    text: str,
    community_id: str = "fam-A",
    lifecycle_state: LifecycleState = LifecycleState.ACTIVE,
    supersedes_chunk_id: str | None = None,
    supersedes_note_id: str | None = None,
    status: EmbeddingStatus = EmbeddingStatus.READY,
    embed_with: MockEmbeddingClient | None = None,
    note_date: date = _DATE,
    subject_id: str | None = None,
) -> EventChunk:
    """Seed one source -> note -> chunk (+ embedding) at the given lifecycle state."""
    sid = f"src-{cid}"
    eid = f"ent-{cid}"
    store.save_source_message(
        SourceMessage(
            source_message_id=sid,
            community_id=community_id,
            author_user_id="u1",
            external_chat_id=community_id,
            external_user_id="u1",
            external_message_id=sid,
            edit_seq=0,
            raw_text=text,
            detected_route=RouteKind.NOTE,
            created_at=_NOW,
        )
    )
    store.save_note(
        Note(
            note_id=eid,
            source_message_id=sid,
            community_id=community_id,
            author_user_id="u1",
            note_date=note_date,
            note_text=text,
            created_at=_NOW,
            subject_id=subject_id,
            lifecycle_state=lifecycle_state,
            supersedes_note_id=supersedes_note_id,
        )
    )
    chunk = EventChunk(
        chunk_id=cid,
        note_id=eid,
        source_message_id=sid,
        community_id=community_id,
        author_user_id="u1",
        note_date=note_date,
        event_index=0,
        chunk_text=text,
        created_at=_NOW,
        subject_id=subject_id,
        lifecycle_state=lifecycle_state,
        supersedes_chunk_id=supersedes_chunk_id,
    )
    store.save_event_chunks([chunk])
    if status is EmbeddingStatus.READY:
        client = embed_with or MockEmbeddingClient()
        store.save_embedding_records(
            [
                EmbeddingRecord(
                    embedding_record_id=str(uuid4()),
                    chunk_id=cid,
                    source_message_id=sid,
                    community_id=community_id,
                    model_name=client.model_name,
                    dimension=client.dimension,
                    embedding=client.embed([text])[0],
                    created_at=_NOW,
                )
            ]
        )
    store.set_chunk_embedding_status(cid, status)
    return chunk


# === Retrieval predicate (R-4 generalization) ================================


@pytest.mark.parametrize("inactive", [LifecycleState.SUPERSEDED, LifecycleState.TOMBSTONED])
def test_inactive_excluded_from_both_legs(
    store: MockDomainStore | PostgresDomainStore, inactive: LifecycleState
) -> None:
    """An ``active`` chunk is returned by both legs; a ``superseded`` /
    ``tombstoned`` sibling with identical text and a ready embedding is not."""
    client = MockEmbeddingClient()
    _seed(store, cid="c-active", text="Walked the dog", embed_with=client)
    _seed(
        store, cid="c-inactive", text="Walked the dog", embed_with=client, lifecycle_state=inactive
    )

    query = client.embed(["Walked the dog"])[0]
    dense = store.dense_candidates("fam-A", query, client.model_name, 10)
    sparse = store.sparse_candidates("fam-A", "dog", 10)

    assert [h.chunk_id for h in dense] == ["c-active"]
    assert [h.chunk_id for h in sparse] == ["c-active"]


def test_active_state_is_independent_of_embedding_status(
    store: MockDomainStore | PostgresDomainStore,
) -> None:
    """The sparse leg ranks any *active* chunk regardless of embedding state,
    but a superseded chunk is excluded even when its embedding is ``ready``."""
    client = MockEmbeddingClient()
    # active but never embedded -> sparse still ranks it (R-4 unchanged for that),
    _seed(store, cid="c-active-pending", text="book chapter", status=EmbeddingStatus.PENDING)
    # superseded but fully ready -> excluded from both legs by lifecycle alone.
    _seed(
        store,
        cid="c-super-ready",
        text="book chapter",
        embed_with=client,
        lifecycle_state=LifecycleState.SUPERSEDED,
    )

    sparse = store.sparse_candidates("fam-A", "book chapter", 10)
    assert [h.chunk_id for h in sparse] == ["c-active-pending"]


def test_active_state_composes_with_date_range_and_subject_scope(
    store: MockDomainStore | PostgresDomainStore,
) -> None:
    """The active-state filter conjoins with ``date_range`` + ``subject_scope``:
    only the active in-window same-subject chunk survives."""
    client = MockEmbeddingClient()
    # active, in window, subj-1 -> the only survivor.
    _seed(store, cid="c-keep", text="book chapter", embed_with=client, subject_id="subj-1")
    _seed(
        store,
        cid="c-super",
        text="book chapter",
        embed_with=client,
        subject_id="subj-1",
        lifecycle_state=LifecycleState.SUPERSEDED,
    )
    _seed(
        store,
        cid="c-tomb",
        text="book chapter",
        embed_with=client,
        subject_id="subj-1",
        lifecycle_state=LifecycleState.TOMBSTONED,
    )

    window = DateRange(start=_DATE, end=_DATE)
    sparse = store.sparse_candidates(
        "fam-A", "book chapter", 10, date_range=window, subject_scope="subj-1"
    )
    dense = store.dense_candidates(
        "fam-A",
        client.embed(["book chapter"])[0],
        client.model_name,
        10,
        date_range=window,
        subject_scope="subj-1",
    )
    assert {h.chunk_id for h in sparse} == {"c-keep"}
    assert {h.chunk_id for h in dense} == {"c-keep"}


# === Persistence / round-trip across backends ================================


@pytest.mark.parametrize(
    "state", [LifecycleState.ACTIVE, LifecycleState.SUPERSEDED, LifecycleState.TOMBSTONED]
)
def test_chunk_round_trips_each_state(
    persist_store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
    state: LifecycleState,
) -> None:
    """Each lifecycle state + a set ``supersedes_chunk_id`` round-trips through
    the real ``get_event_chunk`` read seam, on every backend."""
    _seed(
        persist_store,
        cid="c1",
        text="Walked the dog",
        lifecycle_state=state,
        supersedes_chunk_id="prior-chunk",
        status=EmbeddingStatus.PENDING,
    )
    read = persist_store.get_event_chunk("c1", community_id="fam-A")
    assert read is not None
    assert read.lifecycle_state is state
    assert read.supersedes_chunk_id == "prior-chunk"


@pytest.mark.parametrize(
    "state", [LifecycleState.ACTIVE, LifecycleState.SUPERSEDED, LifecycleState.TOMBSTONED]
)
def test_note_round_trips_each_state(
    persist_store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
    state: LifecycleState,
) -> None:
    """Each lifecycle state + a set ``supersedes_note_id`` round-trips through
    the real ``get_note_by_source_message_id`` read seam, on every backend."""
    _seed(
        persist_store,
        cid="c1",
        text="Walked the dog",
        lifecycle_state=state,
        supersedes_note_id="prior-note",
        status=EmbeddingStatus.PENDING,
    )
    read = persist_store.get_note_by_source_message_id("src-c1")
    assert read is not None
    assert read.lifecycle_state is state
    assert read.supersedes_note_id == "prior-note"


def test_default_is_active(
    persist_store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """A default-constructed row reads back ``active`` / NULL lineage."""
    _seed(persist_store, cid="c1", text="Walked the dog", status=EmbeddingStatus.PENDING)
    chunk = persist_store.get_event_chunk("c1", community_id="fam-A")
    note = persist_store.get_note_by_source_message_id("src-c1")
    assert chunk is not None and note is not None
    assert chunk.lifecycle_state is LifecycleState.ACTIVE
    assert chunk.supersedes_chunk_id is None
    assert note.lifecycle_state is LifecycleState.ACTIVE
    assert note.supersedes_note_id is None


# === Enum / CHECK drift guard ================================================


def test_lifecycle_state_values_pinned() -> None:
    """The three allowed values are an explicit invariant (must match the
    postgres + sqlite CHECK lists and the persisted text)."""
    assert {s.value for s in LifecycleState} == {"active", "superseded", "tombstoned"}
    assert LifecycleState.ACTIVE.value == "active"
    assert LifecycleState.SUPERSEDED.value == "superseded"
    assert LifecycleState.TOMBSTONED.value == "tombstoned"


@pytest.mark.skipif(PG_DSN is None, reason="MEMORY_RAG_PG_TEST_DSN not set; PG leg skipped.")
def test_postgres_rejects_illegal_lifecycle_state() -> None:
    """The PostgreSQL CHECK constraint fires on a value outside the enum —
    making enum/CHECK drift a tested failure, not a silent acceptance."""
    import psycopg

    from memory_rag.storage.postgres import PostgresDomainStore

    assert PG_DSN is not None
    pg = PostgresDomainStore(PG_DSN)
    try:
        _truncate(PG_DSN)
        _seed(pg, cid="c1", text="Walked the dog", status=EmbeddingStatus.PENDING)
        with (
            pytest.raises(psycopg.errors.CheckViolation),
            psycopg.connect(PG_DSN, autocommit=True) as conn,
            conn.cursor() as cur,
        ):
            cur.execute("UPDATE event_chunks SET lifecycle_state = 'bogus' WHERE chunk_id = 'c1'")
    finally:
        pg.close()
