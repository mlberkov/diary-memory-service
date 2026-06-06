"""Grouped + multi-diary characterization suite (G-2 / D-093 lineage).

Pins the *already-true* grouped-diary and multi-diary-on-one-instance
behavior **through the consolidated chat->community resolver seam**
(``resolve_community_id``, G-1 / D-094): one group chat is one
``community_id`` with distinct per-sender ``author_user_id`` (I-6); N
distinct chats are N isolated communities on one instance (I-7 / R-3 /
R-8); cross-community reads do not leak at grouped granularity.

These are characterization tests over current behavior — they add **no**
``src/`` change and must pass against production code as-is. Every
``InboundMessage`` is built with ``community_id=resolve_community_id(chat)``
so the suite exercises the seam rather than hard-coding the identity
mapping.

Harness boundary: this file is **mock-mode only** (``MockEmbeddingClient``
/ ``MockChatClient``; sqlite retrieval raises ``NotImplementedError``). It
provides no PG/sqlite parity for the end-to-end grouped ingest->ask flow.
That parity stays the responsibility of the existing, PG-gated storage and
leg isolation suites, which remain part of full-gate validation:

- ``tests/test_read_access_isolation.py`` — by-id / trace read fail-closed
  isolation across mock / sqlite / PG-gated postgres (Slice 8.1).
- ``tests/test_search_repository_postgres.py`` — leg-level community scope
  isolation on Postgres.
- ``tests/test_dispatcher_sources.py::test_two_family_caches_are_independent``
  — per-community ``/sources`` cache isolation at the dispatcher seam.

This suite composes with that coverage at grouped granularity; it does not
re-run or duplicate it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from memory_rag.adapters.answers import MockChatClient
from memory_rag.adapters.embeddings import MockEmbeddingClient
from memory_rag.adapters.telegram.community import resolve_community_id
from memory_rag.config import Settings
from memory_rag.core.domain import EventChunk
from memory_rag.core.domain.models import AnswerResult
from memory_rag.core.routing import InboundMessage, RouteKind
from memory_rag.services import Dispatcher, DomainService, ExportService, QueryService
from memory_rag.storage.mock import MockDomainStore

# --- message factories (community_id resolved via the G-1 seam) --------------


def _note(payload: str, *, chat: str, user: str, msg_id: str) -> InboundMessage:
    return InboundMessage(
        external_message_id=msg_id,
        external_chat_id=chat,
        external_user_id=user,
        community_id=resolve_community_id(chat),
        text=f"/note {payload}",
        route=RouteKind.NOTE,
        received_at=datetime.now(tz=UTC),
        route_source="command",
        payload=payload,
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


def _sources(*, chat: str, user: str = "reader", msg_id: str = "950") -> InboundMessage:
    return InboundMessage(
        external_message_id=msg_id,
        external_chat_id=chat,
        external_user_id=user,
        community_id=resolve_community_id(chat),
        text="/sources",
        route=RouteKind.SOURCES,
        received_at=datetime.now(tz=UTC),
        route_source="command",
        payload="",
    )


# --- wiring ------------------------------------------------------------------


def _query_service(store: MockDomainStore) -> QueryService:
    embed = MockEmbeddingClient()
    return QueryService(store, store, embed, MockChatClient())


def _ingest(store: MockDomainStore, payload: str, *, chat: str, user: str, msg_id: str) -> None:
    DomainService(store, embedding_client=MockEmbeddingClient()).ingest(
        _note(payload, chat=chat, user=user, msg_id=msg_id)
    )


def _dispatcher(store: MockDomainStore) -> Dispatcher:
    embed = MockEmbeddingClient()
    return Dispatcher(
        DomainService(store, embedding_client=embed),
        QueryService(store, store, embed, MockChatClient()),
        ExportService(store),
        Settings(_env_file=None),  # type: ignore[call-arg]
    )


def _all_chunks(store: MockDomainStore) -> list[EventChunk]:
    return list(store._chunks.values())


def _grounding_authors(answer: AnswerResult) -> set[str]:
    assert answer.context is not None
    return {c.author_user_id for c in answer.context.ordered_chunks}


# === Group A: grouped diary (one chat, N senders, full ingest -> ask) ========


def test_group_chat_is_one_community_with_distinct_authors() -> None:
    """One group chat -> one ``community_id``; authorship preserved per sender.

    Extends ``test_domain_service.test_ingest_preserves_authorship_on_every_chunk``
    (single author) to the grouped/multi-sender case through the resolver seam.
    """
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nAlice tried a new book", chat="grp", user="alice", msg_id="1")
    _ingest(store, "2026-05-09\nBob walked the dog", chat="grp", user="bob", msg_id="2")
    _ingest(store, "2026-05-09\nCarol cooked dinner", chat="grp", user="carol", msg_id="3")

    chunks = _all_chunks(store)
    assert {c.community_id for c in chunks} == {resolve_community_id("grp")}
    assert {c.author_user_id for c in chunks} == {"alice", "bob", "carol"}


def test_grouped_ask_preserves_distinct_contributors_in_answer_context() -> None:
    """A grouped ``/ask`` surfaces chunks from >=2 distinct senders (I-6).

    Driven by full ingest -> retrieve -> assemble-context, not pre-built
    chunks (cf. ``tests/test_telegram_ask_contributors.py`` which starts from
    pre-built chunks).
    """
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nTried a new book", chat="grp", user="alice", msg_id="1")
    _ingest(store, "2026-05-09\nAnother book chapter", chat="grp", user="bob", msg_id="2")
    _ingest(store, "2026-05-09\nWalked the dog", chat="grp", user="carol", msg_id="3")

    result = _query_service(store).answer(_ask("book", chat="grp"))

    # Both "book" lines are surfaced; the off-topic dog line is not.
    matched = {e.chunk_text for e in result.evidence}
    assert matched == {"Tried a new book", "Another book chapter"}
    # Distinct contributors are preserved through retrieval into the context.
    assert _grounding_authors(result) == {"alice", "bob"}


# === Group B: multi-diary on one instance (N chats -> N communities) =========


def test_distinct_chats_are_isolated_communities_through_the_seam() -> None:
    """N distinct chats -> N isolated communities; ``/ask`` never crosses over.

    Composes with ``test_query_service.test_cross_chat_isolation`` but asserts
    at grouped granularity (multiple authors per community) and routes scope
    through ``resolve_community_id``.
    """
    store = MockDomainStore()
    # fam-A: two senders, both with a "book" line.
    _ingest(store, "2026-05-09\nFamily A book", chat="fam-A", user="alice", msg_id="1")
    _ingest(store, "2026-05-09\nA second book entry", chat="fam-A", user="bob", msg_id="2")
    # fam-B: its own "book" line.
    _ingest(store, "2026-05-09\nFamily B book", chat="fam-B", user="carol", msg_id="3")
    query = _query_service(store)

    result_a = query.answer(_ask("book", chat="fam-A"))
    result_b = query.answer(_ask("book", chat="fam-B"))

    a_texts = {e.chunk_text for e in result_a.evidence}
    b_texts = {e.chunk_text for e in result_b.evidence}
    assert a_texts == {"Family A book", "A second book entry"}
    assert b_texts == {"Family B book"}
    # No cross-community leakage in either direction.
    assert "Family B book" not in a_texts
    assert "Family A book" not in b_texts
    assert _grounding_authors(result_a) == {"alice", "bob"}
    assert _grounding_authors(result_b) == {"carol"}


def test_seam_maps_grouped_senders_to_one_community_and_isolates_chats() -> None:
    """Seam-level pin tying the message factories to ``resolve_community_id``.

    Distinct senders in one chat resolve to one ``community_id``; distinct
    chats resolve to distinct ``community_id`` values.
    """
    grouped = {
        _note("x", chat="grp", user=u, msg_id=m).community_id
        for u, m in (("alice", "1"), ("bob", "2"), ("carol", "3"))
    }
    assert grouped == {resolve_community_id("grp")}
    assert resolve_community_id("fam-A") != resolve_community_id("fam-B")


# === Group C: cross-community read isolation at grouped granularity ==========


def test_sources_cache_does_not_leak_across_communities() -> None:
    """A grouped ``/ask`` cache in one community is invisible to another.

    Re-asserts cross-community isolation of the dispatcher ``/sources`` cache
    at grouped granularity. This composes with the broader fail-closed read
    coverage in ``tests/test_read_access_isolation.py`` (by-id / trace reads)
    and the per-community cache coverage in
    ``tests/test_dispatcher_sources.py::test_two_family_caches_are_independent``.
    """
    store = MockDomainStore()
    dispatcher = _dispatcher(store)
    dispatcher.dispatch(
        _note("2026-05-09\nTried a new book", chat="fam-A", user="alice", msg_id="1")
    )
    dispatcher.dispatch(_ask("book", chat="fam-A"))

    # A community with no prior /ask sees nothing — no leak from fam-A.
    leaked = dispatcher.dispatch(_sources(chat="fam-B"))
    assert leaked.source_chunks is None
    assert leaked.metadata["returned"] == "0"

    # The owning community still sees its own selected chunks.
    own = dispatcher.dispatch(_sources(chat="fam-A"))
    assert own.source_chunks is not None
    assert {c.chunk_text for c in own.source_chunks} == {"Tried a new book"}
