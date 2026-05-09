"""Smallest viable in-memory store.

Holds raw text by id. Slice 1.3 replaces this with
`MockSourceMessageRepository` carrying the full `SourceMessage` shape
from TechSpec §5.
"""

from __future__ import annotations


class InMemorySourceMessageStore:
    """Process-local raw-text store. Not thread-safe; not persisted."""

    def __init__(self) -> None:
        self._items: dict[str, str] = {}

    def put(self, source_message_id: str, raw_text: str) -> None:
        self._items[source_message_id] = raw_text

    def get(self, source_message_id: str) -> str | None:
        return self._items.get(source_message_id)

    def __len__(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        self._items.clear()
