"""`/edit` ingestion supersession + re-embed suite (ED-2 / D-114).

Pins the ED-2 half of the edit/delete contract: an edited ``/note`` that
re-arrives with a new ``edit_seq`` and parses as a note supersedes the prior
active revision. The new note/chunk land ``active`` with ``supersedes_*``
lineage to the prior; the prior note + chunk flip to ``superseded`` (retained,
authorship preserved — I-6); the new chunk re-embeds through the existing
synchronous ingest path; and both retrieval legs exclude the superseded
revision immediately (R-4).

Owner-confirmed semantics pinned here (D-114, ED-2):
- a malformed/INVALID_INPUT edit does **not** supersede the prior (no-op);
- supersession is NOTE->NOTE only — a draft edit does not supersede;
- a fresh original (no prior active note) supersedes nothing;
- supersession holds even if the new revision's re-embed fails.

Harness: the ``store`` fixture drives ``DomainService.ingest`` over **mock +
sqlite + PG-gated postgres** (``MEMORY_RAG_PG_TEST_DSN``); sqlite is an ingest
backend here (not the retrieval legs). The ``retrieval_store`` fixture
(**mock + postgres**) covers the end-to-end retrieval-effectiveness check,
since sqlite's retrieval legs raise ``NotImplementedError`` (D-022 / D-025).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from memory_rag.adapters.embeddings import MockEmbeddingClient
from memory_rag.core.domain.models import LifecycleState
from memory_rag.core.embeddings.models import EmbeddingStatus
from memory_rag.core.routing import InboundMessage, RouteKind
from memory_rag.services import DomainService
from memory_rag.storage.mock import MockDomainStore
from memory_rag.storage.sqlite import SqliteDomainStore

if TYPE_CHECKING:
    from memory_rag.storage.postgres import PostgresDomainStore

PG_DSN = os.environ.get("MEMORY_RAG_PG_TEST_DSN")

_NOW = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)

# Two deliveries of one Telegram message: same (chat, message_id), distinct
# edit_seq (0 = original, the edit_date epoch otherwise) — the R-2 key shape.
_CHAT = "chat-1"
_MSG = "msg-100"
_ORIGINAL_SEQ = 0
_EDIT_SEQ = 1_715_300_100


class _RaisingEmbeddingClient:
    """Forces the embedding step to fail so re-embed-failure semantics hold."""

    model_name = "boom"
    dimension = 3072

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("provider down")


def _msg(
    payload: str,
    *,
    chat: str = _CHAT,
    message_id: str = _MSG,
    user: str = "u-alice",
    edit_seq: int = _ORIGINAL_SEQ,
    community_id: str = "fam-A",
    route: RouteKind = RouteKind.NOTE,
    subject_id: str | None = None,
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
        subject_id=subject_id,
    )


def _truncate(dsn: str) -> None:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE embedding_records, event_chunks, notes, source_messages "
            "RESTART IDENTITY CASCADE"
        )


@pytest.fixture(params=["mock", "sqlite"] + (["postgres"] if PG_DSN else []))
def store(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[MockDomainStore | SqliteDomainStore | PostgresDomainStore]:
    """Ingest-capable store: mock + sqlite (fresh DB) + PG-gated postgres."""
    if request.param == "mock":
        yield MockDomainStore()
    elif request.param == "sqlite":
        path = tmp_path_factory.mktemp("ed2") / "supersession.db"
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


# === Core supersession path ==================================================


def test_edit_supersedes_prior_note_and_chunk(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """An edited note creates a new active revision linked by supersedes_* to
    the prior, and flips the prior note + chunk to superseded."""
    svc = DomainService(store)
    r1 = svc.ingest(_msg("2026-05-09\noriginal body", edit_seq=_ORIGINAL_SEQ))
    prior_note = store.get_note_by_source_message_id(r1.source_message_id)
    assert prior_note is not None
    prior_chunk = store.get_active_chunk_for_note(prior_note.note_id, community_id="fam-A")
    assert prior_chunk is not None

    r2 = svc.ingest(_msg("2026-05-09\nedited body", edit_seq=_EDIT_SEQ))
    new_note = store.get_note_by_source_message_id(r2.source_message_id)
    assert new_note is not None
    new_chunk = store.get_active_chunk_for_note(new_note.note_id, community_id="fam-A")
    assert new_chunk is not None

    # New revision is active and carries lineage to the prior.
    assert new_note.lifecycle_state is LifecycleState.ACTIVE
    assert new_note.supersedes_note_id == prior_note.note_id
    assert new_chunk.lifecycle_state is LifecycleState.ACTIVE
    assert new_chunk.supersedes_chunk_id == prior_chunk.chunk_id

    # Prior revision is retained but superseded (not mutated/destroyed).
    superseded_note = store.get_note_by_source_message_id(r1.source_message_id)
    superseded_chunk = store.get_event_chunk(prior_chunk.chunk_id, community_id="fam-A")
    assert superseded_note is not None and superseded_chunk is not None
    assert superseded_note.lifecycle_state is LifecycleState.SUPERSEDED
    assert superseded_chunk.lifecycle_state is LifecycleState.SUPERSEDED
    assert superseded_note.note_text == "original body"  # content intact


def test_fresh_original_supersedes_nothing(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """A first delivery finds no prior active note: active, NULL lineage."""
    svc = DomainService(store)
    r1 = svc.ingest(_msg("2026-05-09\nonly body", edit_seq=_ORIGINAL_SEQ))
    note = store.get_note_by_source_message_id(r1.source_message_id)
    assert note is not None
    chunk = store.get_active_chunk_for_note(note.note_id, community_id="fam-A")
    assert chunk is not None
    assert note.lifecycle_state is LifecycleState.ACTIVE
    assert note.supersedes_note_id is None
    assert chunk.supersedes_chunk_id is None


def test_replayed_edit_does_not_re_supersede(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """Redelivering the same edit tuple replays (R-2): no second flip."""
    svc = DomainService(store)
    r1 = svc.ingest(_msg("2026-05-09\noriginal body", edit_seq=_ORIGINAL_SEQ))
    prior_note = store.get_note_by_source_message_id(r1.source_message_id)
    assert prior_note is not None

    edit = _msg("2026-05-09\nedited body", edit_seq=_EDIT_SEQ)
    r2 = svc.ingest(edit)
    r3 = svc.ingest(edit)

    assert r2.replayed is False
    assert r3.replayed is True
    assert r3.source_message_id == r2.source_message_id
    # Prior stays superseded; new note stays active — replay changed nothing.
    again_prior = store.get_note_by_source_message_id(r1.source_message_id)
    new_note = store.get_note_by_source_message_id(r2.source_message_id)
    assert again_prior is not None and new_note is not None
    assert again_prior.lifecycle_state is LifecycleState.SUPERSEDED
    assert new_note.lifecycle_state is LifecycleState.ACTIVE


def test_invalid_edit_keeps_prior_active(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """A malformed edit (INVALID_INPUT) creates no revision and never
    supersedes the last good one (confirmed semantics, Q1)."""
    from memory_rag.core.domain import FallbackMode

    svc = DomainService(store)
    r1 = svc.ingest(_msg("2026-05-09\noriginal body", edit_seq=_ORIGINAL_SEQ))
    prior_note = store.get_note_by_source_message_id(r1.source_message_id)
    assert prior_note is not None
    prior_chunk = store.get_active_chunk_for_note(prior_note.note_id, community_id="fam-A")
    assert prior_chunk is not None

    bad = svc.ingest(_msg("not-a-date\nstray line", edit_seq=_EDIT_SEQ))
    assert bad.fallback is FallbackMode.INVALID_INPUT

    still_note = store.get_note_by_source_message_id(r1.source_message_id)
    still_chunk = store.get_event_chunk(prior_chunk.chunk_id, community_id="fam-A")
    assert still_note is not None and still_chunk is not None
    assert still_note.lifecycle_state is LifecycleState.ACTIVE
    assert still_chunk.lifecycle_state is LifecycleState.ACTIVE


def test_draft_edit_does_not_supersede_prior_note(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """A draft-routed edit of a prior note does not supersede it — supersession
    is NOTE->NOTE only (confirmed semantics, Q2)."""
    svc = DomainService(store)
    r1 = svc.ingest(_msg("2026-05-09\noriginal body", edit_seq=_ORIGINAL_SEQ))
    prior_note = store.get_note_by_source_message_id(r1.source_message_id)
    assert prior_note is not None

    svc.ingest(_msg("just chatting now", edit_seq=_EDIT_SEQ, route=RouteKind.DRAFT))

    still = store.get_note_by_source_message_id(r1.source_message_id)
    assert still is not None
    assert still.lifecycle_state is LifecycleState.ACTIVE


# === Empty-body edges (both directions) ======================================


def test_date_only_prior_then_body_edit(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """A date-only prior (no chunk) edited to add a body: the new chunk has no
    chunk-level lineage, but the prior note still flips superseded."""
    svc = DomainService(store)
    r1 = svc.ingest(_msg("2026-05-09", edit_seq=_ORIGINAL_SEQ))  # date-only -> no chunk
    prior_note = store.get_note_by_source_message_id(r1.source_message_id)
    assert prior_note is not None
    assert store.get_active_chunk_for_note(prior_note.note_id, community_id="fam-A") is None

    r2 = svc.ingest(_msg("2026-05-09\nnow has a body", edit_seq=_EDIT_SEQ))
    new_note = store.get_note_by_source_message_id(r2.source_message_id)
    assert new_note is not None
    new_chunk = store.get_active_chunk_for_note(new_note.note_id, community_id="fam-A")
    assert new_chunk is not None
    assert new_chunk.supersedes_chunk_id is None  # prior had no chunk to link
    assert new_note.supersedes_note_id == prior_note.note_id

    superseded = store.get_note_by_source_message_id(r1.source_message_id)
    assert superseded is not None
    assert superseded.lifecycle_state is LifecycleState.SUPERSEDED


def test_body_prior_then_date_only_edit(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """A prior with a body edited to date-only: the new revision has no chunk,
    yet the prior chunk + note both flip superseded."""
    svc = DomainService(store)
    r1 = svc.ingest(_msg("2026-05-09\nhad a body", edit_seq=_ORIGINAL_SEQ))
    prior_note = store.get_note_by_source_message_id(r1.source_message_id)
    assert prior_note is not None
    prior_chunk = store.get_active_chunk_for_note(prior_note.note_id, community_id="fam-A")
    assert prior_chunk is not None

    r2 = svc.ingest(_msg("2026-05-09", edit_seq=_EDIT_SEQ))  # date-only -> no chunk
    assert r2.events_count == 0
    new_note = store.get_note_by_source_message_id(r2.source_message_id)
    assert new_note is not None
    assert new_note.lifecycle_state is LifecycleState.ACTIVE
    assert store.get_active_chunk_for_note(new_note.note_id, community_id="fam-A") is None

    superseded_chunk = store.get_event_chunk(prior_chunk.chunk_id, community_id="fam-A")
    superseded_note = store.get_note_by_source_message_id(r1.source_message_id)
    assert superseded_chunk is not None and superseded_note is not None
    assert superseded_chunk.lifecycle_state is LifecycleState.SUPERSEDED
    assert superseded_note.lifecycle_state is LifecycleState.SUPERSEDED


# === Re-embed failure, authorship, scoping ===================================


def test_supersession_holds_when_reembed_fails(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """If the new revision's re-embed fails, the prior is still superseded and
    the new revision is active with embedding_status='failed' (downstream)."""
    from memory_rag.core.domain import FallbackMode

    svc = DomainService(store, embedding_client=_RaisingEmbeddingClient())
    r1 = svc.ingest(_msg("2026-05-09\noriginal body", edit_seq=_ORIGINAL_SEQ))
    prior_note = store.get_note_by_source_message_id(r1.source_message_id)
    assert prior_note is not None

    r2 = svc.ingest(_msg("2026-05-09\nedited body", edit_seq=_EDIT_SEQ))
    assert r2.fallback is FallbackMode.NONE  # raw + chunk lineage survived

    new_note = store.get_note_by_source_message_id(r2.source_message_id)
    assert new_note is not None
    new_chunk = store.get_active_chunk_for_note(new_note.note_id, community_id="fam-A")
    assert new_chunk is not None
    assert new_chunk.lifecycle_state is LifecycleState.ACTIVE
    assert new_chunk.embedding_status is EmbeddingStatus.FAILED

    superseded = store.get_note_by_source_message_id(r1.source_message_id)
    assert superseded is not None
    assert superseded.lifecycle_state is LifecycleState.SUPERSEDED


def test_author_change_preserves_prior_authorship(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """An edit by a different user keeps the prior revision's author (I-6) and
    the new revision carries the new author; lineage links remain intact."""
    svc = DomainService(store)
    r1 = svc.ingest(_msg("2026-05-09\noriginal body", user="u-alice", edit_seq=_ORIGINAL_SEQ))
    r2 = svc.ingest(_msg("2026-05-09\nedited body", user="u-bob", edit_seq=_EDIT_SEQ))

    prior = store.get_note_by_source_message_id(r1.source_message_id)
    new = store.get_note_by_source_message_id(r2.source_message_id)
    assert prior is not None and new is not None
    assert prior.author_user_id == "u-alice"  # never erased
    assert prior.lifecycle_state is LifecycleState.SUPERSEDED
    assert new.author_user_id == "u-bob"
    assert new.supersedes_note_id == prior.note_id


def test_cross_community_edit_does_not_supersede(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """The prior-revision lookup + the flip are community-scoped: an edit in
    community B cannot supersede community A's note for the same external
    message (I-7, R-3)."""
    svc = DomainService(store)
    r_a = svc.ingest(
        _msg("2026-05-09\nfamily A note", community_id="fam-A", edit_seq=_ORIGINAL_SEQ)
    )
    note_a = store.get_note_by_source_message_id(r_a.source_message_id)
    assert note_a is not None

    # Same (chat, message_id) but a different community and a distinct edit_seq.
    r_b = svc.ingest(_msg("2026-05-09\nfamily B note", community_id="fam-B", edit_seq=_EDIT_SEQ))
    note_b = store.get_note_by_source_message_id(r_b.source_message_id)
    assert note_b is not None

    # A's note is untouched; B's is a fresh original (no supersession).
    still_a = store.get_note_by_source_message_id(r_a.source_message_id)
    assert still_a is not None
    assert still_a.lifecycle_state is LifecycleState.ACTIVE
    assert note_b.lifecycle_state is LifecycleState.ACTIVE
    assert note_b.supersedes_note_id is None


# === Marker-seam contract ====================================================


def test_marker_seams_reject_unknown_id_and_empty_community(
    store: MockDomainStore | SqliteDomainStore | PostgresDomainStore,
) -> None:
    """mark_*_superseded raise KeyError on an unknown id and ValueError on an
    empty community_id (precedent parity + fail-closed scoping)."""
    svc = DomainService(store)
    r1 = svc.ingest(_msg("2026-05-09\nbody", edit_seq=_ORIGINAL_SEQ))
    note = store.get_note_by_source_message_id(r1.source_message_id)
    assert note is not None
    chunk = store.get_active_chunk_for_note(note.note_id, community_id="fam-A")
    assert chunk is not None

    with pytest.raises(KeyError):
        store.mark_note_superseded("no-such-note", community_id="fam-A")
    with pytest.raises(KeyError):
        store.mark_chunk_superseded("no-such-chunk", community_id="fam-A")
    with pytest.raises(ValueError):
        store.mark_note_superseded(note.note_id, community_id="")
    with pytest.raises(ValueError):
        store.mark_chunk_superseded(chunk.chunk_id, community_id="")


# === End-to-end retrieval effect (mock + postgres) ===========================


def test_superseded_prior_excluded_from_retrieval_after_edit(
    retrieval_store: MockDomainStore | PostgresDomainStore,
) -> None:
    """After an edit, the superseded revision is gone from both legs and the
    new active revision is retrievable (R-4, effective immediately)."""
    client = MockEmbeddingClient()
    svc = DomainService(retrieval_store, embedding_client=client)
    svc.ingest(_msg("2026-05-09\nWalked the dog", edit_seq=_ORIGINAL_SEQ))
    svc.ingest(_msg("2026-05-09\nWalked the cat", edit_seq=_EDIT_SEQ))

    # The superseded 'dog' revision is excluded from both legs, even though its
    # embedding is still ready.
    assert retrieval_store.sparse_candidates("fam-A", "dog", 10) == []
    dense_old = retrieval_store.dense_candidates(
        "fam-A", client.embed(["Walked the dog"])[0], client.model_name, 10
    )
    assert dense_old == []

    # The new active 'cat' revision is retrievable.
    new_sparse = retrieval_store.sparse_candidates("fam-A", "cat", 10)
    assert [c.chunk_text for c in new_sparse] == ["Walked the cat"]
