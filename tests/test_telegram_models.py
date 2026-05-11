"""Telegram update schema scope tests."""

from __future__ import annotations

from diary_rag.adapters.telegram.models import TelegramUpdate


def test_telegram_update_parses_minimal_message_update() -> None:
    payload = {
        "update_id": 123,
        "message": {
            "message_id": 1,
            "date": 1715300000,
            "chat": {"id": 42},
            "from": {"id": 7},
            "text": "/start",
        },
    }
    update = TelegramUpdate.model_validate(payload)
    assert update.update_id == 123
    assert update.message is not None
    assert update.message.chat.id == 42
    assert update.message.from_.id == 7
    assert update.message.text == "/start"


def test_telegram_update_ignores_unknown_fields() -> None:
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": 1,
            "chat": {"id": 1, "type": "private"},
            "from": {"id": 1, "is_bot": False, "first_name": "Vita"},
            "text": "/help",
            "entities": [{"type": "bot_command", "offset": 0, "length": 5}],
        },
    }
    update = TelegramUpdate.model_validate(payload)
    assert update.message is not None
    assert update.message.text == "/help"


def test_telegram_update_accepts_update_without_message() -> None:
    update = TelegramUpdate.model_validate({"update_id": 5})
    assert update.update_id == 5
    assert update.message is None


def test_telegram_message_parses_edit_date_when_present() -> None:
    payload = {
        "update_id": 7,
        "message": {
            "message_id": 99,
            "date": 1715300000,
            "edit_date": 1715300100,
            "chat": {"id": 42},
            "from": {"id": 7},
            "text": "/note 2026-05-09\nA",
        },
    }
    update = TelegramUpdate.model_validate(payload)
    assert update.message is not None
    assert update.message.edit_date == 1715300100


def test_telegram_message_edit_date_defaults_to_none() -> None:
    payload = {
        "update_id": 7,
        "message": {
            "message_id": 99,
            "date": 1715300000,
            "chat": {"id": 42},
            "from": {"id": 7},
            "text": "/start",
        },
    }
    update = TelegramUpdate.model_validate(payload)
    assert update.message is not None
    assert update.message.edit_date is None
