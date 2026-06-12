"""End-to-end webhook smoke: /note then /ask via TestClient.

Each test wires a fresh ``MockDomainStore`` + ``Dispatcher`` into the
FastAPI app via ``app.dependency_overrides`` so per-test state is
isolated from the module-level singleton in ``webhook.py``. The
``QueryService`` runs the baseline hybrid path (D-025): on the mock
backend the sparse leg matches via token overlap and the dense leg
matches only on identical text (mock embeddings encode text identity).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from memory_rag.adapters.answers import MockChatClient
from memory_rag.adapters.chat_routing import (
    MockOutwardRewriter,
    MockQueryRewriter,
    MockRouteClassifier,
)
from memory_rag.adapters.embeddings import MockEmbeddingClient
from memory_rag.adapters.knowledge import MockKnowledgeSource
from memory_rag.adapters.telegram.webhook import get_dispatcher
from memory_rag.app import create_app
from memory_rag.config import Settings
from memory_rag.core.answers import ChatClient, ChatResponse
from memory_rag.core.domain import FallbackMode
from memory_rag.core.domain.answer_prompt import AnswerPrompt
from memory_rag.services import (
    Dispatcher,
    DomainService,
    ExportService,
    QueryService,
    RoutedChatService,
)
from memory_rag.storage.mock import MockDomainStore


def _settings() -> Settings:
    return Settings(_env_file=None, telegram_webhook_secret="test-secret")  # type: ignore[call-arg]


def _client_with_fresh_store(
    *,
    chat_client: ChatClient | None = None,
    knowledge_source: MockKnowledgeSource | None = None,
) -> tuple[TestClient, MockDomainStore]:
    store = MockDomainStore()
    embed = MockEmbeddingClient()
    chat: ChatClient = chat_client if chat_client is not None else MockChatClient()
    settings = _settings()
    query = QueryService(store, store, embed, chat)
    dispatcher = Dispatcher(
        DomainService(store, embedding_client=embed),
        query,
        ExportService(store),
        settings,
        routed_chat=RoutedChatService(
            MockRouteClassifier(),
            query,
            chat,
            store,
            rewriter=MockQueryRewriter(),
            knowledge_source=knowledge_source,
            outward_rewriter=(MockOutwardRewriter() if knowledge_source is not None else None),
        ),
    )
    app = create_app(settings)
    app.dependency_overrides[get_dispatcher] = lambda: dispatcher
    return TestClient(app), store


def _today_iso(update_id: int = 1) -> str:
    # Mirror the webhook's received_at derivation (webhook.py:
    # datetime.fromtimestamp(message.date, tz=UTC)) so the today-default
    # (D-085) assertions are computed, not hardcoded.
    return datetime.fromtimestamp(1715300000 + update_id, tz=UTC).date().isoformat()


def _post(client: TestClient, payload: dict[str, Any]) -> Any:
    return client.post(
        "/telegram/webhook",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
    )


def _update(
    text: str,
    *,
    update_id: int = 1,
    message_id: int = 1,
    chat_id: int = 42,
    edit_date: int | None = None,
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "message_id": message_id,
        "date": 1715300000 + update_id,
        "chat": {"id": chat_id},
        "from": {"id": 7},
        "text": text,
    }
    if edit_date is not None:
        msg["edit_date"] = edit_date
    return {
        "update_id": update_id,
        "message": msg,
    }


def test_note_then_ask_returns_grounded_reply_with_date() -> None:
    client, store = _client_with_fresh_store()

    note_resp = _post(
        client,
        _update("/note 2026-05-09\nHad a calm morning\nTried a new book", update_id=1),
    )
    assert note_resp.status_code == 200
    assert note_resp.json()["text"] == "Saved your note for 2026-05-09."
    assert store.len_chunks() == 1

    ask_resp = _post(client, _update("/ask book", update_id=2, message_id=2))
    assert ask_resp.status_code == 200
    body = ask_resp.json()
    assert body["method"] == "sendMessage"
    assert body["chat_id"] == 42
    # Reply body is the LLM answer_text (mock-deterministic); the success-case
    # `(hybrid retrieval — dense+sparse RRF)` trailer is no longer appended.
    # Cited chunk text is not in the default reply; /sources exposes it on demand.
    text = body["text"]
    assert text.startswith("Mock answer grounded in 1 diary chunk(s):")
    assert "dense+sparse RRF" not in text
    assert "hybrid retrieval" not in text
    # D-101: the `Contributors: …` footer was removed — the grounded /ask reply
    # is the answer_text alone (no footer, no adapter-composed display name).
    # /sources (cited-only, D-100) is the sole attribution surface.
    assert "Contributors:" not in text
    # No extra blank trailer line remains: the mock answer is single-line, so any
    # remnant `\n\n<trailer>` (e.g. the removed footer separator) would surface as
    # a double newline in the reply body.
    assert "\n\n" not in text
    assert "Found 1 memory" not in text
    assert "Tried a new book" not in text
    # Slice 3.5: successful /ask persists one Query row + retrieval hits.
    assert store.len_queries() == 1
    assert store.len_retrieval_hits() > 0
    # Slice 4.3a: successful /ask also persists one AnswerTrace.
    assert store.len_answer_traces() == 1
    persisted_query = next(iter(store._queries.values()))
    trace = store.get_answer_trace_for_query(
        persisted_query.query_id, community_id=persisted_query.community_id
    )
    assert trace is not None
    assert trace.fallback_mode is FallbackMode.NONE
    assert trace.answer_text  # mock chat produced a grounded answer


def test_ask_with_no_match_returns_no_evidence_fallback() -> None:
    client, store = _client_with_fresh_store()

    _post(client, _update("/note 2026-05-09\nMorning routine", update_id=1))
    resp = _post(client, _update("/ask snowstorm", update_id=2, message_id=2))

    assert resp.status_code == 200
    assert resp.json()["text"] == (
        "Nothing in your saved notes matched 'snowstorm'. "
        "Try rephrasing the question, or use words that appear in your notes."
    )
    # Slice 3.5: NO_EVIDENCE still persists one Query row with zero hits.
    assert store.len_queries() == 1
    assert store.len_retrieval_hits() == 0
    # Slice 4.3a: NO_EVIDENCE still persists one AnswerTrace, with no LLM call.
    assert store.len_answer_traces() == 1
    persisted_query = next(iter(store._queries.values()))
    trace = store.get_answer_trace_for_query(
        persisted_query.query_id, community_id=persisted_query.community_id
    )
    assert trace is not None
    assert trace.fallback_mode is FallbackMode.NO_EVIDENCE
    assert trace.context_chunk_ids == ()
    assert trace.answer_text == ""


def test_note_with_dateless_first_line_defaults_to_today_and_saves() -> None:
    # D-085: an explicit /note whose first line is not a date defaults to the
    # received_at date; the previously-first line and the rest become the body
    # of the single note chunk (I-5 / D-106).
    client, store = _client_with_fresh_store()

    resp = _post(client, _update("/note not-a-date\nfoo", update_id=1))

    assert resp.status_code == 200
    assert resp.json()["text"] == f"Saved your note for {_today_iso(1)}."
    assert store.len_sources() == 1
    assert store.len_notes() == 1
    assert store.len_chunks() == 1


def test_empty_note_returns_invalid_input_and_persists_source() -> None:
    # D-085: the today-default fires only when there IS a non-empty first
    # line. A bare /note keeps the INVALID_INPUT contour and de-leaked wording,
    # and the raw source is still persisted before the parse decision.
    client, store = _client_with_fresh_store()

    resp = _post(client, _update("/note", update_id=1))

    assert resp.status_code == 200
    text = resp.json()["text"]
    assert text == "First line must be a date like 2026-05-09. Got: ''."
    # D-070: the dev-leaking "Mock" label is no longer in the user-facing reply.
    assert "Mock" not in text
    assert store.len_sources() == 1
    assert store.len_notes() == 0
    assert store.len_chunks() == 0


def test_explicit_note_with_slash_separated_yyyy_first_is_normalized_and_saved() -> None:
    # D-070: explicit /note path normalizes a six-form near-ISO whitelist
    # to canonical YYYY-MM-DD before the strict parser runs.
    client, store = _client_with_fresh_store()

    resp = _post(client, _update("/note 2026/05/09\nfoo", update_id=1))

    assert resp.status_code == 200
    assert resp.json()["text"] == "Saved your note for 2026-05-09."
    assert store.len_chunks() == 1


def test_explicit_note_with_dd_first_uses_dd_mm_yyyy_convention_pin() -> None:
    # D-070 convention pin: DD-first inputs are always interpreted as
    # DD/MM/YYYY by intentional product convention. 05/09/2026 must
    # therefore be saved as 2026-09-05 (5 September 2026), never as
    # 2026-05-09 (9 May 2026). A future "let's allow MM/DD/YYYY too"
    # change cannot land without flipping this red.
    client, store = _client_with_fresh_store()

    resp = _post(client, _update("/note 05/09/2026\nfoo", update_id=1))

    assert resp.status_code == 200
    assert resp.json()["text"] == "Saved your note for 2026-09-05."
    assert store.len_chunks() == 1


def test_explicit_note_with_dot_separated_date_is_normalized_and_saved() -> None:
    client, store = _client_with_fresh_store()

    resp = _post(client, _update("/note 09.05.2026\nfoo", update_id=1))

    assert resp.status_code == 200
    assert resp.json()["text"] == "Saved your note for 2026-05-09."
    assert store.len_chunks() == 1


def test_explicit_note_with_unpadded_date_defaults_to_today() -> None:
    # The near-ISO whitelist is exact (D-070): 2026-5-9 is not a recognized
    # date, so under D-085 it is a non-date first line that defaults to today
    # and becomes part of the note body rather than being rejected.
    client, store = _client_with_fresh_store()

    resp = _post(client, _update("/note 2026-5-9\nfoo", update_id=1))

    assert resp.status_code == 200
    assert resp.json()["text"] == f"Saved your note for {_today_iso(1)}."
    assert store.len_notes() == 1
    assert store.len_chunks() == 1


def test_command_less_dated_plain_text_routes_to_draft_floor() -> None:
    # D-079 contract: command-less plain text routes only to the draft floor —
    # the heuristic plain-text NOTE auto-route is retired. A dated first line
    # (even a near-ISO form) does not auto-promote to a NOTE.
    client, store = _client_with_fresh_store()

    resp = _post(client, _update("2026/05/09\nfoo", update_id=1))

    assert resp.status_code == 200
    text = resp.json()["text"]
    assert text.startswith("Stored as draft")
    assert store.len_notes() == 0
    assert store.len_chunks() == 0


def test_ask_before_any_note_returns_no_evidence() -> None:
    client, _ = _client_with_fresh_store()

    resp = _post(client, _update("/ask anything", update_id=1))

    assert resp.status_code == 200
    assert resp.json()["text"] == (
        "Nothing in your saved notes matched 'anything'. "
        "Try rephrasing the question, or use words that appear in your notes."
    )


def test_dated_plain_text_is_stored_as_draft() -> None:
    # D-079: command-less dated plain text is persisted raw as a draft, not
    # auto-promoted to a NOTE — no parse, no chunks, no routing marker.
    client, store = _client_with_fresh_store()

    resp = _post(client, _update("2026-05-10\nLearned a new recipe\nWalked 5km", update_id=1))

    assert resp.status_code == 200
    text = resp.json()["text"]
    assert text.startswith("Stored as draft")
    assert "routed as note" not in text
    assert store.len_chunks() == 0
    assert store.len_notes() == 0


def test_question_plain_text_is_stored_as_draft() -> None:
    # D-079: command-less question-shaped plain text is persisted raw as a
    # draft, not auto-routed to ASK — no retrieval, no answer, no marker.
    client, store = _client_with_fresh_store()

    _post(client, _update("/note 2026-05-10\nLearned a new recipe\nWalked 5km", update_id=1))
    resp = _post(client, _update("recipe?", update_id=2, message_id=2))

    assert resp.status_code == 200
    text = resp.json()["text"]
    assert text.startswith("Stored as draft")
    assert "routed as question" not in text
    assert "Mock answer grounded" not in text


def test_ambiguous_plain_text_persists_as_draft_under_no_command_default() -> None:
    client, store = _client_with_fresh_store()

    resp = _post(client, _update("recipe yesterday", update_id=1))

    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "Stored as draft."
    assert store.len_sources() == 1
    assert store.len_notes() == 0
    assert store.len_chunks() == 0


def test_no_command_plain_text_persists_as_draft_and_skips_enrichment() -> None:
    client, store = _client_with_fresh_store()

    # No leading command. The webhook routes via the heuristic to DRAFT under
    # the no-command-→-draft floor (the only path to a draft after D-030).
    resp = _post(client, _update("Not sure yet, keep it raw", update_id=1))

    assert resp.status_code == 200
    body = resp.json()
    assert body["text"].startswith("Stored as draft")
    assert store.len_sources() == 1
    assert store.len_notes() == 0
    assert store.len_chunks() == 0
    assert store.len_embeddings() == 0


def test_replayed_draft_returns_same_reply_and_does_not_duplicate(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, store = _client_with_fresh_store()
    payload = _update("recipe yesterday", update_id=1, message_id=77)

    with caplog.at_level(logging.INFO, logger="memory_rag.adapters.telegram.webhook"):
        first = _post(client, payload)
        second = _post(client, payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["text"].startswith("Stored as draft")
    assert second.json()["text"].startswith("Stored as draft")
    assert store.len_sources() == 1

    paths = [line for line in caplog.text.splitlines() if "telegram.webhook" in line]
    assert any("lifecycle=draft" in line and "effective_path=fresh" in line for line in paths)
    assert any("lifecycle=draft" in line and "effective_path=replay" in line for line in paths)


def test_replayed_note_returns_same_reply_and_does_not_duplicate(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, store = _client_with_fresh_store()
    payload = _update(
        "/note 2026-05-09\nHad a calm morning\nTried a new book",
        update_id=1,
        message_id=99,
    )

    with caplog.at_level(logging.INFO, logger="memory_rag.adapters.telegram.webhook"):
        first = _post(client, payload)
        second = _post(client, payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert second.json()["text"] == "Saved your note for 2026-05-09."
    assert store.len_sources() == 1
    assert store.len_notes() == 1
    assert store.len_chunks() == 1

    paths = [line for line in caplog.text.splitlines() if "telegram.webhook" in line]
    assert any("effective_path=fresh" in line for line in paths)
    assert any("effective_path=replay" in line for line in paths)


def test_edited_message_is_distinct_state_from_original() -> None:
    client, store = _client_with_fresh_store()

    first = _post(
        client,
        _update("/note 2026-05-09\nA\nB", update_id=1, message_id=99),
    )
    edited = _post(
        client,
        _update(
            "/note 2026-05-09\nA\nB\nC",
            update_id=2,
            message_id=99,
            edit_date=1715300100,
        ),
    )

    assert first.status_code == 200
    assert edited.status_code == 200
    assert store.len_sources() == 2
    assert store.len_notes() == 2
    # Each note is one chunk now (I-5 / D-106): the original body "A\nB" and
    # the edited body "A\nB\nC" are distinct single chunks.
    assert store.len_chunks() == 2


class _WeakEvidenceChatClient:
    """Stub chat client that emits ``uncertainty="uncertain"`` for the smoke test."""

    @property
    def model_name(self) -> str:
        return "stub-uncertain"

    def complete(self, prompt: AnswerPrompt) -> ChatResponse:
        raw = json.dumps(
            {
                "answer_text": "Could be the book or the routine.",
                "cited_chunk_ids": list(prompt.cited_chunk_ids),
                "uncertainty": "uncertain",
            }
        )
        return ChatResponse(
            raw_text=raw,
            model_name=self.model_name,
            token_counts={"prompt": 9, "completion": 6},
            latency_ms=21,
        )


def test_weak_evidence_marker_surfaces_trailer_and_persists_trace(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Slice 4.3b: an LLM ``uncertain`` marker grades the call as WEAK_EVIDENCE end-to-end."""
    client, store = _client_with_fresh_store(chat_client=_WeakEvidenceChatClient())

    _post(client, _update("/note 2026-05-09\nTried a new book", update_id=1))

    with caplog.at_level(logging.INFO, logger="memory_rag.services.query_service"):
        resp = _post(client, _update("/ask book", update_id=2, message_id=2))

    assert resp.status_code == 200
    text = resp.json()["text"]
    assert "(weak evidence — model expressed uncertainty)" in text
    # Slice 4.4 (D-036): body is the LLM answer_text, not the evidence line.
    assert "Could be the book or the routine." in text
    assert "Tried a new book" not in text

    # Persisted Query.fallback matches AnswerTrace.fallback_mode (D-035).
    persisted_query = next(iter(store._queries.values()))
    assert persisted_query.fallback is FallbackMode.WEAK_EVIDENCE
    trace = store.get_answer_trace_for_query(
        persisted_query.query_id, community_id=persisted_query.community_id
    )
    assert trace is not None
    assert trace.fallback_mode is FallbackMode.WEAK_EVIDENCE
    assert trace.answer_text == "Could be the book or the routine."
    assert trace.model_name == "stub-uncertain"
    assert trace.latency_ms == 21

    # Log line carries the new fallback value.
    assert "fallback=weak_evidence" in caplog.text


