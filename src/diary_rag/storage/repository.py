"""Storage seam for the diary domain.

`DomainRepository` is the channel-neutral persistence Protocol that
the ingest path depends on. The in-memory ``MockDomainStore``, the local
``SqliteDomainStore``, and the canonical ``PostgresDomainStore`` all
satisfy it structurally. Retrieval is a separate seam
(``SearchRepository`` in ``storage.search_repository``); a single
backend class can satisfy both Protocols.

``get_or_create_source_message`` enforces Runtime invariant R-2 (D-023):
repeated delivery of the same ``(external_chat_id, external_message_id,
edit_seq)`` returns the row that was already persisted and never creates
a second one. Backends use DB-native conflict handling
(``INSERT ... ON CONFLICT DO NOTHING`` on Postgres, ``INSERT OR IGNORE``
on SQLite, dict-keyed dedupe in the mock) so the unique constraint is
part of the correctness model rather than a safety net.

Phase 3.1+3.2 (D-024) adds three embedding-related methods. The Postgres
backend persists ``embedding`` as a ``vector(3072)`` (pgvector); SQLite
stores the same payload as little-endian f32 ``BLOB``; the mock keeps it
as a ``list[float]``. ``embedding_status`` is a per-chunk column so a
SQL inspection alone tells the operator which chunks succeeded or
failed.

Slice 3.3 (D-025) replaces the substring placeholder ``search_chunks``
with the dedicated ``SearchRepository`` seam. ``get_event_chunk`` is the
small chunk-by-id read primitive that supports inspection and test
assertions after that removal.
"""

from __future__ import annotations

from typing import Protocol

from diary_rag.core.domain.models import (
    AnswerTrace,
    DiaryEntry,
    EventChunk,
    Query,
    RetrievalHit,
    SourceMessage,
)
from diary_rag.core.embeddings.models import EmbeddingRecord, EmbeddingStatus


class DomainRepository(Protocol):
    """Persistence surface used by ``DomainService`` and ``QueryService``."""

    def save_source_message(self, source: SourceMessage) -> None: ...

    def save_diary_entry(self, entry: DiaryEntry) -> None: ...

    def save_event_chunks(self, chunks: list[EventChunk]) -> None: ...

    def get_source_message(self, source_message_id: str) -> SourceMessage | None: ...

    def list_source_messages(
        self, family_id: str, *, limit: int | None = None
    ) -> list[SourceMessage]:
        """List raw source messages for a family in deterministic order.

        Order: ``(created_at ASC, source_message_id ASC)``. Includes every
        persisted route (notes and drafts alike). Family scoping is
        mandatory (I-7). ``limit`` caps the result; ``None`` means no
        cap. Backends without raw-export parity (SQLite is opt-in
        ingest-only) raise ``NotImplementedError`` (D-029).
        """

    def list_recent_drafts(self, family_id: str, *, limit: int) -> list[SourceMessage]:
        """Return the most recent draft source messages for a family.

        Filter: ``detected_route == RouteKind.DRAFT``. Order:
        ``(created_at DESC, source_message_id DESC)``. Family scoping is
        mandatory (I-7); ``limit`` must be ``>= 1``. Backends without
        durable parity (SQLite is opt-in ingest-only) raise
        ``NotImplementedError``.
        """

    def get_or_create_source_message(self, source: SourceMessage) -> tuple[SourceMessage, bool]:
        """Idempotent persist (R-2, D-023).

        Returns ``(persisted, replayed)``. ``replayed`` is ``True`` when a
        row keyed on ``(external_chat_id, external_message_id, edit_seq)``
        already existed; the returned ``SourceMessage`` is the existing row
        in that case, so callers can short-circuit re-parse / re-chunk /
        re-embed (D-024).
        """

    def get_diary_entry_by_source_message_id(self, source_message_id: str) -> DiaryEntry | None:
        """Fetch the diary entry persisted for a given source, if any.

        Used by the ingest path to reconstruct the original ``IngestResult``
        on replay without re-parsing or re-chunking.
        """

    def count_event_chunks_for_source(self, source_message_id: str) -> int:
        """Count event chunks persisted for a given source."""

    def get_event_chunk(self, chunk_id: str) -> EventChunk | None:
        """Fetch a single chunk by id, or ``None`` if it does not exist.

        Used by the ingest path's status reconciliation and by tests
        that need to inspect a chunk's ``embedding_status`` without
        going through retrieval (D-025).
        """

    def save_embedding_records(self, records: list[EmbeddingRecord]) -> None:
        """Persist one embedding row per chunk per model (D-024).

        Backends enforce ``UNIQUE (chunk_id, model_name)`` so a future
        model migration writes a second row rather than mutating the old
        one; this call must not be invoked twice for the same pair under
        a single ingest.
        """

    def count_embedding_records_for_source(self, source_message_id: str) -> int:
        """Count embedding rows persisted for a given source."""

    def set_chunk_embedding_status(self, chunk_id: str, status: EmbeddingStatus) -> None:
        """Transition a single chunk's ``embedding_status`` (D-024).

        ``ready`` after the embedding row is persisted; ``failed`` if the
        provider call raised. The chunk row itself is always intact
        (I-3, R-1).
        """

    def save_query(self, query: Query) -> None:
        """Persist a single ``Query`` row for an ``/ask`` call (Slice 3.5)."""

    def save_retrieval_hits(self, hits: list[RetrievalHit]) -> None:
        """Persist zero-or-more ``RetrievalHit`` rows for a query (Slice 3.5)."""

    def get_query(self, query_id: str) -> Query | None:
        """Fetch a single ``Query`` by id, or ``None`` (Slice 3.5)."""

    def get_retrieval_hits_for_query(self, query_id: str) -> list[RetrievalHit]:
        """Return all ``RetrievalHit`` rows for a query (Slice 3.5).

        Ordering is stable for inspection: ``(leg ASC, rank ASC)``.
        """

    def save_answer_trace(self, trace: AnswerTrace) -> None:
        """Persist one ``AnswerTrace`` row per ``/ask`` reply (Slice 4.3a, D-034).

        Backends enforce ``UNIQUE (query_id)`` so a single ``Query`` has at
        most one ``AnswerTrace`` — the answer-side counterpart of the
        D-032 retrieval traces. The caller is ``QueryService.answer`` on
        the success and no-evidence/empty-query contours.
        """

    def get_answer_trace_for_query(self, query_id: str) -> AnswerTrace | None:
        """Fetch the ``AnswerTrace`` for a query, or ``None`` (Slice 4.3a)."""
