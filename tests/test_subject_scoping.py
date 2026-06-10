"""Subject-scoping characterization suite (Milestone H closure / D-097, D-107).

Pins the *already-true* subject-scoping behavior end-to-end **through both
adapter seams**: every ``InboundMessage`` is built with
``community_id=resolve_community_id(chat)`` (G-1 / D-094) and, on the
default path, ``subject_id=resolve_subject_id(community_id)`` (H-2), so the
suite exercises the seams rather than hard-coding the mappings. Explicit
non-``None`` ``subject_id`` values simulate a divergent adapter mapping —
the same shape ``tests/test_domain_service.py`` pins at ingest granularity.

The end-to-end contract pinned here (D-097 / D-107): ingest persists the
resolved opaque ``subject_id`` on chunk rows; ``QueryService.answer`` with a
non-``None`` ``subject_scope`` strict-matches it (community-wide ``None``
rows excluded, reachable only via the default ``None`` = no constraint),
composes with ``date_range`` as a conjunction, never widens the community
boundary (I-7 / R-3), records the requested scope on the persisted ``Query``
row, and fails closed to ``NO_EVIDENCE`` when nothing matches.

Harness boundary: parametrized over **mock + PG-gated postgres**
(``MEMORY_RAG_PG_TEST_DSN``); these are the first service-level
ingest -> answer runs against Postgres. sqlite is excluded — its retrieval
legs raise ``NotImplementedError`` (D-022 / D-025); its ``subject_scope``
parity is signature-only and its ``Query`` round-trip is covered by
``tests/test_storage_query_traces.py``. Grading is mock-mode
(``MockEmbeddingClient`` / ``MockChatClient``).

These are characterization tests over current behavior — no ``src/`` change;
they must pass against production code as-is. They compose with (and do not
re-run) the per-packet coverage:

- ``tests/test_telegram_subject_resolver.py`` — H-2 resolver unit contract.
- ``tests/test_domain_service.py`` — ``subject_id`` threading through ingest.
- ``tests/test_search_repository_mock.py`` /
  ``tests/test_search_repository_postgres.py`` — leg-level strict-match,
  null-exclusion, ``date_range`` composition, and community-boundary
  predicates on both backends.
- ``tests/test_query_service.py`` — mock-store ``answer()`` subject cases.
- ``tests/test_storage_query_traces.py`` — ``Query.subject_scope``
  round-trip across mock / sqlite / postgres.
- ``tests/test_postgres_migrations.py`` — 0005 / 0006 upgrades.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest

from memory_rag.adapters.answers import MockChatClient
from memory_rag.adapters.embeddings import MockEmbeddingClient
from memory_rag.adapters.telegram.community import resolve_community_id
from memory_rag.adapters.telegram.subject import resolve_subject_id
from memory_rag.core.domain import DateRange, FallbackMode
from memory_rag.core.domain.models import AnswerResult, Query
from memory_rag.core.routing import InboundMessage, RouteKind
from memory_rag.services import DomainService, QueryService
from memory_rag.storage.mock import MockDomainStore

if TYPE_CHECKING:
    from memory_rag.storage.postgres import PostgresDomainStore

PG_DSN = os.environ.get("MEMORY_RAG_PG_TEST_DSN")

# Sentinel: route the factory through the H-2 resolver (the webhook default
# path) instead of pinning an explicit subject. Any real subject id wins.
_USE_RESOLVER = "__use-resolver__"


def _truncate(dsn: str) -> None:
    # Wider than the leg-level suites' truncate: ``answer()`` also persists
    # queries / retrieval_hits / answer_traces rows.
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE answer_traces, retrieval_hits, queries, embedding_records, "
            "event_chunks, notes, source_messages "
            "RESTART IDENTITY CASCADE"
        )


@pytest.fixture(params=["mock"] + (["postgres"] if PG_DSN else []))
def store(request: pytest.FixtureRequest) -> Iterator[MockDomainStore | PostgresDomainStore]:
    """A store usable as both ``DomainRepository`` and ``SearchRepository``."""
    if request.param == "mock":
        yield MockDomainStore()
    else:
        from memory_rag.storage.postgres import PostgresDomainStore

        assert PG_DSN is not None
        # Construct before truncating so a fresh database is bootstrapped to
        # schema head first (the test_search_repository_postgres.py ordering).
        pg = PostgresDomainStore(PG_DSN)
        try:
            _truncate(PG_DSN)
            yield pg
        finally:
            pg.close()


# --- message factories (both scope fields resolved via the adapter seams) ----


def _note(
    payload: str,
    *,
    chat: str,
    user: str = "7",
    msg_id: str,
    subject_id: str | None = _USE_RESOLVER,
) -> InboundMessage:
    community_id = resolve_community_id(chat)
    resolved = resolve_subject_id(community_id) if subject_id == _USE_RESOLVER else subject_id
    return InboundMessage(
        external_message_id=msg_id,
        external_chat_id=chat,
        external_user_id=user,
        community_id=community_id,
        text=f"/note {payload}",
        route=RouteKind.NOTE,
        received_at=datetime.now(tz=UTC),
        route_source="command",
        payload=payload,
        subject_id=resolved,
    )


def _ask(query: str, *, chat: str, user: str = "reader", msg_id: str = "900") -> InboundMessage:
    return InboundMessage(
        external_message_id=msg_id,
        external_chat_id=chat,
        external_user_id=user,
        community_id=resolve_community_id(chat),
        text=f"/ask {query}",
        route=RouteKind.ASK,
        received_at=datetime.now(tz=UTC),
        route_source="command",
        payload=query,
    )


# --- wiring -------------------------------------------------------------------


def _ingest(
    store: MockDomainStore | PostgresDomainStore,
    payload: str,
    *,
    chat: str,
    msg_id: str,
    subject_id: str | None = _USE_RESOLVER,
) -> None:
    DomainService(store, embedding_client=MockEmbeddingClient()).ingest(
        _note(payload, chat=chat, msg_id=msg_id, subject_id=subject_id)
    )


def _wire(store: MockDomainStore | PostgresDomainStore) -> QueryService:
    return QueryService(store, store, MockEmbeddingClient(), MockChatClient())


def _persisted_query(
    store: MockDomainStore | PostgresDomainStore, result: AnswerResult, *, chat: str
) -> Query:
    assert result.context is not None
    persisted = store.get_query(result.context.query_id, community_id=resolve_community_id(chat))
    assert persisted is not None
    return persisted


# === The cross-seam contract ==================================================


def test_default_mapping_end_to_end_is_community_wide(
    store: MockDomainStore | PostgresDomainStore,
) -> None:
    """Resolver-default ingest persists community-wide rows.

    The default ``answer()`` retrieves them and persists
    ``Query.subject_scope=None``; a named scope over the same corpus fails
    closed — proving (without reading store internals) that every persisted
    row is community-wide under the default single-subject mapping.
    """
    _ingest(store, "2026-05-09\nTried a new book", chat="fam-A", msg_id="1")
    _ingest(store, "2026-05-09\nAnother book chapter", chat="fam-A", msg_id="2")
    query = _wire(store)

    unscoped = query.answer(_ask("book", chat="fam-A"))

    assert unscoped.fallback is FallbackMode.NONE
    assert {e.chunk_text for e in unscoped.evidence} == {
        "Tried a new book",
        "Another book chapter",
    }
    assert _persisted_query(store, unscoped, chat="fam-A").subject_scope is None

    scoped = query.answer(_ask("book", chat="fam-A"), subject_scope="subj-1")
    assert scoped.fallback is FallbackMode.NO_EVIDENCE
    assert scoped.evidence == []


def test_scoped_answer_returns_only_matching_subject(
    store: MockDomainStore | PostgresDomainStore,
) -> None:
    """A scoped ``answer()`` strict-matches one subject's chunks end-to-end.

    Corpus spans two named subjects plus a community-wide row; the scope is
    recorded on the persisted ``Query`` row.
    """
    _ingest(
        store, "2026-05-09\nBook about subject one", chat="fam-A", msg_id="1", subject_id="subj-A"
    )
    _ingest(
        store, "2026-05-09\nBook about subject two", chat="fam-A", msg_id="2", subject_id="subj-B"
    )
    _ingest(store, "2026-05-09\nBook community wide", chat="fam-A", msg_id="3", subject_id=None)
    query = _wire(store)

    result = query.answer(_ask("book", chat="fam-A"), subject_scope="subj-A")

    assert result.fallback is FallbackMode.NONE
    assert [e.chunk_text for e in result.evidence] == ["Book about subject one"]
    assert result.context is not None
    assert {c.subject_id for c in result.context.ordered_chunks} == {"subj-A"}
    assert _persisted_query(store, result, chat="fam-A").subject_scope == "subj-A"


def test_named_scope_with_no_matching_records_fails_closed(
    store: MockDomainStore | PostgresDomainStore,
) -> None:
    """A named scope with zero matching rows is ``NO_EVIDENCE``, not a widen.

    Distinct from the all-community-wide corpus case
    (``test_query_service.test_subject_scope_over_community_wide_corpus_is_no_evidence``):
    here another *named* subject's rows exist and must not leak either. The
    requested scope is still recorded on the persisted ``Query`` row.
    """
    _ingest(
        store, "2026-05-09\nBook about subject two", chat="fam-A", msg_id="1", subject_id="subj-B"
    )
    _ingest(store, "2026-05-09\nBook community wide", chat="fam-A", msg_id="2", subject_id=None)
    query = _wire(store)

    result = query.answer(_ask("book", chat="fam-A"), subject_scope="subj-A")

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert result.evidence == []
    persisted = _persisted_query(store, result, chat="fam-A")
    assert persisted.subject_scope == "subj-A"
    assert persisted.fallback is FallbackMode.NO_EVIDENCE


def test_community_wide_rows_reachable_only_via_default_scope(
    store: MockDomainStore | PostgresDomainStore,
) -> None:
    """Explicit negative: ``None``-subject rows never match a named scope.

    The community-wide row would match either query textually; it surfaces
    under the default ``None`` scope only.
    """
    _ingest(
        store, "2026-05-09\nBook about subject one", chat="fam-A", msg_id="1", subject_id="subj-A"
    )
    _ingest(store, "2026-05-09\nBook community wide", chat="fam-A", msg_id="2", subject_id=None)
    query = _wire(store)

    scoped = query.answer(_ask("book", chat="fam-A"), subject_scope="subj-A")
    assert [e.chunk_text for e in scoped.evidence] == ["Book about subject one"]

    unscoped = query.answer(_ask("book", chat="fam-A", msg_id="901"))
    assert {e.chunk_text for e in unscoped.evidence} == {
        "Book about subject one",
        "Book community wide",
    }


def test_subject_scope_composes_with_date_range_end_to_end(
    store: MockDomainStore | PostgresDomainStore,
) -> None:
    """``subject_scope`` and ``date_range`` apply together as a conjunction.

    PG parity is the new value over the mock-only
    ``test_query_service.test_answer_composes_subject_scope_with_date_range``.
    """
    _ingest(store, "2026-05-09\nRead a book in May", chat="fam-A", msg_id="1", subject_id="subj-A")
    _ingest(store, "2026-06-15\nRead a book in June", chat="fam-A", msg_id="2", subject_id="subj-A")
    _ingest(store, "2026-06-15\nRead a book in June too", chat="fam-A", msg_id="3", subject_id=None)
    query = _wire(store)

    result = query.answer(
        _ask("book", chat="fam-A"),
        date_range=DateRange(start=date(2026, 6, 1)),
        subject_scope="subj-A",
    )

    assert result.fallback is FallbackMode.NONE
    assert [e.chunk_text for e in result.evidence] == ["Read a book in June"]


def test_same_subject_id_across_communities_stays_isolated(
    store: MockDomainStore | PostgresDomainStore,
) -> None:
    """The same ``subject_id`` string in two communities never crosses over.

    ``subject_id`` is subordinate to ``community_id`` (D-097); the community
    boundary (I-7 / R-3) stays the outer filter. Service-level composition
    over the leg-level
    ``test_search_repository_*.test_subject_scope_never_widens_community_scope``.
    """
    _ingest(store, "2026-05-09\nFamily A book", chat="fam-A", msg_id="1", subject_id="subj-1")
    _ingest(store, "2026-05-09\nFamily B book", chat="fam-B", msg_id="2", subject_id="subj-1")
    query = _wire(store)

    result = query.answer(_ask("book", chat="fam-A"), subject_scope="subj-1")

    assert result.fallback is FallbackMode.NONE
    assert [e.chunk_text for e in result.evidence] == ["Family A book"]


def test_factories_route_through_both_resolvers() -> None:
    """Seam-level pin tying the factories to the H-2 / G-1 resolvers.

    The default factory's ``subject_id`` is exactly
    ``resolve_subject_id(resolve_community_id(chat))`` — ``None`` under the
    default single-subject mapping today.
    """
    message = _note("2026-05-09\nx", chat="fam-A", msg_id="1")
    assert message.community_id == resolve_community_id("fam-A")
    assert message.subject_id == resolve_subject_id(resolve_community_id("fam-A"))
    assert message.subject_id is None
