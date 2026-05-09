"""Webhook secret-header gating."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from diary_rag.app import create_app
from diary_rag.config import Settings


def _settings(secret: str = "test-secret") -> Settings:
    return Settings(_env_file=None, telegram_webhook_secret=secret)  # type: ignore[call-arg]


def _update_payload() -> dict[str, Any]:
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": 1715300000,
            "chat": {"id": 42},
            "from": {"id": 7},
            "text": "/start",
        },
    }


def test_webhook_rejects_request_without_secret_header() -> None:
    client = TestClient(create_app(_settings()))
    response = client.post("/telegram/webhook", json=_update_payload())
    assert response.status_code == 401


def test_webhook_rejects_request_with_wrong_secret() -> None:
    client = TestClient(create_app(_settings()))
    response = client.post(
        "/telegram/webhook",
        json=_update_payload(),
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert response.status_code == 401


def test_webhook_accepts_request_with_matching_secret() -> None:
    client = TestClient(create_app(_settings()))
    response = client.post(
        "/telegram/webhook",
        json=_update_payload(),
        headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "sendMessage"
    assert body["chat_id"] == 42


def test_webhook_fails_closed_when_secret_unset() -> None:
    client = TestClient(create_app(_settings(secret="")))
    response_no_header = client.post("/telegram/webhook", json=_update_payload())
    response_with_header = client.post(
        "/telegram/webhook",
        json=_update_payload(),
        headers={"X-Telegram-Bot-Api-Secret-Token": "anything"},
    )
    assert response_no_header.status_code == 401
    assert response_with_header.status_code == 401
