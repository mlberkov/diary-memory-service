"""Storage seam for the diary domain.

`DiaryRepository` is the channel-neutral persistence Protocol that
ingestion and query services depend on. The in-memory ``MockDiaryStore``
and the durable ``SqliteDiaryStore`` both satisfy it structurally.

Stability note: future idempotency work (R-2) will add a new method
returning ``(SourceMessage, bool)`` rather than mutate the existing
``save_source_message`` signature, so callers that depend only on this
Protocol are insulated from that change.
"""

from __future__ import annotations

from typing import Protocol

from diary_rag.core.diary.models import DiaryEntry, EventChunk, SourceMessage


class DiaryRepository(Protocol):
    """Persistence surface used by ``DiaryService`` and ``QueryService``."""

    def save_source_message(self, source: SourceMessage) -> None: ...

    def save_diary_entry(self, entry: DiaryEntry) -> None: ...

    def save_event_chunks(self, chunks: list[EventChunk]) -> None: ...

    def get_source_message(self, source_message_id: str) -> SourceMessage | None: ...

    def search_chunks(self, family_id: str, query_text: str, top_k: int) -> list[EventChunk]: ...
