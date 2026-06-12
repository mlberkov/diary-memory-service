"""Routed-chat milestone characterization suite (RC closure / D-108..D-111).

Pins the milestone contract end-to-end at ``RoutedChatService``
granularity: an inbound natural-language question is classified into one
of the four routes — ``notes_lookup`` / ``notes_plus_model`` /
``notes_plus_knowledge`` / ``model_only`` (product register
``diary_lookup`` / ``diary_plus_llm`` / ``diary_plus_web`` /
``general_llm``) — and answered under explicit per-segment provenance
(generalized I-9): notes claims cite chunk ids, knowledge claims cite
the offered refs verbatim, model knowledge stays in its own labeled
field. Every call persists exactly one ``ChatRouteDecision`` row with
the requested-vs-effective distinction (R-6); the mixed routes add
their rewrite / knowledge-search trace rows; community scoping (R-3 /
R-8) holds on every route; classification failure and the empty
question default cause-neutrally to ``notes_lookup``.

Harness boundary: parametrized over **mock + PG-gated postgres**
(``MEMORY_RAG_PG_TEST_DSN``); sqlite is excluded — its retrieval legs
raise ``NotImplementedError`` (D-022 / D-025). Providers are mock-mode
(``MockEmbeddingClient`` / ``MockChatClient`` / mock classifier,
rewriters, and knowledge source); the REAL-backend round trip is the
operator drill in ``docs/RUNBOOK.md``, not a gated test.

These are characterization tests over current behavior — they must pass
against production code as-is. They compose with (and do not re-run)
the per-packet coverage:

- ``tests/test_routed_chat_service.py`` — RC-2 classifier/dispatch
  contours, ``model_only`` grading, decision-row shape.
- ``tests/test_routed_chat_notes_plus_model.py`` — RC-3 rewrite +
  enrichment contours, escalation clause, scoping inside enrichment.
- ``tests/test_routed_chat_notes_plus_knowledge.py`` — RC-4 outward
  rewrite + search contours, degradation, trace chronology.
- ``tests/test_dispatcher_chat.py`` — the reply-rendering surface and
  its pinned literals.
- ``tests/test_storage_chat_route_decisions.py`` /
  ``tests/test_storage_chat_query_rewrites.py`` /
  ``tests/test_storage_chat_knowledge_searches.py`` — per-backend trace
  seams.
- ``tests/test_postgres_migrations.py`` — 0007..0009 upgrades.
- ``tests/test_end_to_end_smoke.py`` — webhook-level ``/chat`` round
  trips.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from memory_rag.adapters.answers import MockChatClient
from memory_rag.adapters.chat_routing import (
    MockOutwardRewriter,
    MockQueryRewriter,
    MockRouteClassifier,
)
from memory_rag.adapters.embeddings import MockEmbeddingClient
from memory_rag.adapters.knowledge import MockKnowledgeSource
from memory_rag.adapters.telegram.community import resolve_community_id
from memory_rag.core.chat import ChatRoute, KnowledgeExcerpt
from memory_rag.core.domain import FallbackMode
from memory_rag.core.routing import InboundMessage, RouteKind
from memory_rag.services import DomainService, QueryService, RoutedChatService
from memory_rag.storage.mock import MockDomainStore

if TYPE_CHECKING:
    from memory_rag.storage.postgres import PostgresDomainStore

PG_DSN = os.environ.get("MEMORY_RAG_PG_TEST_DSN")

_EXCERPTS = (
    KnowledgeExcerpt(ref="https://example.org/naps", title="Nap science", text="nap facts"),
)


def _truncate(dsn: str) -> None:
    # Wider than the leg-level suites' truncate: routed chat also persists
    # decision / rewrite / knowledge-search rows.
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE chat_knowledge_searches, chat_query_rewrites, chat_route_decisions, "
            "answer_traces, retrieval_hits, queries, embedding_records, "
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
        pg = PostgresDomainStore(PG_DSN)
        try:
            _truncate(PG_DSN)
            yield pg
        finally:
            pg.close()


def _chat_msg(question: str, *, chat: str = "42", msg_id: str = "500") -> InboundMessage:
    community_id = resolve_community_id(chat)
    return InboundMessage(
        external_message_id=msg_id,
        external_chat_id=chat,
        external_user_id="7",
        community_id=community_id,
        text=f"/chat {question}",
        route=RouteKind.CHAT,
        received_at=datetime.now(tz=UTC),
        route_source="command",
        payload=question,
    )


def _ingest(
    store: MockDomainStore | PostgresDomainStore, payload: str, *, chat: str = "42", msg_id: str
) -> None:
    DomainService(store, embedding_client=MockEmbeddingClient()).ingest(
        InboundMessage(
            external_message_id=msg_id,
            external_chat_id=chat,
            external_user_id="7",
            community_id=resolve_community_id(chat),
            text=f"/note {payload}",
            route=RouteKind.NOTE,
            received_at=datetime.now(tz=UTC),
            route_source="command",
            payload=payload,
        )
    )


def _wire(store: MockDomainStore | PostgresDomainStore) -> RoutedChatService:
    """The full RC-4 wiring: in-band-steerable classifier, both rewriters,
    and a scripted knowledge source — the get_dispatcher composition shape."""
    chat = MockChatClient()
    query = QueryService(store, store, MockEmbeddingClient(), chat)
    return RoutedChatService(
        MockRouteClassifier(),
        query,
        chat,
        store,
        rewriter=MockQueryRewriter(),
        knowledge_source=MockKnowledgeSource(excerpts=_EXCERPTS),
        outward_rewriter=MockOutwardRewriter(),
    )


# === All four routes end-to-end ===============================================


def test_notes_lookup_route_answers_grounded_and_records_the_decision(
    store: MockDomainStore | PostgresDomainStore,
) -> None:
    """``diary_lookup``: the existing grounded ask, unchanged, behind the
    routed entry — cited notes provenance, one decision row (R-6)."""
    _ingest(store, "2026-05-09\nTried a new book", msg_id="1")
    service = _wire(store)

    result = service.chat(_chat_msg("book"))

    assert result.requested_route is ChatRoute.NOTES_LOOKUP
    assert result.effective_route is ChatRoute.NOTES_LOOKUP
    assert result.answer.fallback is FallbackMode.NONE
    assert result.answer.cited_chunk_ids != ()
    assert result.answer.model_text is None
    assert result.answer.knowledge_text is None
    decision = store.get_chat_route_decision(result.decision_id, community_id="42")
    assert decision is not None
    assert decision.query_id is not None


def test_model_only_route_answers_unretrieved_with_model_provenance(
    store: MockDomainStore | PostgresDomainStore,
) -> None:
    """``general_llm``: a direct model answer with no retrieval and no
    notes claim — the model plane is the only populated provenance."""
    service = _wire(store)

    result = service.chat(_chat_msg("what is model_only awareness"))

    assert result.effective_route is ChatRoute.MODEL_ONLY
    assert result.answer.fallback is FallbackMode.NONE
    assert result.answer.answer_text == "Mock model-knowledge answer (no notes consulted)."
    assert result.answer.cited_chunk_ids == ()
    assert result.answer.evidence == []
    decision = store.get_chat_route_decision(result.decision_id, community_id="42")
    assert decision is not None
    assert decision.query_id is not None
    assert store.get_retrieval_hits_for_query(decision.query_id, community_id="42") == []


def test_notes_plus_model_route_carries_both_planes_and_a_rewrite_row(
    store: MockDomainStore | PostgresDomainStore,
) -> None:
    """``diary_plus_llm``: cited notes plane + labeled model plane, plus
    the rewrite trace row."""
    _ingest(store, "2026-05-09\nTried a notes_plus_model book", msg_id="1")
    service = _wire(store)

    result = service.chat(_chat_msg("notes_plus_model book"))

    assert result.effective_route is ChatRoute.NOTES_PLUS_MODEL
    assert result.answer.fallback is FallbackMode.NONE
    assert result.answer.cited_chunk_ids != ()
    assert result.answer.model_text == "Mock general-knowledge segment."
    assert result.answer.knowledge_text is None
    rewrite = store.get_chat_query_rewrite_for_decision(result.decision_id, community_id="42")
    assert rewrite is not None


def test_notes_plus_knowledge_route_carries_all_three_planes_and_both_trace_rows(
    store: MockDomainStore | PostgresDomainStore,
) -> None:
    """``diary_plus_web``: cited notes plane + ref-cited knowledge plane +
    labeled model plane, plus the rewrite and knowledge-search rows."""
    _ingest(store, "2026-05-09\nTried a notes_plus_knowledge nap", msg_id="1")
    service = _wire(store)

    result = service.chat(_chat_msg("notes_plus_knowledge nap"))

    assert result.effective_route is ChatRoute.NOTES_PLUS_KNOWLEDGE
    answer = result.answer
    assert answer.fallback is FallbackMode.NONE
    assert answer.cited_chunk_ids != ()
    assert answer.knowledge_text is not None
    # Knowledge citations are the offered refs verbatim (generalized I-9).
    assert answer.knowledge_refs == ("https://example.org/naps",)
    assert answer.model_text == "Mock general-knowledge segment."
    rewrite = store.get_chat_query_rewrite_for_decision(result.decision_id, community_id="42")
    assert rewrite is not None
    search = store.get_chat_knowledge_search_for_decision(result.decision_id, community_id="42")
    assert search is not None
    assert search.provider_name == "mock"
    assert search.result_count == 1


# === Fallback policy + R-6 ====================================================


def test_an_empty_question_defaults_to_notes_lookup_with_no_requested_route(
    store: MockDomainStore | PostgresDomainStore,
) -> None:
    """D-108 fallback policy: no usable classification -> the default
    route, requested-vs-effective preserved on the decision row."""
    service = _wire(store)

    result = service.chat(_chat_msg("   "))

    assert result.requested_route is None
    assert result.effective_route is ChatRoute.NOTES_LOOKUP
    decision = store.get_chat_route_decision(result.decision_id, community_id="42")
    assert decision is not None
    assert decision.requested_route is None
    assert decision.effective_route is ChatRoute.NOTES_LOOKUP


# === Scoping (R-3 / R-8) across routed answers ================================


def test_routed_answers_never_cross_the_community_boundary(
    store: MockDomainStore | PostgresDomainStore,
) -> None:
    """I-7 / R-3 through the routed entry: community B's notes are
    unreachable from community A on both retrieval-backed routes."""
    _ingest(store, "2026-05-09\nTried a new book", chat="A", msg_id="1")
    _ingest(store, "2026-05-09\nSecret book of B", chat="B", msg_id="2")
    service = _wire(store)

    lookup = service.chat(_chat_msg("book", chat="A", msg_id="501"))
    enriched = service.chat(_chat_msg("notes_plus_knowledge book", chat="A", msg_id="502"))

    for result in (lookup, enriched):
        texts = {e.chunk_text for e in result.answer.evidence}
        assert "Secret book of B" not in texts


def test_every_route_writes_exactly_one_decision_row(
    store: MockDomainStore | PostgresDomainStore,
) -> None:
    """R-6 / R-11 uniformity: four calls, four decision rows, each
    readable only under its own community scope."""
    _ingest(store, "2026-05-09\nTried a notes_plus_model notes_plus_knowledge book", msg_id="1")
    service = _wire(store)

    decisions = [
        service.chat(_chat_msg("book", msg_id="510")).decision_id,
        service.chat(_chat_msg("what is model_only awareness", msg_id="511")).decision_id,
        service.chat(_chat_msg("notes_plus_model book", msg_id="512")).decision_id,
        service.chat(_chat_msg("notes_plus_knowledge book", msg_id="513")).decision_id,
    ]

    assert len(set(decisions)) == 4
    for decision_id in decisions:
        assert store.get_chat_route_decision(decision_id, community_id="42") is not None
        assert store.get_chat_route_decision(decision_id, community_id="elsewhere") is None
