"""Webhook → adapter → dispatcher wiring tests using a recording fake."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from diary_rag.adapters.telegram.webhook import get_dispatcher
from diary_rag.app import create_app
from diary_rag.config import Settings
from diary_rag.core.routing import DispatchResult, InboundMessage, RouteKind


class RecordingDispatcher:
    def __init__(self) -> None:
        self.calls: list[InboundMessage] = []

    def dispatch(self, message: InboundMessage) -> DispatchResult:
        self.calls.append(message)
        return DispatchResult(reply_text="ok", route=message.route)


def _settings() -> Settings:
    return Settings(_env_file=None, telegram_webhook_secret="test-secret")  # type: ignore[call-arg]


def _client_with_fake() -> tuple[TestClient, RecordingDispatcher]:
    fake = RecordingDispatcher()
    app = create_app(_settings())
    app.dependency_overrides[get_dispatcher] = lambda: fake
    return TestClient(app), fake


def _post(client: TestClient, payload: dict[str, Any]) -> Any:
    return client.post(
        "/telegram/webhook",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
    )


def _message_update(text: str | None) -> dict[str, Any]:
    return {
        "update_id": 1,
        "message": {
            "message_id": 99,
            "date": 1715300000,
            "chat": {"id": 42},
            "from": {"id": 7},
            "text": text,
        },
    }


def test_dispatch_called_with_route_start_for_start_command() -> None:
    client, fake = _client_with_fake()
    response = _post(client, _message_update("/start"))
    assert response.status_code == 200
    assert len(fake.calls) == 1
    inbound = fake.calls[0]
    assert inbound.route is RouteKind.START
    assert inbound.external_chat_id == "42"
    assert inbound.external_user_id == "7"
    assert inbound.external_message_id == "99"
    assert inbound.payload == ""


def test_dispatch_called_with_route_entry_and_payload() -> None:
    client, fake = _client_with_fake()
    response = _post(client, _message_update("/entry 2026-05-09\nFoo"))
    assert response.status_code == 200
    assert len(fake.calls) == 1
    assert fake.calls[0].route is RouteKind.ENTRY
    assert fake.calls[0].payload == "2026-05-09\nFoo"


def test_dispatch_called_with_route_ask_for_question_command() -> None:
    client, fake = _client_with_fake()
    response = _post(client, _message_update("/ask what did we do?"))
    assert response.status_code == 200
    assert fake.calls[0].route is RouteKind.ASK
    assert fake.calls[0].payload == "what did we do?"


def test_dispatch_called_with_route_unknown_for_plain_text() -> None:
    client, fake = _client_with_fake()
    response = _post(client, _message_update("hello"))
    assert response.status_code == 200
    assert fake.calls[0].route is RouteKind.UNKNOWN


def test_webhook_returns_200_with_empty_body_for_non_message_update() -> None:
    client, fake = _client_with_fake()
    response = _post(client, {"update_id": 1})
    assert response.status_code == 200
    assert response.json() == {}
    assert fake.calls == []
