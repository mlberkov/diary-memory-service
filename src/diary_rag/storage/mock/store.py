"""In-memory mock store for the diary domain.

Holds raw source messages, parsed diary entries, and per-event chunks
in process-local dicts. Search is a deterministic case-insensitive
substring match over chunk text, scoped to ``family_id``.

Not thread-safe. State lives only as long as the process.
"""

from __future__ import annotations

from diary_rag.core.diary.models import DiaryEntry, EventChunk, SourceMessage


class MockDiaryStore:
    """Process-local store for ``SourceMessage``, ``DiaryEntry``, ``EventChunk``."""

    def __init__(self) -> None:
        self._sources: dict[str, SourceMessage] = {}
        self._entries: dict[str, DiaryEntry] = {}
        self._chunks: dict[str, EventChunk] = {}

    def save_source_message(self, source: SourceMessage) -> None:
        self._sources[source.source_message_id] = source

    def save_diary_entry(self, entry: DiaryEntry) -> None:
        self._entries[entry.diary_entry_id] = entry

    def save_event_chunks(self, chunks: list[EventChunk]) -> None:
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk

    def get_source_message(self, source_message_id: str) -> SourceMessage | None:
        return self._sources.get(source_message_id)

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
        self._entries.clear()
        self._chunks.clear()
