"""Dispatcher-seam tests for explicit ``/note`` first-line date normalization.

Pins the boundary added in Packet 2 of the post-DEPLOY-1 Phase-4 UX polish
milestone (D-067 §Observations bullet 1):

- Explicit ``/note`` messages have their first non-empty line normalized
  to canonical ``YYYY-MM-DD`` before reaching :class:`DomainService.ingest`
  when the line matches the six-form near-ISO whitelist.
- Heuristic-routed messages are forwarded unchanged regardless of first
  line shape — the legacy classifier surface is not coupled to the new
  whitelist.
- The de-leaked user-facing error wording is in effect for unmatched
  first lines, and the ``/start`` blurb proactively names the accepted
  formats and the DD/MM/YYYY convention.
"""

from __future__ import annotations

from datetime import UTC, datetime

from memory_rag.adapters.answers import MockChatClient
from memory_rag.adapters.embeddings import MockEmbeddingClient
from memory_rag.config import Settings
from memory_rag.core.routing import InboundMessage, RouteKind, RouteSource
from memory_rag.services import Dispatcher, DomainService, ExportService, QueryService
from memory_rag.services.dispatcher import (
    _REPLY_START,
    _normalize_note_first_line,
)
from memory_rag.storage.mock import MockDomainStore


def _inbound(
    payload: str,
    *,
    route: RouteKind = RouteKind.NOTE,
    route_source: RouteSource = "command",
) -> InboundMessage:
    return InboundMessage(
        external_message_id="1",
        external_chat_id="42",
        external_user_id="7",
        text="/note " + payload if route is RouteKind.NOTE else payload,
        route=route,
        received_at=datetime(2026, 5, 10, tzinfo=UTC),
        route_source=route_source,
        payload=payload,
    )


def _dispatcher() -> tuple[Dispatcher, MockDomainStore]:
    store = MockDomainStore()
    embed = MockEmbeddingClient()
    chat = MockChatClient()
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    return (
        Dispatcher(
            DomainService(store, embedding_client=embed),
            QueryService(store, store, embed, chat),
            ExportService(store),
            settings,
        ),
        store,
    )


# ---------------------------------------------------------------------------
# Helper-level behavior — pure InboundMessage transform, no domain involved.
# ---------------------------------------------------------------------------


def test_normalize_helper_rewrites_first_line_for_whitelisted_form() -> None:
    msg = _inbound("2026/05/09\nfoo\nbar")
    out = _normalize_note_first_line(msg)
    assert out.payload == "2026-05-09\nfoo\nbar"


def test_normalize_helper_applies_dd_mm_yyyy_convention() -> None:
    msg = _inbound("05/09/2026\nfoo")
    out = _normalize_note_first_line(msg)
    # Convention pin at the dispatcher seam: 05/09/2026 → 2026-09-05.
    assert out.payload == "05/09/2026\nfoo".replace("05/09/2026", "2026-09-05")


def test_normalize_helper_is_noop_for_canonical_form() -> None:
    msg = _inbound("2026-05-09\nfoo")
    out = _normalize_note_first_line(msg)
    assert out is msg
    assert out.payload == "2026-05-09\nfoo"


def test_normalize_helper_is_noop_for_unmatched_first_line() -> None:
    # Junk first line stays as-is so the existing strict parser then
    # produces INVALID_INPUT with the new user-facing wording.
    msg = _inbound("not-a-date\nfoo")
    out = _normalize_note_first_line(msg)
    assert out is msg
    assert out.payload == "not-a-date\nfoo"


def test_normalize_helper_is_noop_for_unpadded_form() -> None:
    # Owner whitelist is exact: 2026-5-9 is rejected by the normalizer
    # and falls through to the existing INVALID_INPUT path.
    msg = _inbound("2026-5-9\nfoo")
    out = _normalize_note_first_line(msg)
    assert out is msg


def test_normalize_helper_skips_leading_blank_lines_like_parser() -> None:
    msg = _inbound("\n\n09/05/2026\nfoo")
    out = _normalize_note_first_line(msg)
    assert out.payload == "\n\n2026-05-09\nfoo"


def test_normalize_helper_preserves_payload_for_empty_input() -> None:
    msg = _inbound("")
    out = _normalize_note_first_line(msg)
    assert out is msg


# ---------------------------------------------------------------------------
# Dispatcher-level behavior — explicit /note path applies the normalizer,
# heuristic path does not.
# ---------------------------------------------------------------------------


def test_dispatch_explicit_note_with_slash_separated_date_persists_canonical_date() -> None:
    dispatcher, store = _dispatcher()
    result = dispatcher.dispatch(_inbound("2026/05/09\nfoo"))
    assert result.reply_text == "Saved 1 event for 2026-05-09."
    assert store.len_notes() == 1
    assert store.len_chunks() == 1


def test_dispatch_explicit_note_with_dd_first_date_uses_dd_mm_yyyy_convention() -> None:
    dispatcher, store = _dispatcher()
    # 05/09/2026 in DD/MM/YYYY is 5 September 2026 → canonical 2026-09-05.
    result = dispatcher.dispatch(_inbound("05/09/2026\nfoo"))
    assert result.reply_text == "Saved 1 event for 2026-09-05."
    assert store.len_notes() == 1


def test_dispatch_explicit_note_with_unmatched_first_line_returns_new_error_wording() -> None:
    dispatcher, store = _dispatcher()
    result = dispatcher.dispatch(_inbound("not-a-date\nfoo"))
    assert result.reply_text == "First line must be a date like 2026-05-09. Got: 'not-a-date'."
    assert "Mock" not in result.reply_text
    assert store.len_notes() == 0


def test_dispatch_heuristic_note_route_is_not_normalized() -> None:
    # The legacy heuristic plain-text NOTE auto-route is not coupled to
    # the new whitelist. A heuristic-routed message with 2026/05/09 on
    # the first line forwards the payload unchanged, so the strict
    # parser still rejects it. (This test pins that the seam respects
    # is_heuristic; the broader question of whether the legacy
    # heuristic should exist at all is deferred to a separate cleanup.)
    dispatcher, store = _dispatcher()
    result = dispatcher.dispatch(
        _inbound("2026/05/09\nfoo", route_source="heuristic"),
    )
    # Strict parse_note rejects 2026/05/09 → INVALID_INPUT reply, plus
    # the heuristic marker appended by the dispatcher.
    assert "First line must be a date like 2026-05-09." in result.reply_text
    assert "Got: '2026/05/09'." in result.reply_text
    assert store.len_notes() == 0


# ---------------------------------------------------------------------------
# /start blurb pins — proactive user-facing warning about accepted formats.
# ---------------------------------------------------------------------------


def test_start_reply_advertises_canonical_iso_form() -> None:
    assert "2026-05-09" in _REPLY_START


def test_start_reply_warns_about_dd_mm_yyyy_convention() -> None:
    assert "DD/MM/YYYY" in _REPLY_START
