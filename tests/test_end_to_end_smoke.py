"""End-to-end webhook smoke: /note then /ask via TestClient.

Each test wires a fresh ``MockDiaryStore`` + ``Dispatcher`` into the
FastAPI app via ``app.dependency_overrides`` so per-test state is
isolated from the module-level singleton in ``webhook.py``. The
``QueryService`` runs the baseline hybrid path (D-025): on the mock
backend the sparse leg matches via token overlap and the dense leg
matches only on identical text (mock embeddings encode text identity).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from diary_rag.adapters.answers import MockChatClient
from diary_rag.adapters.embeddings import MockEmbeddingClient
from diary_rag.adapters.telegram.webhook import get_dispatcher
from diary_rag.app import create_app
from diary_rag.config import Settings
from diary_rag.core.answers import ChatClient, ChatResponse
from diary_rag.core.diary import FallbackMode
from diary_rag.core.diary.answer_prompt import AnswerPrompt
from diary_rag.services import DiaryService, Dispatcher, ExportService, QueryService
from diary_rag.storage.mock import MockDiaryStore


def _settings() -> Settings:
    return Settings(_env_file=None, telegram_webhook_secret="test-secret")  # type: ignore[call-arg]


def _client_with_fresh_store(
    *, chat_client: ChatClient | None = None
) -> tuple[TestClient, MockDiaryStore]:
    store = MockDiaryStore()
    embed = MockEmbeddingClient()
    chat: ChatClient = chat_client if chat_client is not None else MockChatClient()
    settings = _settings()
    dispatcher = Dispatcher(
        DiaryService(store, embedding_client=embed),
        QueryService(store, store, embed, chat),
        ExportService(store),
        settings,
    )
    app = create_app(settings)
    app.dependency_overrides[get_dispatcher] = lambda: dispatcher
    return TestClient(app), store


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


def test_entry_then_ask_returns_grounded_reply_with_date() -> None:
    client, store = _client_with_fresh_store()

    entry_resp = _post(
        client,
        _update("/note 2026-05-09\nHad a calm morning\nTried a new book", update_id=1),
    )
    assert entry_resp.status_code == 200
    assert entry_resp.json()["text"] == "Saved 2 events for 2026-05-09."
    assert store.len_chunks() == 2

    ask_resp = _post(client, _update("/ask book", update_id=2, message_id=2))
    assert ask_resp.status_code == 200
    body = ask_resp.json()
    assert body["method"] == "sendMessage"
    assert body["chat_id"] == 42
    # Slice 4.4 (D-036): reply body is the LLM answer_text (mock-deterministic),
    # followed by the unchanged retrieval trailer. Cited chunk text is not in
    # the default reply; /sources exposes it on demand.
    text = body["text"]
    assert text.startswith("Mock answer grounded in 1 diary chunk(s):")
    assert text.endswith("(hybrid retrieval — dense+sparse RRF)")
    assert "Found 1 memory" not in text
    assert "Tried a new book" not in text
    # Slice 3.5: successful /ask persists one Query row + retrieval hits.
    assert store.len_queries() == 1
    assert store.len_retrieval_hits() > 0
    # Slice 4.3a: successful /ask also persists one AnswerTrace.
    assert store.len_answer_traces() == 1
    persisted_query = next(iter(store._queries.values()))
    trace = store.get_answer_trace_for_query(persisted_query.query_id)
    assert trace is not None
    assert trace.fallback_mode is FallbackMode.NONE
    assert trace.answer_text  # mock chat produced a grounded answer


def test_ask_with_no_match_returns_no_evidence_fallback() -> None:
    client, store = _client_with_fresh_store()

    _post(client, _update("/note 2026-05-09\nMorning routine", update_id=1))
    resp = _post(client, _update("/ask snowstorm", update_id=2, message_id=2))

    assert resp.status_code == 200
    assert resp.json()["text"] == "No memories matched 'snowstorm'."
    # Slice 3.5: NO_EVIDENCE still persists one Query row with zero hits.
    assert store.len_queries() == 1
    assert store.len_retrieval_hits() == 0
    # Slice 4.3a: NO_EVIDENCE still persists one AnswerTrace, with no LLM call.
    assert store.len_answer_traces() == 1
    persisted_query = next(iter(store._queries.values()))
    trace = store.get_answer_trace_for_query(persisted_query.query_id)
    assert trace is not None
    assert trace.fallback_mode is FallbackMode.NO_EVIDENCE
    assert trace.context_chunk_ids == ()
    assert trace.answer_text == ""


def test_entry_with_invalid_first_line_returns_invalid_input_and_persists_source() -> None:
    client, store = _client_with_fresh_store()

    resp = _post(client, _update("/note not-a-date\nfoo", update_id=1))

    assert resp.status_code == 200
    assert resp.json()["text"] == (
        "Mock /note needs an ISO date (YYYY-MM-DD) on the first line. Got: 'not-a-date'."
    )
    assert store.len_sources() == 1
    assert store.len_entries() == 0
    assert store.len_chunks() == 0


def test_ask_before_any_entry_returns_no_evidence() -> None:
    client, _ = _client_with_fresh_store()

    resp = _post(client, _update("/ask anything", update_id=1))

    assert resp.status_code == 200
    assert resp.json()["text"] == "No memories matched 'anything'."


def test_dated_plain_text_is_ingested_as_entry_via_heuristic() -> None:
    client, store = _client_with_fresh_store()

    resp = _post(client, _update("2026-05-10\nLearned a new recipe\nWalked 5km", update_id=1))

    assert resp.status_code == 200
    assert resp.json()["text"] == (
        "Saved 2 events for 2026-05-10.\n" "(routed as note — send /note next time to be explicit)"
    )
    assert store.len_chunks() == 2


def test_question_plain_text_returns_grounded_reply_via_heuristic() -> None:
    client, _ = _client_with_fresh_store()

    _post(client, _update("/note 2026-05-10\nLearned a new recipe\nWalked 5km", update_id=1))
    resp = _post(client, _update("recipe?", update_id=2, message_id=2))

    assert resp.status_code == 200
    text = resp.json()["text"]
    # Slice 4.4 (D-036): answer_text body + retrieval trailer + heuristic marker.
    assert text.startswith("Mock answer grounded in 1 diary chunk(s):")
    assert "(hybrid retrieval — dense+sparse RRF)" in text
    assert text.endswith("(routed as question — send /ask next time to be explicit)")
    assert "Found 1 memory" not in text
    assert "Learned a new recipe" not in text


def test_ambiguous_plain_text_persists_as_draft_under_no_command_default() -> None:
    client, store = _client_with_fresh_store()

    resp = _post(client, _update("recipe yesterday", update_id=1))

    assert resp.status_code == 200
    body = resp.json()
    assert body["text"].startswith("Stored as draft")
    assert "/note" in body["text"]
    assert store.len_sources() == 1
    assert store.len_entries() == 0
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
    assert store.len_entries() == 0
    assert store.len_chunks() == 0
    assert store.len_embeddings() == 0


def test_replayed_draft_returns_same_reply_and_does_not_duplicate(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, store = _client_with_fresh_store()
    payload = _update("recipe yesterday", update_id=1, message_id=77)

    with caplog.at_level(logging.INFO, logger="diary_rag.adapters.telegram.webhook"):
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


def test_replayed_entry_returns_same_reply_and_does_not_duplicate(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, store = _client_with_fresh_store()
    payload = _update(
        "/note 2026-05-09\nHad a calm morning\nTried a new book",
        update_id=1,
        message_id=99,
    )

    with caplog.at_level(logging.INFO, logger="diary_rag.adapters.telegram.webhook"):
        first = _post(client, payload)
        second = _post(client, payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert second.json()["text"] == "Saved 2 events for 2026-05-09."
    assert store.len_sources() == 1
    assert store.len_entries() == 1
    assert store.len_chunks() == 2

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
    assert store.len_entries() == 2
    assert store.len_chunks() == 5


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

    with caplog.at_level(logging.INFO, logger="diary_rag.services.query_service"):
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
    trace = store.get_answer_trace_for_query(persisted_query.query_id)
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
