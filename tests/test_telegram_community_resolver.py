"""Adapter-owned chat→community resolver (D-093 / G-1).

Pins the single named seam and its default 1:1 mapping. Characterization
of grouped / multi-diary behavior across the stack is G-2, not here.
"""

from __future__ import annotations

from memory_rag.adapters.telegram.community import resolve_community_id


def test_default_mapping_is_identity() -> None:
    assert resolve_community_id("42") == "42"


def test_distinct_chats_yield_distinct_community_ids() -> None:
    # Multi-diary on one instance: distinct chats are isolated communities
    # (I-7). The default mapping keeps them distinct.
    assert resolve_community_id("chat-a") != resolve_community_id("chat-b")


def test_returns_input_unchanged() -> None:
    for chat_id in ("", "-100123", "fam-A", "  spaces  "):
        assert resolve_community_id(chat_id) == chat_id
