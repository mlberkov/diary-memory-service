"""Dispatcher tests for the ``/delete`` control branch (ED-3 / D-114).

Covers the reply-targeted delete surface end to end through the dispatcher: a
successful tombstone, the two fail-closed no-op replies (no reply target, and a
target with no active note), and byte-equality guards that pin the new delete
reply strings and assert the sibling dispatch literals stay unchanged.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

from memory_rag.adapters.answers import MockChatClient
from memory_rag.adapters.embeddings import MockEmbeddingClient
from memory_rag.config import Settings
from memory_rag.core.routing import InboundMessage, RouteKind
from memory_rag.services import Dispatcher, DomainService, ExportService, QueryService
from memory_rag.services import dispatcher as dispatcher_module
from memory_rag.storage.mock import MockDomainStore

_CHAT = "chat-1"
_NOTE_MSG = "msg-100"
_COMMUNITY = "fam-A"


def _dispatcher() -> tuple[Dispatcher, MockDomainStore]:
    store = MockDomainStore()
    embed = MockEmbeddingClient()
    chat = MockChatClient()
    return (
        Dispatcher(
            DomainService(store, embedding_client=embed),
            QueryService(store, store, embed, chat),
            ExportService(store),
            Settings(_env_file=None),  # type: ignore[call-arg]
        ),
        store,
    )


def _note(payload: str, *, message_id: str = _NOTE_MSG) -> InboundMessage:
    return InboundMessage(
        external_message_id=message_id,
        external_chat_id=_CHAT,
        external_user_id="u-alice",
        community_id=_COMMUNITY,
        text=f"/note {payload}",
        route=RouteKind.NOTE,
        received_at=datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC),
        route_source="command",
        payload=payload,
    )


def _delete(*, reply_to: str | None) -> InboundMessage:
    return InboundMessage(
        external_message_id="cmd-1",
        external_chat_id=_CHAT,
        external_user_id="u-alice",
        community_id=_COMMUNITY,
        text="/delete",
        route=RouteKind.DELETE,
        received_at=datetime(2026, 5, 11, 12, 5, 0, tzinfo=UTC),
        route_source="command",
        payload="",
        reply_to_external_message_id=reply_to,
    )


def test_delete_reply_to_note_tombstones_and_confirms() -> None:
    dispatcher, store = _dispatcher()
    dispatcher.dispatch(_note("2026-05-09\nWalked the dog"))

    result = dispatcher.dispatch(_delete(reply_to=_NOTE_MSG))
    assert result.route is RouteKind.DELETE
    assert result.reply_text == dispatcher_module._REPLY_DELETE_OK
    assert result.metadata["deleted"] == "true"
    # The note is gone from the active set.
    assert (
        store.get_active_note_for_external_message(_CHAT, _NOTE_MSG, community_id=_COMMUNITY)
        is None
    )


def test_delete_without_reply_target_nudges() -> None:
    dispatcher, _ = _dispatcher()
    result = dispatcher.dispatch(_delete(reply_to=None))
    assert result.reply_text == dispatcher_module._REPLY_DELETE_NO_TARGET
    assert result.metadata["deleted"] == "false"


def test_delete_reply_to_non_note_is_friendly_noop() -> None:
    dispatcher, _ = _dispatcher()
    # Reply target exists as an id but addresses no captured note.
    result = dispatcher.dispatch(_delete(reply_to="not-a-note"))
    assert result.reply_text == dispatcher_module._REPLY_DELETE_NOTHING
    assert result.metadata["deleted"] == "false"


def test_delete_replayed_is_friendly_noop() -> None:
    dispatcher, _ = _dispatcher()
    dispatcher.dispatch(_note("2026-05-09\nWalked the dog"))
    first = dispatcher.dispatch(_delete(reply_to=_NOTE_MSG))
    second = dispatcher.dispatch(_delete(reply_to=_NOTE_MSG))
    assert first.reply_text == dispatcher_module._REPLY_DELETE_OK
    assert second.reply_text == dispatcher_module._REPLY_DELETE_NOTHING


# === Wording guards ==========================================================


def test_delete_reply_strings_are_pinned() -> None:
    """Byte-equality pins for the new delete replies (stable operator wording)."""
    assert (
        dispatcher_module._REPLY_DELETE_OK
        == "Deleted. That note is removed from search and won't appear in answers."
    )
    assert (
        dispatcher_module._REPLY_DELETE_NOTHING
        == "Nothing to delete — reply to a saved note with /delete to remove it."
    )
    assert (
        dispatcher_module._REPLY_DELETE_NO_TARGET == "To delete a note, reply to it with /delete."
    )


def test_sibling_dispatch_reply_strings_unchanged() -> None:
    """Adding the DELETE branch must not touch existing dispatch reply strings."""
    assert dispatcher_module._REPLY_UNKNOWN == (
        "I haven't been taught how to handle that yet — use /note, /ask, /sources, or /drafts."
    )
    assert dispatcher_module._REPLY_CLARIFY == (
        "I couldn't tell if that's a diary entry or a question. "
        "Send /note <YYYY-MM-DD> on the first line then your events to record it, "
        "or /ask <your question> to query."
    )
    assert dispatcher_module._REPLY_HELP == (
        "Commands: /start, /help, /note, /ask, /chat, /sources, /drafts, /export. Plain text "
        "without a command is stored as a draft."
    )
    # Round-trip a START dispatch to prove the welcome string is byte-stable.
    dispatcher, _ = _dispatcher()
    start = dispatcher.dispatch(
        dataclasses.replace(_delete(reply_to=None), route=RouteKind.START, text="/start")
    )
    assert start.reply_text == dispatcher_module._REPLY_START
