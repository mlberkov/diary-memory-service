"""Channel-neutral ingestion service.

Persists the raw inbound message first (Invariant I-3, runtime R-1),
then parses the date-led payload and creates one ``DiaryEntry`` plus
one ``EventChunk`` per event line (I-5). Authorship and family scope
are carried through (I-6, I-7).
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
from diary_rag.storage.mock import MockDiaryStore


def _family_id_for(message: InboundMessage) -> str:
    """Per-chat surrogate until explicit family bootstrap exists (A-14)."""
    return message.external_chat_id


class DiaryService:
    """Ingests an ``InboundMessage`` carrying a ``/entry`` payload."""

    def __init__(self, store: MockDiaryStore) -> None:
        self._store = store

    def ingest(self, message: InboundMessage) -> IngestResult:
        now = datetime.now(tz=UTC)
        family_id = _family_id_for(message)
        author_user_id = message.external_user_id
        source_message_id = str(uuid4())

        source = SourceMessage(
            source_message_id=source_message_id,
            family_id=family_id,
            author_user_id=author_user_id,
            external_chat_id=message.external_chat_id,
            external_user_id=message.external_user_id,
            raw_text=message.payload,
            detected_route=message.route,
            created_at=now,
        )
        self._store.save_source_message(source)

        parsed = parse_diary_entry(message.payload)
        if parsed is None:
            invalid = message.payload.splitlines()[0].strip() if message.payload else ""
            return IngestResult(
                fallback=FallbackMode.INVALID_INPUT,
                source_message_id=source_message_id,
                invalid_first_line=invalid,
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
