"""Dispatcher-seam tests for explicit ``/note`` first-line date normalization.

Pins the boundary added in Packet 2 of the post-DEPLOY-1 Phase-4 UX polish
milestone (D-067 §Observations bullet 1):

- Explicit ``/note`` messages have their first non-empty line normalized
  to canonical ``YYYY-MM-DD`` before reaching :class:`DomainService.ingest`
  when the line matches the six-form near-ISO whitelist.
- Heuristic-routed messages are forwarded unchanged regardless of first
  line shape — the legacy classifier surface is not coupled to the new
  whitelist.
- The de-leaked user-facing error wording is in effect for empty/whitespace
  ``/note`` payloads, and the ``/start`` blurb proactively names the accepted
  formats and the DD/MM/YYYY convention.

Also pins Packet 3 of the "Stage-1 capture/routing baseline correction"
milestone (D-085):

- A ``/note`` whose first non-empty line is not a recognized date defaults
  the note to "today" (``message.received_at``, UTC) by prepending a canonical
  ``YYYY-MM-DD`` line, so the text becomes event lines instead of producing
  ``INVALID_INPUT``. The ``INVALID_INPUT`` contour survives only for an
  empty/whitespace-only payload.
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
        community_id="42",
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


def test_normalize_helper_prepends_today_for_unmatched_first_line() -> None:
    # D-085: a non-date first line on the explicit /note path defaults the
    # note to today (message.received_at, UTC); the junk line becomes an
    # event rather than producing INVALID_INPUT.
    msg = _inbound("not-a-date\nfoo")
    out = _normalize_note_first_line(msg)
    assert out.payload == "2026-05-10\nnot-a-date\nfoo"


def test_normalize_helper_prepends_today_for_unpadded_form() -> None:
    # The near-ISO whitelist is exact: 2026-5-9 is not a recognized date, so
    # D-085 treats it as a non-date first line and defaults to today rather
    # than "fixing" it into a date.
    msg = _inbound("2026-5-9\nfoo")
    out = _normalize_note_first_line(msg)
    assert out.payload == "2026-05-10\n2026-5-9\nfoo"


def test_normalize_helper_prepends_today_for_multi_event_dateless_note() -> None:
    msg = _inbound("walk\nslept well")
    out = _normalize_note_first_line(msg)
    assert out.payload == "2026-05-10\nwalk\nslept well"


def test_normalize_helper_prepends_today_before_leading_blank_lines() -> None:
    # The prepended today line precedes the original payload verbatim; the
    # parser then ignores the interior blank lines.
    msg = _inbound("\n\nwalk")
    out = _normalize_note_first_line(msg)
    assert out.payload == "2026-05-10\n\n\nwalk"


def test_normalize_helper_skips_leading_blank_lines_like_parser() -> None:
    msg = _inbound("\n\n09/05/2026\nfoo")
    out = _normalize_note_first_line(msg)
    assert out.payload == "\n\n2026-05-09\nfoo"


def test_normalize_helper_preserves_payload_for_empty_input() -> None:
    # Empty payload has no non-empty first line, so the today-default does not
    # fire — it falls through unchanged to parse_note → INVALID_INPUT.
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


def test_dispatch_explicit_dateless_note_saves_under_today() -> None:
    # D-085: a dateless /note defaults to the message's received_at date
    # (2026-05-10 in this fixture); the text becomes a single event.
    dispatcher, store = _dispatcher()
    result = dispatcher.dispatch(_inbound("walk in park"))
    assert result.reply_text == "Saved 1 event for 2026-05-10."
    assert store.len_notes() == 1
    assert store.len_chunks() == 1


def test_dispatch_explicit_dateless_multi_line_note_saves_all_events_under_today() -> None:
    dispatcher, store = _dispatcher()
    result = dispatcher.dispatch(_inbound("walk\nslept well"))
    assert result.reply_text == "Saved 2 events for 2026-05-10."
    assert store.len_notes() == 1
    assert store.len_chunks() == 2


# ---------------------------------------------------------------------------
# Sibling-wording guards — the INVALID_INPUT contour stays reachable and
# byte-identical for empty/whitespace-only /note (the today-default fires only
# when there IS a non-empty first line), and the sibling /note reply literals
# do not drift under this packet's edit.
# ---------------------------------------------------------------------------


def test_dispatch_explicit_empty_note_still_returns_invalid_input_wording() -> None:
    dispatcher, store = _dispatcher()
    result = dispatcher.dispatch(_inbound(""))
    assert result.reply_text == "First line must be a date like 2026-05-09. Got: ''."
    assert "Mock" not in result.reply_text
    assert store.len_notes() == 0


def test_dispatch_explicit_whitespace_only_note_still_returns_invalid_input_wording() -> None:
    dispatcher, store = _dispatcher()
    result = dispatcher.dispatch(_inbound("   "))
    assert result.reply_text == "First line must be a date like 2026-05-09. Got: ''."
    assert store.len_notes() == 0


def test_dispatch_explicit_dateless_note_with_no_events_uses_saved_no_events_wording() -> None:
    # A single non-date line becomes one event, so reaching the
    # "no event lines" literal would require a today-line with nothing after
    # it — only possible via an explicit canonical date with no body. Pin that
    # sibling literal here so it cannot drift.
    dispatcher, _ = _dispatcher()
    result = dispatcher.dispatch(_inbound("2026-05-09"))
    assert result.reply_text == "Saved 2026-05-09 with no event lines."


# The heuristic-routed NOTE normalize-seam (the dispatcher's former
# ``if not is_heuristic:`` guard) was removed with D-079: heuristic plain-text
# NOTE is no longer reachable (NOTE comes only from the explicit ``/note``
# command, which always normalizes). The test that pinned that seam was
# removed alongside it.


# ---------------------------------------------------------------------------
# /start blurb pins — proactive user-facing warning about accepted formats.
# ---------------------------------------------------------------------------


def test_start_reply_advertises_canonical_iso_form() -> None:
    assert "2026-05-09" in _REPLY_START


def test_start_reply_warns_about_dd_mm_yyyy_convention() -> None:
    assert "DD/MM/YYYY" in _REPLY_START
