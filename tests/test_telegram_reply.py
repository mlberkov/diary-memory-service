"""Reply-envelope and canned-route dispatcher tests."""

from __future__ import annotations

from datetime import UTC, datetime

from diary_rag.adapters.telegram.reply import build_send_message_payload
from diary_rag.core.routing import InboundMessage, RouteKind
from diary_rag.services import DiaryService, Dispatcher, QueryService
from diary_rag.storage.mock import MockDiaryStore


def _inbound(route: RouteKind, text: str = "", payload: str = "") -> InboundMessage:
    return InboundMessage(
        external_message_id="1",
        external_chat_id="42",
        external_user_id="7",
        text=text,
        route=route,
        received_at=datetime(2026, 5, 10, tzinfo=UTC),
        payload=payload,
    )


def _dispatcher() -> Dispatcher:
    store = MockDiaryStore()
    return Dispatcher(DiaryService(store), QueryService(store))


def test_reply_payload_has_send_message_envelope() -> None:
    assert build_send_message_payload("123", "hi") == {
        "method": "sendMessage",
        "chat_id": 123,
        "text": "hi",
    }


def test_dispatcher_start_reply_mentions_diary_mode() -> None:
    result = _dispatcher().dispatch(_inbound(RouteKind.START, "/start"))
    assert result.route is RouteKind.START
    assert "diary" in result.reply_text.lower()


def test_dispatcher_help_reply_lists_supported_commands() -> None:
    result = _dispatcher().dispatch(_inbound(RouteKind.HELP, "/help"))
    text = result.reply_text
    for token in ("/start", "/help", "/entry", "/ask"):
        assert token in text


def test_dispatcher_unknown_reply_points_at_help() -> None:
    result = _dispatcher().dispatch(_inbound(RouteKind.UNKNOWN, "hello"))
    text = result.reply_text
    assert "/entry" in text or "/ask" in text