def test_sources_after_ask_returns_selected_chunks() -> None:
    """Slice 4.4 (D-036): /sources after a successful /ask renders the selected chunks."""
    client, _ = _client_with_fresh_store()

    _post(
        client,
        _update("/note 2026-05-09\nHad a calm morning\nTried a new book", update_id=1),
    )
    _post(client, _update("/ask book", update_id=2, message_id=2))

    resp = _post(client, _update("/sources", update_id=3, message_id=3))

    assert resp.status_code == 200
    body = resp.json()
    # Outbound delivery happens via send_message; the webhook returns {}.
    assert body == {}


def test_sources_without_prior_ask_returns_fail_closed_reply() -> None:
    """Slice 4.4 (D-036): /sources with no cached selected-chunks fails closed."""
    client, _ = _client_with_fresh_store()

    resp = _post(client, _update("/sources", update_id=1))

    assert resp.status_code == 200
    text = resp.json()["text"]
    assert text == "No selected chunks available — ask a question with /ask first."


def test_chat_model_only_round_trip_returns_labeled_reply() -> None:
    """RC-2 (D-108): a /chat question classified model_only (in-band mock
    steering) answers from model knowledge with the explicit provenance
    trailer, persisting its own Query + AnswerTrace + decision row."""
    client, store = _client_with_fresh_store()

    resp = _post(client, _update("/chat what is model_only awareness", update_id=1))

    assert resp.status_code == 200
    assert resp.json()["text"] == (
        "Mock model-knowledge answer (no notes consulted)."
        "\n\n(model knowledge — not from your saved notes)"
    )
    assert store.len_queries() == 1
    assert store.len_answer_traces() == 1
    assert store.len_chat_route_decisions() == 1
    assert store.len_retrieval_hits() == 0


