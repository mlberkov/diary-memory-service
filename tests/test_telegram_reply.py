"""Reply-envelope and canned-route dispatcher tests."""

from __future__ import annotations

from datetime import UTC, datetime

from diary_rag.adapters.answers import MockChatClient
from diary_rag.adapters.embeddings import MockEmbeddingClient
from diary_rag.adapters.telegram.reply import build_send_message_payload
from diary_rag.config import Settings
from diary_rag.core.routing import InboundMessage, RouteKind, RouteSource
from diary_rag.services import Dispatcher, DomainService, ExportService, QueryService
from diary_rag.storage.mock import MockDomainStore


def _inbound(
    route: RouteKind,
    text: str = "",
    payload: str = "",
    *,
    route_source: RouteSource = "command",
) -> InboundMessage:
    return InboundMessage(
        external_message_id="1",
        external_chat_id="42",
        external_user_id="7",
        text=text,
        route=route,
        received_at=datetime(2026, 5, 10, tzinfo=UTC),
        route_source=route_source,
        payload=payload,
    )


def _settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _dispatcher() -> Dispatcher:
    store = MockDomainStore()
    embed = MockEmbeddingClient()
    chat = MockChatClient()
    return Dispatcher(
        DomainService(store, embedding_client=embed),
        QueryService(store, store, embed, chat),
        ExportService(store),
        _settings(),
    )


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
    for token in ("/start", "/help", "/note", "/ask", "/drafts", "/sources"):
        assert token in text
    assert "/draft " not in text  # the explicit /draft command is gone
    assert "/draft," not in text
    assert "/entry" not in text  # the old /entry command is gone (D-031)


def test_dispatcher_help_reply_does_not_mention_removed_draft_command() -> None:
    result = _dispatcher().dispatch(_inbound(RouteKind.HELP, "/help"))
    # ``/draft`` as a standalone command token (not the lifecycle word "draft")
    # must no longer be advertised in the help text.
    assert "/draft " not in result.reply_text
    assert "/draft," not in result.reply_text


def test_dispatcher_unknown_reply_points_at_help() -> None:
    result = _dispatcher().dispatch(_inbound(RouteKind.UNKNOWN, "hello"))
    text = result.reply_text
    assert "/note" in text or "/ask" in text or "/drafts" in text


def test_dispatcher_no_command_default_draft_stores_via_heuristic() -> None:
    result = _dispatcher().dispatch(
        _inbound(
            RouteKind.DRAFT,
            text="just thinking out loud",
            payload="just thinking out loud",
            route_source="heuristic",
        )
    )
    assert result.route is RouteKind.DRAFT
    assert result.reply_text.startswith("Stored as draft")
    assert "/note" in result.reply_text
    assert result.metadata["effective_path"] == "fresh"
    assert result.metadata["fallback"] == "none"


def test_dispatcher_draft_reply_marks_replay_on_repeated_delivery() -> None:
    dispatcher = _dispatcher()
    msg = _inbound(
        RouteKind.DRAFT,
        text="just thinking out loud",
        payload="just thinking out loud",
        route_source="heuristic",
    )
    first = dispatcher.dispatch(msg)
    second = dispatcher.dispatch(msg)
    assert first.metadata["effective_path"] == "fresh"
    assert second.metadata["effective_path"] == "replay"
    assert "replay" in second.reply_text


def test_dispatcher_no_command_default_draft_omits_heuristic_marker() -> None:
    result = _dispatcher().dispatch(
        _inbound(
            RouteKind.DRAFT,
            text="recipe yesterday",
            payload="recipe yesterday",
            route_source="heuristic",
        )
    )
    assert result.route is RouteKind.DRAFT
    assert result.reply_text.startswith("Stored as draft")
    # The draft floor is unconditional; no requested-vs-effective marker is needed
    # because nothing about the draft outcome diverged from the routing decision.
    assert "routed as" not in result.reply_text


def test_dispatcher_clarify_reply_explains_both_commands() -> None:
    result = _dispatcher().dispatch(
        _inbound(RouteKind.CLARIFY, "recipe yesterday", route_source="heuristic")
    )
    assert result.route is RouteKind.CLARIFY
    assert "/note" in result.reply_text
    assert "/ask" in result.reply_text
    assert result.metadata["route_source"] == "heuristic"


def test_dispatcher_appends_heuristic_marker_to_entry_reply() -> None:
    result = _dispatcher().dispatch(
        _inbound(
            RouteKind.ENTRY,
            text="2026-05-10\nLearned a new recipe",
            payload="2026-05-10\nLearned a new recipe",
            route_source="heuristic",
        )
    )
    assert result.reply_text.endswith("(routed as note — send /note next time to be explicit)")
    assert result.metadata["route_source"] == "heuristic"


def test_dispatcher_appends_heuristic_marker_to_ask_reply() -> None:
    dispatcher = _dispatcher()
    dispatcher.dispatch(
        _inbound(
            RouteKind.ENTRY,
            text="2026-05-10\nLearned a new recipe",
            payload="2026-05-10\nLearned a new recipe",
        )
    )
    result = dispatcher.dispatch(
        _inbound(
            RouteKind.ASK,
            text="recipe?",
            payload="recipe?",
            route_source="heuristic",
        )
    )
    assert result.reply_text.endswith("(routed as question — send /ask next time to be explicit)")
    assert result.metadata["route_source"] == "heuristic"


def test_command_routed_entry_reply_has_no_heuristic_marker() -> None:
    result = _dispatcher().dispatch(
        _inbound(
            RouteKind.ENTRY,
            text="/note 2026-05-10\nA",
            payload="2026-05-10\nA",
        )
    )
    assert "routed as note" not in result.reply_text
    assert result.metadata["route_source"] == "command"
