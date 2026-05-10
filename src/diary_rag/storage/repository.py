"""Storage seam for the diary domain.

`DiaryRepository` is the channel-neutral persistence Protocol that
ingestion and query services depend on. The in-memory ``MockDiaryStore``,
the local ``SqliteDiaryStore``, and the canonical ``PostgresDiaryStore``
all satisfy it structurally.

``get_or_create_source_message`` enforces Runtime invariant R-2 (D-023):
repeated delivery of the same ``(external_chat_id, external_message_id,
edit_seq)`` returns the row that was already persisted and never creates
a second one. Backends use DB-native conflict handling
(``INSERT ... ON CONFLICT DO NOTHING`` on Postgres, ``INSERT OR IGNORE``
on SQLite, dict-keyed dedupe in the mock) so the unique constraint is
part of the correctness model rather than a safety net.
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

    def get_or_create_source_message(self, source: SourceMessage) -> tuple[SourceMessage, bool]:
        """Idempotent persist (R-2, D-023).

        Returns ``(persisted, replayed)``. ``replayed`` is ``True`` when a
        row keyed on ``(external_chat_id, external_message_id, edit_seq)``
        already existed; the returned ``SourceMessage`` is the existing row
        in that case, so callers can short-circuit re-parse / re-chunk.
        """

    def get_diary_entry_by_source_message_id(self, source_message_id: str) -> DiaryEntry | None:
        """Fetch the diary entry persisted for a given source, if any.

        Used by the ingest path to reconstruct the original ``IngestResult``
        on replay without re-parsing or re-chunking.
        """

    def count_event_chunks_for_source(self, source_message_id: str) -> int:
        """Count event chunks persisted for a given source."""

    def search_chunks(self, family_id: str, query_text: str, top_k: int) -> list[EventChunk]: ...
