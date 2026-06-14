"""`/delete` tombstone + NOTE->DRAFT removal + audited hard-delete (ED-3 / D-114).

Pins the ED-3 (delete) half of the edit/delete contract:

- the ``/delete`` control path tombstones the active note (+ chunk) the user
  replied to, retained with I-6 authorship intact and excluded from retrieval
  immediately (R-4), and is a fail-closed no-op for every miss;
- a NOTE->DRAFT edit (a captured ``/note`` edited to drop its command)
  tombstones the prior active note;
- the ``mark_*_tombstoned`` seams mirror the ED-2 superseded-writer contract;
- ``hard_delete_source_message`` physically removes a raw source message and the
  rows derived from it within the community, in FK-safe order, with the audit
  log; it is community-scoped and raises on a cross-community target.

Harness mirrors ``test_edit_supersession_ingest.py``: the ``store`` fixture
drives the service over **mock + sqlite + PG-gated postgres**; the
``retrieval_store`` fixture (**mock + postgres**) covers the
retrieval-effectiveness check (sqlite has no retrieval legs — D-022 / D-025).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from memory_rag.adapters.embeddings import MockEmbeddingClient
from memory_rag.core.domain import FallbackMode
from memory_rag.core.domain.models import (
    LifecycleState,
    Query,
    RetrievalHit,
    RetrievalLeg,
)
from memory_rag.core.routing import InboundMessage, RouteKind
from memory_rag.services import DomainService
from memory_rag.storage.mock import MockDomainStore
from memory_rag.storage.sqlite import SqliteDomainStore

if TYPE_CHECKING:
    from memory_rag.storage.postgres import PostgresDomainStore

PG_DSN = os.environ.get("MEMORY_RAG_PG_TEST_DSN")

_NOW = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)

_CHAT = "chat-1"
_MSG = "msg-100"
_ORIGINAL_SEQ = 0
_EDIT_SEQ = 1_715_300_100
_COMMUNITY = "fam-A"


def _msg(
    payload: str,
    *,
    chat: str = _CHAT,
    message_id: str = _MSG,
    user: str = "u-alice",
    edit_seq: int = _ORIGINAL_SEQ,
    community_id: str = _COMMUNITY,
    route: RouteKind = RouteKind.NOTE,
) -> InboundMessage:
    """Build an inbound NOTE (or DRAFT) delivery for one external message."""
    is_note = route is RouteKind.NOTE
    return InboundMessage(
        external_message_id=message_id,
        external_chat_id=chat,
        external_user_id=user,
        community_id=community_id,
        text=f"/note {payload}" if is_note else payload,
        route=route,
        received_at=_NOW,
        route_source="command" if is_note else "heuristic",
        payload=payload,
        edit_seq=edit_seq,
    )


def _truncate(dsn: str) -> None:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE retrieval_hits, queries, embedding_records, event_chunks, "
            "notes, source_messages RESTART IDENTITY CASCADE"
        )


@pytest.fixture(params=["mock", "sqlite"] + (["postgres"] if PG_DSN else []))
def store(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[MockDomainStore | SqliteDomainStore | PostgresDomainStore]:
    """Ingest-capable store: mock + sqlite (fresh DB) + PG-gated postgres."""
    if request.param == "mock":
        yield MockDomainStore()
    elif request.param == "sqlite":
        path = tmp_path_factory.mktemp("ed3") / "delete.db"
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


@pytest.fixture(params=["mock"] + (["postgres"] if PG_DSN else []))
def retrieval_store(
    request: pytest.FixtureRequest,
) -> Iterator[MockDomainStore | PostgresDomainStore]:
    """Retrieval-capable store: mock + PG-gated postgres (sqlite has no legs)."""
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


# === /delete control path (soft tombstone) ===================================


def test_delete_tombstones_active_note_and_chunk(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """/delete on the replied-to note tombstones the active note + chunk; the
    prior rows are retained (content + I-6 authorship intact)."""
    svc = DomainService(store)
    r1 = svc.ingest(_msg("2026-05-09\nWalked the dog", user="u-alice"))
    note = store.get_note_by_source_message_id(r1.source_message_id)
    assert note is not None
    chunk = store.get_active_chunk_for_note(note.note_id, community_id=_COMMUNITY)
    assert chunk is not None

    outcome = svc.delete_note_for_external_message(_CHAT, _MSG, community_id=_COMMUNITY)
    assert outcome.deleted is True
    assert outcome.note_date == note.note_date

    # No active note/chunk remains for the external message.
    assert store.get_active_note_for_external_message(_CHAT, _MSG, community_id=_COMMUNITY) is None
    assert store.get_active_chunk_for_note(note.note_id, community_id=_COMMUNITY) is None

    # The rows are retained at tombstoned, not destroyed; authorship intact.
    kept_note = store.get_note_by_source_message_id(r1.source_message_id)
    kept_chunk = store.get_event_chunk(chunk.chunk_id, community_id=_COMMUNITY)
    assert kept_note is not None and kept_chunk is not None
    assert kept_note.lifecycle_state is LifecycleState.TOMBSTONED
    assert kept_chunk.lifecycle_state is LifecycleState.TOMBSTONED
    assert kept_note.note_text == "Walked the dog"
    assert kept_note.author_user_id == "u-alice"


def test_delete_date_only_note_has_no_chunk(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """A date-only note (no chunk) is still tombstoned at the note level."""
    svc = DomainService(store)
    r1 = svc.ingest(_msg("2026-05-09"))  # date-only -> no chunk
    note = store.get_note_by_source_message_id(r1.source_message_id)
    assert note is not None
    assert store.get_active_chunk_for_note(note.note_id, community_id=_COMMUNITY) is None

    outcome = svc.delete_note_for_external_message(_CHAT, _MSG, community_id=_COMMUNITY)
    assert outcome.deleted is True
    kept = store.get_note_by_source_message_id(r1.source_message_id)
    assert kept is not None
    assert kept.lifecycle_state is LifecycleState.TOMBSTONED


def test_delete_unknown_target_is_noop(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """/delete for an external message with no active note is a no-op."""
    svc = DomainService(store)
    svc.ingest(_msg("2026-05-09\nWalked the dog"))
    outcome = svc.delete_note_for_external_message(
        _CHAT, "no-such-message", community_id=_COMMUNITY
    )
    assert outcome.deleted is False


def test_delete_is_idempotent(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """A second /delete finds no active note and is a no-op (no double flip)."""
    svc = DomainService(store)
    svc.ingest(_msg("2026-05-09\nWalked the dog"))
    first = svc.delete_note_for_external_message(_CHAT, _MSG, community_id=_COMMUNITY)
    second = svc.delete_note_for_external_message(_CHAT, _MSG, community_id=_COMMUNITY)
    assert first.deleted is True
    assert second.deleted is False


def test_delete_is_community_scoped(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """A /delete issued in community B cannot tombstone community A's note for
    the same external message (I-7, R-3)."""
    svc = DomainService(store)
    r_a = svc.ingest(_msg("2026-05-09\nfamily A note", community_id="fam-A"))
    note_a = store.get_note_by_source_message_id(r_a.source_message_id)
    assert note_a is not None

    outcome = svc.delete_note_for_external_message(_CHAT, _MSG, community_id="fam-B")
    assert outcome.deleted is False

    still_a = store.get_note_by_source_message_id(r_a.source_message_id)
    assert still_a is not None
    assert still_a.lifecycle_state is LifecycleState.ACTIVE


# === NOTE->DRAFT edit-removal =================================================


def test_note_edited_to_draft_tombstones_prior_note(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """Editing a captured /note to drop its command (NOTE->DRAFT) tombstones the
    prior active note — the deferred ED-2 removal semantics (D-116 -> ED-3)."""
    svc = DomainService(store)
    r1 = svc.ingest(_msg("2026-05-09\nWalked the dog", edit_seq=_ORIGINAL_SEQ))
    note = store.get_note_by_source_message_id(r1.source_message_id)
    assert note is not None
    chunk = store.get_active_chunk_for_note(note.note_id, community_id=_COMMUNITY)
    assert chunk is not None

    # The edit re-arrives as plain text -> DRAFT route, same external message.
    svc.ingest(_msg("just chatting now", edit_seq=_EDIT_SEQ, route=RouteKind.DRAFT))

    kept_note = store.get_note_by_source_message_id(r1.source_message_id)
    kept_chunk = store.get_event_chunk(chunk.chunk_id, community_id=_COMMUNITY)
    assert kept_note is not None and kept_chunk is not None
    assert kept_note.lifecycle_state is LifecycleState.TOMBSTONED
    assert kept_chunk.lifecycle_state is LifecycleState.TOMBSTONED


def test_fresh_draft_tombstones_nothing(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """A fresh plain-text draft (no prior active note) tombstones nothing."""
    svc = DomainService(store)
    r = svc.ingest(_msg("a brand new thought", route=RouteKind.DRAFT))
    assert r.fallback is FallbackMode.NONE
    # No note exists for this source at all.
    assert store.get_note_by_source_message_id(r.source_message_id) is None


# === Tombstone-seam contract =================================================


def test_tombstone_seams_reject_unknown_id_and_empty_community(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """mark_*_tombstoned raise KeyError on an unknown id and ValueError on an
    empty community_id (parity with the ED-2 superseded seams)."""
    svc = DomainService(store)
    r1 = svc.ingest(_msg("2026-05-09\nbody"))
    note = store.get_note_by_source_message_id(r1.source_message_id)
    assert note is not None
    chunk = store.get_active_chunk_for_note(note.note_id, community_id=_COMMUNITY)
    assert chunk is not None

    with pytest.raises(KeyError):
        store.mark_note_tombstoned("no-such-note", community_id=_COMMUNITY)
    with pytest.raises(KeyError):
        store.mark_chunk_tombstoned("no-such-chunk", community_id=_COMMUNITY)
    with pytest.raises(ValueError):
        store.mark_note_tombstoned(note.note_id, community_id="")
    with pytest.raises(ValueError):
        store.mark_chunk_tombstoned(chunk.chunk_id, community_id="")


# === Audited hard-delete =====================================================


def _seed_retrieval_hit(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
    *,
    chunk_id: str,
) -> None:
    """Seed a query + one retrieval hit referencing ``chunk_id``.

    The retrieval_hits -> event_chunks FK is the row that forces the hard-delete
    ordering, so the hard-delete test seeds one to prove the ordered cascade.
    """
    store.save_query(
        Query(
            query_id="q-1",
            community_id=_COMMUNITY,
            query_text="dog",
            model_name="mock",
            fallback=FallbackMode.NONE,
            created_at=_NOW,
        )
    )
    store.save_retrieval_hits(
        [
            RetrievalHit(
                retrieval_hit_id="h-1",
                query_id="q-1",
                chunk_id=chunk_id,
                leg=RetrievalLeg.MERGED,
                rank=1,
                score=0.5,
                model_name="mock",
                created_at=_NOW,
            )
        ]
    )


def test_hard_delete_removes_source_and_derived_rows(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """hard_delete_source_message physically removes the source and every row
    derived from it (notes, chunks, embeddings, retrieval hits), in FK-safe
    order, and reports the per-table tally."""
    svc = DomainService(store, embedding_client=MockEmbeddingClient())
    r1 = svc.ingest(_msg("2026-05-09\nWalked the dog"))
    note = store.get_note_by_source_message_id(r1.source_message_id)
    assert note is not None
    chunk = store.get_active_chunk_for_note(note.note_id, community_id=_COMMUNITY)
    assert chunk is not None
    _seed_retrieval_hit(store, chunk_id=chunk.chunk_id)

    outcome = svc.hard_delete_source_message(
        r1.source_message_id, community_id=_COMMUNITY, requested_by="u-operator"
    )
    assert outcome.source_messages == 1
    assert outcome.notes == 1
    assert outcome.event_chunks == 1
    assert outcome.embedding_records == 1
    assert outcome.retrieval_hits == 1

    # Nothing derived survives.
    assert store.get_source_message(r1.source_message_id, community_id=_COMMUNITY) is None
    assert store.get_note_by_source_message_id(r1.source_message_id) is None
    assert store.get_event_chunk(chunk.chunk_id, community_id=_COMMUNITY) is None
    assert store.count_event_chunks_for_source(r1.source_message_id) == 0
    assert store.count_embedding_records_for_source(r1.source_message_id) == 0


def test_hard_delete_unknown_target_raises(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """An unknown source message id raises KeyError (operator mistake is loud)."""
    svc = DomainService(store)
    with pytest.raises(KeyError):
        svc.hard_delete_source_message(
            "no-such-source", community_id=_COMMUNITY, requested_by="u-operator"
        )


def test_hard_delete_is_community_scoped(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """A hard-delete scoped to community B cannot remove community A's source
    (I-7, R-3): it raises and leaves the row intact."""
    svc = DomainService(store)
    r_a = svc.ingest(_msg("2026-05-09\nfamily A note", community_id="fam-A"))
    with pytest.raises(KeyError):
        svc.hard_delete_source_message(
            r_a.source_message_id, community_id="fam-B", requested_by="u-operator"
        )
    assert store.get_source_message(r_a.source_message_id, community_id="fam-A") is not None


def test_hard_delete_empty_community_raises(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """An empty community_id is rejected fail-closed (R-3)."""
    svc = DomainService(store)
    r1 = svc.ingest(_msg("2026-05-09\nbody"))
    with pytest.raises(ValueError):
        svc.hard_delete_source_message(
            r1.source_message_id, community_id="", requested_by="u-operator"
        )


# === End-to-end retrieval effect (mock + postgres) ===========================


def test_tombstoned_note_excluded_from_retrieval(
    retrieval_store: MockDomainStore | PostgresDomainStore,
) -> None:
    """After /delete, the tombstoned chunk is gone from both retrieval legs,
    even though its embedding is still ready (R-4, effective immediately)."""
    client = MockEmbeddingClient()
    svc = DomainService(retrieval_store, embedding_client=client)
    svc.ingest(_msg("2026-05-09\nWalked the dog"))

    # Present before the delete.
    assert [c.chunk_text for c in retrieval_store.sparse_candidates(_COMMUNITY, "dog", 10)] == [
        "Walked the dog"
    ]

    svc.delete_note_for_external_message(_CHAT, _MSG, community_id=_COMMUNITY)

    assert retrieval_store.sparse_candidates(_COMMUNITY, "dog", 10) == []
    dense = retrieval_store.dense_candidates(
        _COMMUNITY, client.embed(["Walked the dog"])[0], client.model_name, 10
    )
    assert dense == []
