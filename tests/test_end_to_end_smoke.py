"""End-to-end webhook smoke: /entry then /ask via TestClient.

Each test wires a fresh ``MockDiaryStore`` + ``Dispatcher`` into the
FastAPI app via ``app.dependency_overrides`` so per-test state is
isolated from the module-level singleton in ``webhook.py``. The
``QueryService`` runs the baseline hybrid path (D-025): on the mock
backend the sparse leg matches via token overlap and the dense leg
matches only on identical text (mock embeddings encode text identity).
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from diary_rag.adapters.embeddings import MockEmbeddingClient
from diary_rag.adapters.telegram.webhook import get_dispatcher
from diary_rag.app import create_app
from diary_rag.config import Settings
from diary_rag.services import DiaryService, Dispatcher, ExportService, QueryService
from diary_rag.storage.mock import MockDiaryStore


def _settings() -> Settings:
    return Settings(_env_file=None, telegram_webhook_secret="test-secret")  # type: ignore[call-arg]


def _client_with_fresh_store() -> tuple[TestClient, MockDiaryStore]:
    store = MockDiaryStore()
    embed = MockEmbeddingClient()
    dispatcher = Dispatcher(
        DiaryService(store, embedding_client=embed),
        QueryService(store, embed),
        ExportService(store),
    )
    app = create_app(_settings())
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
        _update("/entry 2026-05-09\nHad a calm morning\nTried a new book", update_id=1),
    )
    assert entry_resp.status_code == 200
    assert entry_resp.json()["text"] == "Saved 2 events for 2026-05-09."
    assert store.len_chunks() == 2

    ask_resp = _post(client, _update("/ask book", update_id=2, message_id=2))
    assert ask_resp.status_code == 200
    body = ask_resp.json()
    assert body["method"] == "sendMessage"
    assert body["chat_id"] == 42
    assert body["text"] == (
        "Found 1 memory:\n"
        "- [2026-05-09] Tried a new book\n"
        "(hybrid retrieval — dense+sparse RRF)"
    )


def test_ask_with_no_match_returns_no_evidence_fallback() -> None:
    client, _ = _client_with_fresh_store()

    _post(client, _update("/entry 2026-05-09\nMorning routine", update_id=1))
    resp = _post(client, _update("/ask snowstorm", update_id=2, message_id=2))

    assert resp.status_code == 200
    assert resp.json()["text"] == "No memories matched 'snowstorm'."


def test_entry_with_invalid_first_line_returns_invalid_input_and_persists_source() -> None:
    client, store = _client_with_fresh_store()

    resp = _post(client, _update("/entry not-a-date\nfoo", update_id=1))

    assert resp.status_code == 200
    assert resp.json()["text"] == (
        "Mock /entry needs an ISO date (YYYY-MM-DD) on the first line. Got: 'not-a-date'."
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
        "Saved 2 events for 2026-05-10.\n"
        "(routed as entry — send /entry next time to be explicit)"
    )
    assert store.len_chunks() == 2


def test_question_plain_text_returns_grounded_reply_via_heuristic() -> None:
    client, _ = _client_with_fresh_store()

    _post(client, _update("/entry 2026-05-10\nLearned a new recipe\nWalked 5km", update_id=1))
    resp = _post(client, _update("recipe?", update_id=2, message_id=2))

    assert resp.status_code == 200
    assert resp.json()["text"] == (
        "Found 1 memory:\n"
        "- [2026-05-10] Learned a new recipe\n"
        "(hybrid retrieval — dense+sparse RRF)\n"
        "(routed as question — send /ask next time to be explicit)"
    )


def test_ambiguous_plain_text_persists_as_draft_under_no_command_default() -> None:
    client, store = _client_with_fresh_store()

    resp = _post(client, _update("recipe yesterday", update_id=1))

    assert resp.status_code == 200
    body = resp.json()
    assert body["text"].startswith("Stored as draft")
    assert "/entry" in body["text"]
    assert store.len_sources() == 1
    assert store.len_entries() == 0
    assert store.len_chunks() == 0


def test_explicit_draft_command_persists_raw_only_and_skips_enrichment() -> None:
    client, store = _client_with_fresh_store()

    resp = _post(client, _update("/draft 2026-05-09\nNot sure yet, keep it raw", update_id=1))

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
        "/entry 2026-05-09\nHad a calm morning\nTried a new book",
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
        _update("/entry 2026-05-09\nA\nB", update_id=1, message_id=99),
    )
    edited = _post(
        client,
        _update(
            "/entry 2026-05-09\nA\nB\nC",
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