def test_chat_notes_lookup_round_trip_matches_the_ask_reply() -> None:
    """RC-2 (D-108): a /chat question classified notes_lookup answers
    byte-identically to /ask for the same store, and the new wiring leaves
    the /ask reply itself unchanged."""
    client, store = _client_with_fresh_store()

    _post(client, _update("/note 2026-05-09\nTried a new book", update_id=1))
    chat_resp = _post(client, _update("/chat book", update_id=2, message_id=2))
    ask_resp = _post(client, _update("/ask book", update_id=3, message_id=3))

    assert chat_resp.status_code == 200
    assert ask_resp.status_code == 200
    assert chat_resp.json()["text"] == ask_resp.json()["text"]
    assert ask_resp.json()["text"].startswith("Mock answer grounded in 1 diary chunk(s):")
    # One decision row for the /chat call; none for the /ask call.
    assert store.len_chat_route_decisions() == 1


def test_chat_notes_plus_model_round_trip_returns_segmented_reply() -> None:
    """RC-3 (D-108): a /chat question classified notes_plus_model (in-band
    mock steering) answers with both labeled segments, persisting Query +
    hits + AnswerTrace + decision row + rewrite row."""
    client, store = _client_with_fresh_store()

    _post(client, _update("/note 2026-05-09\nTried a notes_plus_model book", update_id=1))
    resp = _post(client, _update("/chat notes_plus_model book", update_id=2, message_id=2))

    assert resp.status_code == 200
    text = resp.json()["text"]
    assert text.startswith("From your saved notes:\n")
    assert "(model knowledge — not from your saved notes)" in text
    assert text.endswith("Mock general-knowledge segment.")
    assert store.len_queries() == 1
    assert store.len_answer_traces() == 1
    assert store.len_chat_route_decisions() == 1
    assert store.len_chat_query_rewrites() == 1
    assert store.len_retrieval_hits() > 0


