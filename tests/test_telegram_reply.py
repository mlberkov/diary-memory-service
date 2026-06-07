"""Reply-envelope and canned-route dispatcher tests."""

from __future__ import annotations

from datetime import UTC, datetime

from memory_rag.adapters.answers import MockChatClient
from memory_rag.adapters.embeddings import MockEmbeddingClient
from memory_rag.adapters.telegram.reply import build_send_message_payload
from memory_rag.config import Settings
from memory_rag.core.routing import InboundMessage, RouteKind, RouteSource
from memory_rag.services import Dispatcher, DomainService, ExportService, QueryService
from memory_rag.services.dispatcher import (
    _REPLY_CLARIFY,
    _REPLY_HELP,
    _REPLY_START,
    _REPLY_UNKNOWN,
)
from memory_rag.storage.mock import MockDomainStore


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
        community_id="42",
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
    assert result.reply_text == "Stored as draft."
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
    assert first.reply_text == "Stored as draft."
    assert second.reply_text == "Stored as draft (replay)."


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


def test_draft_reply_wording_and_sibling_literals_are_pinned() -> None:
    """Byte-equality guards for the trimmed draft reply and its sibling reply literals.

    Packet 1 removed the ``/note`` + ``/ask`` hint from the draft-save confirmation. These
    guards pin the trimmed draft reply (fresh + replay), assert the removed hint sentence
    survives in no reply literal, and byte-pin the neighboring reply literals that
    legitimately still mention ``/note`` — so the trim cannot silently bleed into a sibling
    string or be reverted in this milestone.
    """
    dispatcher = _dispatcher()
    msg = _inbound(RouteKind.DRAFT, text="x", payload="x", route_source="heuristic")
    first = dispatcher.dispatch(msg)
    second = dispatcher.dispatch(msg)
    assert first.reply_text == "Stored as draft."
    assert second.reply_text == "Stored as draft (replay)."
    assert "/note" not in first.reply_text
    assert "/ask" not in first.reply_text

    # The exact hint sentence removed from the draft reply must survive nowhere else.
    removed_hint = (
        "Send /note <YYYY-MM-DD> on the first line to commit it as a note, or /ask to query."
    )
    for literal in (first.reply_text, _REPLY_START, _REPLY_HELP, _REPLY_UNKNOWN, _REPLY_CLARIFY):
        assert removed_hint not in literal

    # Sibling reply literals — byte-equality pins (must not change under this milestone).
    assert _REPLY_HELP == (
        "Commands: /start, /help, /note, /ask, /sources, /drafts, /export. Plain text "
        "without a command is stored as a draft."
    )
    assert _REPLY_UNKNOWN == (
        "I haven't been taught how to handle that yet — use /note, /ask, /sources, or /drafts."
    )
    assert _REPLY_CLARIFY == (
        "I couldn't tell if that's a diary entry or a question. "
        "Send /note <YYYY-MM-DD> on the first line then your events to record it, "
        "or /ask <your question> to query."
    )
    assert _REPLY_START == (
        "Welcome — diary mode. Use /note to record, /ask to query, /sources to see the chunks "
        "behind your last answer, or /drafts to recall recent drafts. For /note, put a date on "
        "the first line — 2026-05-09 is the recommended form; 2026/05/09, 2026.05.09, "
        "09-05-2026, 09/05/2026, and 09.05.2026 also work (DD-first is read as DD/MM/YYYY). "
        "Plain text without a command is stored as a draft so nothing is lost."
    )


def test_dispatcher_clarify_reply_explains_both_commands() -> None:
    result = _dispatcher().dispatch(
        _inbound(RouteKind.CLARIFY, "recipe yesterday", route_source="heuristic")
    )
    assert result.route is RouteKind.CLARIFY
    assert "/note" in result.reply_text
    assert "/ask" in result.reply_text
    assert result.metadata["route_source"] == "heuristic"


# Heuristic NOTE/ASK is no longer a reachable state after D-079 (command-less
# plain text routes only to the draft floor; NOTE/ASK come only from explicit
# commands), so the dispatcher no longer appends routing markers. The two tests
# that pinned those markers were removed with the marker machinery.


def test_command_routed_note_reply_has_no_heuristic_marker() -> None:
    result = _dispatcher().dispatch(
        _inbound(
            RouteKind.NOTE,
            text="/note 2026-05-10\nA",
            payload="2026-05-10\nA",
        )
    )
    assert "routed as note" not in result.reply_text
    assert result.metadata["route_source"] == "command"
