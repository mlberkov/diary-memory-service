"""Channel-neutral ingestion service.

Persists the raw inbound message first (Invariant I-3, runtime R-1),
then parses the date-led payload and creates one ``DiaryEntry`` plus
one ``EventChunk`` per event line (I-5). Authorship and family scope
are carried through (I-6, I-7).

Idempotency (R-2 / D-023): the source row is committed via
``DiaryRepository.get_or_create_source_message`` keyed on
``(external_chat_id, external_message_id, edit_seq)``. A replay short-
circuits parse and chunking and reconstructs the original ``IngestResult``
from persisted state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from diary_rag.core.diary import (
    DiaryEntry,
    EventChunk,
    FallbackMode,
    IngestResult,
    SourceMessage,
    parse_diary_entry,
)
from diary_rag.core.routing import InboundMessage
from diary_rag.storage.repository import DiaryRepository


def _family_id_for(message: InboundMessage) -> str:
    """Per-chat surrogate until explicit family bootstrap exists (A-14)."""
    return message.external_chat_id


def _first_line(text: str) -> str:
    return text.splitlines()[0].strip() if text else ""


class DiaryService:
    """Ingests an ``InboundMessage`` carrying a ``/entry`` payload."""

    def __init__(self, store: DiaryRepository) -> None:
        self._store = store

    def ingest(self, message: InboundMessage) -> IngestResult:
        now = datetime.now(tz=UTC)
        family_id = _family_id_for(message)
        author_user_id = message.external_user_id
        candidate_id = str(uuid4())

        candidate = SourceMessage(
            source_message_id=candidate_id,
            family_id=family_id,
            author_user_id=author_user_id,
            external_chat_id=message.external_chat_id,
            external_user_id=message.external_user_id,
            external_message_id=message.external_message_id,
            edit_seq=message.edit_seq,
            raw_text=message.payload,
            detected_route=message.route,
            created_at=now,
        )
        persisted, replayed = self._store.get_or_create_source_message(candidate)
        source_message_id = persisted.source_message_id

        if replayed:
            return self._reconstruct_result(persisted)

        parsed = parse_diary_entry(message.payload)
        if parsed is None:
            return IngestResult(
                fallback=FallbackMode.INVALID_INPUT,
                source_message_id=source_message_id,
                invalid_first_line=_first_line(message.payload),
            )

        diary_entry_id = str(uuid4())
        entry = DiaryEntry(
            diary_entry_id=diary_entry_id,
            source_message_id=source_message_id,
            family_id=family_id,
            author_user_id=author_user_id,
            entry_date=parsed.entry_date,
            entry_text="\n".join(parsed.events),
            created_at=now,
        )
        self._store.save_diary_entry(entry)

        chunks = [
            EventChunk(
                chunk_id=str(uuid4()),
                diary_entry_id=diary_entry_id,
                source_message_id=source_message_id,
                family_id=family_id,
                author_user_id=author_user_id,
                entry_date=parsed.entry_date,
                event_index=i,
                chunk_text=line,
                created_at=now,
            )
            for i, line in enumerate(parsed.events)
        ]
        self._store.save_event_chunks(chunks)

        return IngestResult(
            fallback=FallbackMode.NONE,
            source_message_id=source_message_id,
            entry_date=parsed.entry_date,
            events_count=len(chunks),
        )

    def _reconstruct_result(self, source: SourceMessage) -> IngestResult:
        """Rebuild the original ``IngestResult`` from persisted state (R-2)."""
        entry = self._store.get_diary_entry_by_source_message_id(source.source_message_id)
        if entry is None:
            return IngestResult(
                fallback=FallbackMode.INVALID_INPUT,
                source_message_id=source.source_message_id,
                invalid_first_line=_first_line(source.raw_text),
                replayed=True,
            )
        events_count = self._store.count_event_chunks_for_source(source.source_message_id)
        return IngestResult(
            fallback=FallbackMode.NONE,
            source_message_id=source.source_message_id,
            entry_date=entry.entry_date,
            events_count=events_count,
            replayed=True,
        )
