"""In-memory mock store round-trips a raw message."""

from __future__ import annotations

from diary_rag.storage.mock import InMemorySourceMessageStore


def test_put_and_get_round_trip() -> None:
    store = InMemorySourceMessageStore()
    store.put("msg-1", "2026-05-09\nFirst event\nSecond event")

    assert len(store) == 1
    assert store.get("msg-1") == "2026-05-09\nFirst event\nSecond event"
    assert store.get("missing") is None


def test_clear_resets_store() -> None:
    store = InMemorySourceMessageStore()
    store.put("a", "x")
    store.clear()
    assert len(store) == 0
