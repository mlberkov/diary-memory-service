"""Telegram-adapter tests for ``/export`` (D-029)."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from diary_rag.adapters.answers import MockChatClient
from diary_rag.adapters.embeddings import MockEmbeddingClient
from diary_rag.adapters.telegram.client import TelegramClient
from diary_rag.adapters.telegram.commands import parse_command
from diary_rag.adapters.telegram.webhook import get_dispatcher, get_telegram_client
from diary_rag.app import create_app
from diary_rag.config import Settings
from diary_rag.core.routing import RouteKind
from diary_rag.services import Dispatcher, DomainService, ExportService, QueryService
from diary_rag.storage.mock import MockDomainStore


class RecordingTelegramClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send_document(
        self,
        *,
        chat_id: str,
        filename: str,
        content: bytes,
        media_type: str,
        caption: str | None = None,
    ) -> None:
        self.calls.append(
            {
                "chat_id": chat_id,
                "filename": filename,
                "content": content,
                "media_type": media_type,
                "caption": caption,
            }
        )

    def send_message(self, *, chat_id: str, text: str) -> None:  # pragma: no cover
        raise AssertionError("send_message should not be invoked for /export")


class FailingTelegramClient:
    def send_document(self, **kwargs: Any) -> None:
        raise RuntimeError("simulated outbound delivery failure")

    def send_message(self, *, chat_id: str, text: str) -> None:  # pragma: no cover
        raise AssertionError("send_message should not be invoked for /export")


def _settings() -> Settings:
    return Settings(_env_file=None, telegram_webhook_secret="test-secret")  # type: ignore[call-arg]


def _client_with(
    telegram_client: TelegramClient | None = None,
) -> tuple[TestClient, MockDomainStore, TelegramClient]:
    store = MockDomainStore()
    embed = MockEmbeddingClient()
    chat = MockChatClient()
    settings = _settings()
    dispatcher = Dispatcher(
        DomainService(store, embedding_client=embed),
        QueryService(store, store, embed, chat),
        ExportService(store),
        settings,
    )
    if telegram_client is None:
        telegram_client = RecordingTelegramClient()
    app = create_app(settings)
    app.dependency_overrides[get_dispatcher] = lambda: dispatcher
    app.dependency_overrides[get_telegram_client] = lambda: telegram_client
    return TestClient(app), store, telegram_client


def _post(client: TestClient, payload: dict[str, Any]) -> Any:
    return client.post(
        "/telegram/webhook",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
    )


def _update(text: str) -> dict[str, Any]:
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": 1715300000,
            "chat": {"id": 42},
            "from": {"id": 7},
            "text": text,
        },
    }


def _seed_one(store: MockDomainStore) -> None:
    _post_or_seed(store)


def _post_or_seed(store: MockDomainStore) -> None:
    """Seed one note row directly through the store so /export has content."""
    from datetime import UTC, datetime

    from diary_rag.core.domain.models import SourceMessage

    store.save_source_message(
        SourceMessage(
            source_message_id="seed-1",
            community_id="42",
            author_user_id="7",
            external_chat_id="42",
            external_user_id="7",
            external_message_id="100",
            edit_seq=0,
            raw_text="seeded content",
            detected_route=RouteKind.NOTE,
            created_at=datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC),
        )
    )


def test_parse_command_parses_export_json() -> None:
    route, payload = parse_command("/export json")
    assert route is RouteKind.EXPORT
    assert payload == "json"


def test_parse_command_parses_export_txt() -> None:
    route, payload = parse_command("/export txt")
    assert route is RouteKind.EXPORT
    assert payload == "txt"


def test_parse_command_export_without_arg_yields_empty_payload() -> None:
    route, payload = parse_command("/export")
    assert route is RouteKind.EXPORT
    assert payload == ""


def test_export_missing_arg_replies_with_usage_and_does_not_send_document() -> None:
    client, _store, telegram_client = _client_with()
    response = _post(client, _update("/export"))
    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "sendMessage"
    assert "Usage" in body["text"]
    assert "json" in body["text"] and "txt" in body["text"]
    assert isinstance(telegram_client, RecordingTelegramClient)
    assert telegram_client.calls == []


def test_export_invalid_arg_replies_with_usage_and_does_not_send_document() -> None:
    client, _store, telegram_client = _client_with()
    response = _post(client, _update("/export csv"))
    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "sendMessage"
    assert "Usage" in body["text"]
    assert isinstance(telegram_client, RecordingTelegramClient)
    assert telegram_client.calls == []


def test_export_json_sends_document_and_returns_empty_body() -> None:
    client, store, telegram_client = _client_with()
    _seed_one(store)
    response = _post(client, _update("/export json"))
    assert response.status_code == 200
    assert response.json() == {}
    assert isinstance(telegram_client, RecordingTelegramClient)
    assert len(telegram_client.calls) == 1
    call = telegram_client.calls[0]
    assert call["chat_id"] == "42"
    assert call["filename"].startswith("raw_export_42_")
    assert call["filename"].endswith(".json")
    assert call["media_type"] == "application/json"
    assert call["caption"] == "Exported 1 raw message as JSON."
    document = json.loads(call["content"].decode("utf-8"))
    assert [r["source_message_id"] for r in document["records"]] == ["seed-1"]


def test_export_txt_sends_document_with_text_media_type() -> None:
    client, store, telegram_client = _client_with()
    _seed_one(store)
    response = _post(client, _update("/export txt"))
    assert response.status_code == 200
    assert response.json() == {}
    assert isinstance(telegram_client, RecordingTelegramClient)
    call = telegram_client.calls[0]
    assert call["filename"].endswith(".txt")
    assert call["media_type"] == "text/plain; charset=utf-8"
    assert call["caption"] == "Exported 1 raw message as TXT."


def test_export_with_no_seeded_messages_still_delivers_empty_envelope() -> None:
    client, _store, telegram_client = _client_with()
    response = _post(client, _update("/export json"))
    assert response.status_code == 200
    assert response.json() == {}
    assert isinstance(telegram_client, RecordingTelegramClient)
    call = telegram_client.calls[0]
    document = json.loads(call["content"].decode("utf-8"))
    assert document["records"] == []
    assert document["export"]["record_count"] == 0
    assert call["caption"] == "Exported 0 raw messages as JSON."


def test_export_delivery_failure_returns_send_message_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, store, _telegram_client = _client_with(telegram_client=FailingTelegramClient())
    _seed_one(store)
    with caplog.at_level(logging.WARNING, logger="diary_rag.adapters.telegram.webhook"):
        response = _post(client, _update("/export json"))
    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "sendMessage"
    assert "delivery to Telegram failed" in body["text"]
    assert any("export.delivery_failed" in line for line in caplog.text.splitlines())


def test_export_logs_ok_and_delivered_provenance(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, store, _telegram_client = _client_with()
    _seed_one(store)
    with caplog.at_level(logging.INFO):
        response = _post(client, _update("/export json"))
    assert response.status_code == 200
    assert any("export.ok" in line for line in caplog.text.splitlines())
    assert any("export.delivered" in line for line in caplog.text.splitlines())
