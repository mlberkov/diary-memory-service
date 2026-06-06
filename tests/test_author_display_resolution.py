"""Adapter-side author display-name resolution + rendering (D-086 / A-44).

The fallback chain ``username → first_name → opaque short-ID`` is applied
**only at the Telegram adapter seam** (D-081); the channel-neutral dispatcher
returns opaque chunks and never composes a display name. These tests cover the
pure resolver, the chunk→source→snapshot bridge, and the rendered ``/sources``
block format (byte-stable, sibling-guarded).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from memory_rag.adapters.telegram.author_display import (
    _resolve_source_author_display,
    render_source_block,
    resolve_author_display_name,
    resolve_chunk_author_display,
)
from memory_rag.core.domain.models import EventChunk, SourceMessage
from memory_rag.core.embeddings import EmbeddingStatus
from memory_rag.core.routing import RouteKind

# ---- pure resolver: fallback ordering ---------------------------------------


def test_username_present_wins_and_gets_at_prefix() -> None:
    # username takes priority even when first_name is also present.
    assert resolve_author_display_name("alice", "Alice A", "user-abcdef12") == "@alice"


def test_first_name_used_when_username_absent() -> None:
    assert resolve_author_display_name(None, "Bob", "user-abcdef12") == "Bob"


def test_both_null_falls_to_opaque_short_id() -> None:
    assert resolve_author_display_name(None, None, "user-1234567890abcdef") == "user-90abcdef"


def test_blank_and_whitespace_values_count_as_absent() -> None:
    # Empty / whitespace-only username falls through to first_name...
    assert resolve_author_display_name("", "Bob", "user-abcdef12") == "Bob"
    assert resolve_author_display_name("   ", "Bob", "user-abcdef12") == "Bob"
    # ...and a blank first_name too falls through to the short-ID floor.
    assert resolve_author_display_name("   ", "  ", "user-abcdef12") == "user-abcdef12"


def test_username_inner_whitespace_is_stripped_only_at_edges() -> None:
    assert resolve_author_display_name("  alice  ", None, "user-abcdef12") == "@alice"


def test_short_id_uses_last_eight_chars_of_author_user_id() -> None:
    # Shorter-than-8 ids are used whole (no padding).
    assert resolve_author_display_name(None, None, "7") == "user-7"


# ---- bridge: chunk → source → snapshot --------------------------------------


def _chunk(source_message_id: str = "src-1", author_user_id: str = "user-abcdef12") -> EventChunk:
    return EventChunk(
        chunk_id="c-1",
        note_id="n-1",
        source_message_id=source_message_id,
        community_id="42",
        author_user_id=author_user_id,
        note_date=date(2026, 5, 9),
        event_index=0,
        chunk_text="Walked the dog",
        created_at=datetime.now(tz=UTC),
        embedding_status=EmbeddingStatus.READY,
    )


class _FakeStore:
    """Minimal combined store: get_source_message + get_author_display_input."""

    def __init__(
        self,
        *,
        source: SourceMessage | None,
        snapshot: tuple[str | None, str | None] | None,
    ) -> None:
        self._source = source
        self._snapshot = snapshot
        self.snapshot_keys: list[tuple[str, str, int]] = []

    def get_source_message(
        self, source_message_id: str, *, community_id: str
    ) -> SourceMessage | None:
        # Community-scoped read (Slice 8.1.2 / D-089): a source owned by another
        # community reads as None, mirroring the real backends' own-column filter.
        if self._source is None or self._source.community_id != community_id:
            return None
        return self._source

    def get_author_display_input(
        self, *, external_chat_id: str, external_message_id: str, edit_seq: int
    ) -> tuple[str | None, str | None] | None:
        self.snapshot_keys.append((external_chat_id, external_message_id, edit_seq))
        return self._snapshot


def _source(source_message_id: str = "src-1") -> SourceMessage:
    return SourceMessage(
        source_message_id=source_message_id,
        community_id="42",
        author_user_id="user-abcdef12",
        external_chat_id="42",
        external_user_id="7",
        external_message_id="101",
        edit_seq=3,
        raw_text="Walked the dog",
        detected_route=RouteKind.NOTE,
        created_at=datetime.now(tz=UTC),
    )


def test_bridge_resolves_via_source_then_snapshot() -> None:
    store = _FakeStore(source=_source(), snapshot=("alice", "Alice A"))
    assert (
        resolve_chunk_author_display(_chunk(), store, community_id="42") == "@alice"  # type: ignore[arg-type]
    )
    # The bridge keys the snapshot read by the source row's external tuple.
    assert store.snapshot_keys == [("42", "101", 3)]


def test_bridge_floor_when_source_row_missing() -> None:
    store = _FakeStore(source=None, snapshot=None)
    assert (
        resolve_chunk_author_display(_chunk(), store, community_id="42")  # type: ignore[arg-type]
        == "user-abcdef12"
    )
    # No source row → no snapshot lookup attempted.
    assert store.snapshot_keys == []


def test_bridge_floor_when_community_mismatch() -> None:
    # Requester-scoped community ("99") differs from the source's owning
    # community ("42"): the community-scoped read returns None, so author
    # resolution fails closed to the opaque floor and never reads a snapshot —
    # the /sources author lookup cannot cross a community boundary (Slice 8.1.2).
    store = _FakeStore(source=_source(), snapshot=("alice", "Alice A"))
    assert (
        resolve_chunk_author_display(_chunk(), store, community_id="99")  # type: ignore[arg-type]
        == "user-abcdef12"
    )
    assert store.snapshot_keys == []


def test_bridge_floor_when_snapshot_missing() -> None:
    store = _FakeStore(source=_source(), snapshot=None)
    assert (
        resolve_chunk_author_display(_chunk(), store, community_id="42")  # type: ignore[arg-type]
        == "user-abcdef12"
    )


def test_bridge_floor_when_snapshot_both_null() -> None:
    store = _FakeStore(source=_source(), snapshot=(None, None))
    assert (
        resolve_chunk_author_display(_chunk(), store, community_id="42")  # type: ignore[arg-type]
        == "user-abcdef12"
    )


# ---- source/draft helper: direct snapshot (no bridge) -----------------------
# A SourceMessage already carries its own external tuple, so _resolve_source_author_display
# reads the snapshot directly — no get_source_message bridge (used by /drafts, D-098).


def test_source_resolver_username_tier() -> None:
    store = _FakeStore(source=None, snapshot=("alice", "Alice A"))
    assert (
        _resolve_source_author_display(_source(), store, community_id="42")  # type: ignore[arg-type]
        == "@alice"
    )
    # Keyed by the source's own external tuple — no get_source_message bridge.
    assert store.snapshot_keys == [("42", "101", 3)]


def test_source_resolver_first_name_tier() -> None:
    store = _FakeStore(source=None, snapshot=(None, "Bob"))
    assert (
        _resolve_source_author_display(_source(), store, community_id="42")  # type: ignore[arg-type]
        == "Bob"
    )


def test_source_resolver_floor_when_snapshot_missing() -> None:
    store = _FakeStore(source=None, snapshot=None)
    assert (
        _resolve_source_author_display(_source(), store, community_id="42")  # type: ignore[arg-type]
        == "user-abcdef12"
    )


def test_source_resolver_floor_when_snapshot_both_null() -> None:
    store = _FakeStore(source=None, snapshot=(None, None))
    assert (
        _resolve_source_author_display(_source(), store, community_id="42")  # type: ignore[arg-type]
        == "user-abcdef12"
    )


def test_source_resolver_floor_on_community_mismatch_reads_no_snapshot() -> None:
    # Defensive scope (Slice 8.1.2 / D-089): a source owned by another community
    # resolves to the opaque floor and never reads a snapshot. Drafts are already
    # community-scoped by the caller, so this guards the seam, not a live path.
    store = _FakeStore(source=None, snapshot=("alice", "Alice A"))
    assert (
        _resolve_source_author_display(_source(), store, community_id="99")  # type: ignore[arg-type]
        == "user-abcdef12"
    )
    assert store.snapshot_keys == []


# ---- rendered block format (byte-stable, sibling-guarded) -------------------


def test_render_source_block_format_is_byte_stable() -> None:
    store = _FakeStore(source=_source(), snapshot=("alice", None))
    block = render_source_block(_chunk(), index=1, total=3, store=store, community_id="42")  # type: ignore[arg-type]
    # Header line unchanged; author on its own attribution line; verbatim text.
    assert block == "[2026-05-09] (1/3)\n— @alice\n\nWalked the dog"


def test_render_source_block_floor_tier_format() -> None:
    store = _FakeStore(source=None, snapshot=None)
    block = render_source_block(_chunk(), index=2, total=2, store=store, community_id="42")  # type: ignore[arg-type]
    assert block == "[2026-05-09] (2/2)\n— user-abcdef12\n\nWalked the dog"
