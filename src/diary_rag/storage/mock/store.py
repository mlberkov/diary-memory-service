"""In-memory mock store for the diary domain.

Holds raw source messages, parsed diary entries, and per-event chunks
in process-local dicts. Search is a deterministic case-insensitive
substring match over chunk text, scoped to ``family_id``.

``get_or_create_source_message`` enforces R-2 (D-023) by keying on the
``(external_chat_id, external_message_id, edit_seq)`` triple in a side
index; replays return the originally-persisted row.

Not thread-safe. State lives only as long as the process.
"""

from __future__ import annotations

from diary_rag.core.diary.models import DiaryEntry, EventChunk, SourceMessage


class MockDiaryStore:
    """Process-local store for ``SourceMessage``, ``DiaryEntry``, ``EventChunk``."""

    def __init__(self) -> None:
        self._sources: dict[str, SourceMessage] = {}
        self._idempotency: dict[tuple[str, str, int], str] = {}
        self._entries: dict[str, DiaryEntry] = {}
        self._chunks: dict[str, EventChunk] = {}

    def save_source_message(self, source: SourceMessage) -> None:
        key = (source.external_chat_id, source.external_message_id, source.edit_seq)
        if key in self._idempotency:
            raise ValueError(
                "duplicate source message for "
                f"(chat={source.external_chat_id}, msg={source.external_message_id}, "
                f"edit_seq={source.edit_seq}); use get_or_create_source_message"
            )
        self._sources[source.source_message_id] = source
        self._idempotency[key] = source.source_message_id

    def get_or_create_source_message(self, source: SourceMessage) -> tuple[SourceMessage, bool]:
        key = (source.external_chat_id, source.external_message_id, source.edit_seq)
        existing_id = self._idempotency.get(key)
        if existing_id is not None:
            return self._sources[existing_id], True
        self._sources[source.source_message_id] = source
        self._idempotency[key] = source.source_message_id
        return source, False

    def save_diary_entry(self, entry: DiaryEntry) -> None:
        self._entries[entry.diary_entry_id] = entry

    def save_event_chunks(self, chunks: list[EventChunk]) -> None:
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk

    def get_source_message(self, source_message_id: str) -> SourceMessage | None:
        return self._sources.get(source_message_id)

    def get_diary_entry_by_source_message_id(self, source_message_id: str) -> DiaryEntry | None:
        for entry in self._entries.values():
            if entry.source_message_id == source_message_id:
                return entry
        return None

    def count_event_chunks_for_source(self, source_message_id: str) -> int:
        return sum(
            1 for chunk in self._chunks.values() if chunk.source_message_id == source_message_id
        )

    def search_chunks(self, family_id: str, query_text: str, top_k: int) -> list[EventChunk]:
        """Case-insensitive substring match within a single ``family_id``.

        Results are returned in insertion order so the smoke flow is
        deterministic without depending on dict ordering surprises.
        """
        if not family_id:
            raise ValueError("family_id is required (Runtime invariant R-3)")
        if top_k <= 0:
            return []

        needle = query_text.strip().lower()
        if not needle:
            return []

        hits: list[EventChunk] = []
        for chunk in self._chunks.values():
            if chunk.family_id != family_id:
                continue
            if needle in chunk.chunk_text.lower():
                hits.append(chunk)
                if len(hits) >= top_k:
                    break
        return hits

    def len_sources(self) -> int:
        return len(self._sources)

    def len_entries(self) -> int:
        return len(self._entries)

    def len_chunks(self) -> int:
        return len(self._chunks)

    def clear(self) -> None:
        self._sources.clear()
        self._idempotency.clear()
        self._entries.clear()
        self._chunks.clear()
