"""End-to-end webhook smoke: /entry then /ask via TestClient.

Each test wires a fresh ``MockDiaryStore`` + ``Dispatcher`` into the
FastAPI app via ``app.dependency_overrides`` so per-test state is
isolated from the module-level singleton in ``webhook.py``.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from diary_rag.adapters.telegram.webhook import get_dispatcher
from diary_rag.app import create_app
from diary_rag.config import Settings
from diary_rag.services import DiaryService, Dispatcher, QueryService
from diary_rag.storage.mock import MockDiaryStore


def _settings() -> Settings:
    return Settings(_env_file=None, telegram_webhook_secret="test-secret")  # type: ignore[call-arg]


def _client_with_fresh_store() -> tuple[TestClient, MockDiaryStore]:
    store = MockDiaryStore()
    dispatcher = Dispatcher(DiaryService(store), QueryService(store))
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
    text: str, *, update_id: int = 1, message_id: int = 1, chat_id: int = 42
) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": message_id,
            "date": 1715300000 + update_id,
            "chat": {"id": chat_id},
            "from": {"id": 7},
            "text": text,
        },
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
        "Found 1 memory:\n- [2026-05-09] Tried a new book\n(mock retrieval — substring match)"
    )


def test_ask_with_no_match_returns_no_evidence_fallback() -> None:
    client, _ = _client_with_fresh_store()

    _post(client, _update("/entry 2026-05-09\nMorning routine", update_id=1))
    resp = _post(client, _update("/ask snowstorm", update_id=2, message_id=2))

    assert resp.status_code == 200
    assert resp.json()["text"] == (
        "No memories matched 'snowstorm'. (no_evidence — mock retrieval only.)"
    )


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
    assert resp.json()["text"] == (
        "No memories matched 'anything'. (no_evidence — mock retrieval only.)"
    )