def test_chat_notes_plus_knowledge_round_trip_returns_three_segment_reply() -> None:
    """RC-4 (D-108): a /chat question classified notes_plus_knowledge
    (in-band mock steering) answers with all three labeled segments —
    the web segment citing its refs verbatim — persisting Query + hits +
    AnswerTrace + decision row + rewrite row + knowledge-search row."""
    from memory_rag.core.chat import KnowledgeExcerpt

    knowledge = MockKnowledgeSource(
        excerpts=(KnowledgeExcerpt(ref="https://example.org/naps", title="Naps", text="nap facts"),)
    )
    client, store = _client_with_fresh_store(knowledge_source=knowledge)

    _post(client, _update("/note 2026-05-09\nTried a notes_plus_knowledge nap", update_id=1))
    resp = _post(client, _update("/chat notes_plus_knowledge nap", update_id=2, message_id=2))

    assert resp.status_code == 200
    text = resp.json()["text"]
    assert text.startswith("From your saved notes:\n")
    assert "From the web:" in text
    assert "https://example.org/naps" in text
    assert "(model knowledge — not from your saved notes)" in text
    assert text.endswith("Mock general-knowledge segment.")
    assert store.len_queries() == 1
    assert store.len_answer_traces() == 1
    assert store.len_chat_route_decisions() == 1
    assert store.len_chat_query_rewrites() == 1
    assert store.len_chat_knowledge_searches() == 1
    assert store.len_retrieval_hits() > 0


def test_chat_notes_plus_model_round_trip_degrades_honestly_on_empty_corpus() -> None:
    """RC-3 (D-108): with nothing ingested, the reply states the empty
    diary evidence strictly before any model content."""
    client, store = _client_with_fresh_store()

    resp = _post(client, _update("/chat notes_plus_model what games suit him", update_id=1))

    assert resp.status_code == 200
    assert resp.json()["text"] == (
        "Nothing in your saved notes covers this — here's general information instead."
        "\n\n(model knowledge — not from your saved notes)"
        "\nMock general-knowledge segment."
    )
    assert store.len_chat_query_rewrites() == 1
