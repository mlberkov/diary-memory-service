"""Consolidated cross-community read-access isolation sweep — Slice 8.1 closure (D-090).

This is the single milestone-level proof for Slice 8.1 (community-scoped
read-access enforcement). The milestone contract: every read of a
community-owned record either carries a non-null ``community_id`` and filters by
the owning community, or is a documented safe-by-construction seam. This file
pins the five scoped by-id / trace / source reads in one reviewable place::

    get_query, get_retrieval_hits_for_query, get_answer_trace_for_query,
    get_event_chunk, get_source_message

Two contracts are asserted across every backend (mock / sqlite / PG-gated
postgres) from one parametrized fixture:

  * fail-closed guard — a null/empty ``community_id`` raises ``ValueError`` (R-3);
  * cross-community isolation — a record owned by ``fam-A`` reads the empty
    sentinel (``None`` / ``[]``) for ``fam-B``, never another community's row.

``get_event_chunk``'s isolation/guard is newly pinned here: D-088 scoped the
``get_event_chunk`` code (keyword-only ``community_id`` + own-column filter +
null guard) but shipped no isolation test of its own. The other four mirror
their per-packet guard tests (``test_storage_query_traces.py``,
``test_storage_answer_traces.py``, ``test_storage_source_messages.py``) as a
consolidated closure surface; the overlap is deliberate.

The remaining milestone evidence stays in place and is indexed here, not
re-implemented:

  * hot-path retrieval scope — ``test_dense_family_scope_isolates`` /
    ``test_sparse_family_scope_isolates``
    (``test_search_repository_{mock,postgres}.py``); ``test_cross_chat_isolation``
    / ``test_missing_community_id_raises`` (``test_query_service.py``);
  * prompt-assembly single-community raise — ``test_cross_family_context_raises``
    -> ``CrossCommunityContextError`` (``test_answer_prompt.py``);
  * ``/sources`` author-resolution seam — ``test_bridge_floor_when_community_mismatch``
    (``test_author_display_resolution.py``);
  * ``_latest_sources`` cache already community-keyed by construction —
    ``test_two_family_caches_are_independent`` (``test_dispatcher_sources.py``).

See ``docs/decision-log.md`` D-090, ``docs/READ-ACCESS-ENFORCEMENT-ROADMAP.md``,
``docs/INVARIANTS.md`` I-7, ``docs/RUNTIME-INVARIANTS.md`` R-3 / R-8.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from memory_rag.core.domain.models import (
    AnswerTrace,
    EventChunk,
    FallbackMode,
    Note,
    Query,
    RetrievalHit,
    RetrievalLeg,
    SourceMessage,
)
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


def _note(eid: str = "e1", sid: str = "s1") -> Note:
    return Note(
        note_id=eid,
        source_message_id=sid,
        community_id="fam-A",
        author_user_id="u1",
        note_date=date(2026, 5, 9),
        note_text="Walked the dog",
        created_at=_now(),
    )


def _chunk(cid: str = "c1", eid: str = "e1", sid: str = "s1", idx: int = 0) -> EventChunk:
    return EventChunk(
        chunk_id=cid,
        note_id=eid,
        source_message_id=sid,
        community_id="fam-A",
        author_user_id="u1",
        note_date=date(2026, 5, 9),
        event_index=idx,
        chunk_text="Walked the dog",
        created_at=_now(),
    )


def _query(qid: str = "q1", community_id: str = "fam-A") -> Query:
    return Query(
        query_id=qid,
        community_id=community_id,
        query_text="book",
        model_name="mock",
        fallback=FallbackMode.NONE,
        created_at=_now(),
    )


def _hit(hid: str = "h1", qid: str = "q1", chunk_id: str = "c1") -> RetrievalHit:
    return RetrievalHit(
        retrieval_hit_id=hid,
        query_id=qid,
        chunk_id=chunk_id,
        leg=RetrievalLeg.DENSE,
        rank=1,
        score=0.5,
        model_name="mock",
        created_at=_now(),
    )


def _trace(aid: str = "a1", qid: str = "q1") -> AnswerTrace:
    return AnswerTrace(
        answer_trace_id=aid,
        query_id=qid,
        prompt_version="v1",
        context_chunk_ids=("c1",),
        answer_text="Mock answer.",
        fallback_mode=FallbackMode.NONE,
        model_name="mock",
        token_counts={"prompt": 10, "completion": 5},
        latency_ms=0,
        created_at=_now(),
    )


def _seed(store: DomainRepository) -> None:
    """Seed one fam-A record reachable by each of the five scoped reads.

    Order respects the FK chain: source -> note -> chunks -> query -> hits ->
    answer_trace (hits reference ``event_chunks``; the answer trace references
    ``queries``).
    """
    store.save_source_message(_source())
    store.save_note(_note())
    store.save_event_chunks([_chunk("c1", idx=0), _chunk("c2", idx=1)])
    store.save_query(_query())
    store.save_retrieval_hits([_hit()])
    store.save_answer_trace(_trace())


def _truncate(dsn: str) -> None:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE answer_traces, retrieval_hits, queries, embedding_records, "
            "event_chunks, notes, source_messages "
            "RESTART IDENTITY CASCADE"
        )


@pytest.fixture(params=["mock", "sqlite"] + (["postgres"] if PG_DSN else []))
def scoped_store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[DomainRepository]:
    """A store seeded with one fam-A record per scoped read, across every backend."""
    if request.param == "mock":
        store: DomainRepository = MockDomainStore()
        _seed(store)
        yield store
    elif request.param == "sqlite":
        store = SqliteDomainStore(str(tmp_path / "scoped.db"))
        _seed(store)
        yield store
    else:
        from memory_rag.storage.postgres import PostgresDomainStore

        assert PG_DSN is not None
        _truncate(PG_DSN)
        pg = PostgresDomainStore(PG_DSN)
        try:
            _seed(pg)
            yield pg
        finally:
            pg.close()


# A scoped read is named, invoked by a closure over (store, community_id), and
# carries the empty/fail-closed sentinel its contract returns for a foreign
# community: ``None`` for the single-record reads, ``[]`` for the list read.
_ScopedRead = Callable[[DomainRepository, str], object]

_SCOPED_READS: list[tuple[str, _ScopedRead, object]] = [
    ("get_query", lambda s, cid: s.get_query("q1", community_id=cid), None),
    (
        "get_retrieval_hits_for_query",
        lambda s, cid: s.get_retrieval_hits_for_query("q1", community_id=cid),
        [],
    ),
    (
        "get_answer_trace_for_query",
        lambda s, cid: s.get_answer_trace_for_query("q1", community_id=cid),
        None,
    ),
    ("get_event_chunk", lambda s, cid: s.get_event_chunk("c1", community_id=cid), None),
    ("get_source_message", lambda s, cid: s.get_source_message("s1", community_id=cid), None),
]

_READ_IDS = [name for name, _read, _empty in _SCOPED_READS]


@pytest.mark.parametrize("name,read,empty", _SCOPED_READS, ids=_READ_IDS)
def test_scoped_read_rejects_empty_community_id(
    scoped_store: DomainRepository,
    name: str,
    read: _ScopedRead,
    empty: object,
) -> None:
    """Every scoped read fails closed on a null/empty community_id (R-3)."""
    with pytest.raises(ValueError, match="community_id is required"):
        read(scoped_store, "")


@pytest.mark.parametrize("name,read,empty", _SCOPED_READS, ids=_READ_IDS)
def test_scoped_read_cross_community_fails_closed(
    scoped_store: DomainRepository,
    name: str,
    read: _ScopedRead,
    empty: object,
) -> None:
    """The owning community reads its record; a foreign community sees no leak."""
    owner = read(scoped_store, "fam-A")
    if isinstance(empty, list):
        assert owner != [], f"{name}: owning community should see its record"
    else:
        assert owner is not None, f"{name}: owning community should see its record"
    # Same id, different community: fail-closed sentinel, never another community's row.
    assert read(scoped_store, "fam-B") == empty, f"{name}: cross-community read leaked"
