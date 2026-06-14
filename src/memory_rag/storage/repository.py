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

from memory_rag.core.chat.models import ChatKnowledgeSearch, ChatQueryRewrite, ChatRouteDecision
from memory_rag.core.domain.models import (
    AnswerTrace,
    EventChunk,
    HardDeleteOutcome,
    IndexingDeadLetter,
    Note,
    Query,
    RetrievalHit,
    SourceMessage,
)
from memory_rag.core.embeddings.models import EmbeddingRecord, EmbeddingStatus


class DomainRepository(Protocol):
    """Persistence surface used by ``DomainService`` and ``QueryService``."""

    def save_source_message(self, source: SourceMessage) -> None: ...

    def save_note(self, note: Note) -> None: ...

    def save_event_chunks(self, chunks: list[EventChunk]) -> None: ...

    def get_source_message(
        self, source_message_id: str, *, community_id: str
    ) -> SourceMessage | None:
        """Fetch a single source message by id within a community, or ``None``.

        Community scoping is mandatory and fail-closed (I-7, R-3;
        Slice 8.1.2): a null/empty ``community_id`` raises; a source owned
        by a different community reads as ``None`` (own-column filter).
        ``community_id`` is keyword-only to prevent a silent positional
        swap between two ``str`` identifiers (D-088, D-089). The sole live
        caller is the ``/sources`` author-resolution bridge
        (`adapters/telegram/author_display.resolve_chunk_author_display`),
        which passes the requester-scoped community.
        """

    def list_source_messages(
        self, community_id: str, *, limit: int | None = None
    ) -> list[SourceMessage]:
        """List raw source messages for a community in deterministic order.

        Order: ``(created_at ASC, source_message_id ASC)``. Includes every
        persisted route (notes and drafts alike). Community scoping is
        mandatory (I-7). ``limit`` caps the result; ``None`` means no
        cap. Backends without raw-export parity (SQLite is opt-in
        ingest-only) raise ``NotImplementedError`` (D-029).
        """

    def list_recent_drafts(self, community_id: str, *, limit: int) -> list[SourceMessage]:
        """Return the most recent draft source messages for a community.

        Filter: ``detected_route == RouteKind.DRAFT``. Order:
        ``(created_at DESC, source_message_id DESC)``. Community scoping is
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

    def get_note_by_source_message_id(self, source_message_id: str) -> Note | None:
        """Fetch the note persisted for a given source, if any.

        Used by the ingest path to reconstruct the original ``IngestResult``
        on replay without re-parsing or re-chunking.
        """

    def get_active_note_for_external_message(
        self, external_chat_id: str, external_message_id: str, *, community_id: str
    ) -> Note | None:
        """Return the single ``active`` note for an external message, or ``None`` (ED-2, D-114).

        Resolves the prior live revision when an edited delivery arrives:
        joins ``notes`` to ``source_messages`` on ``source_message_id`` and
        filters ``source_messages.external_chat_id`` /
        ``external_message_id``, ``notes.community_id``, and
        ``notes.lifecycle_state='active'``. At most one ``active`` note
        matches under normal operation (the ``/edit`` supersession writer
        flips the prior to ``superseded`` in the same ingest); the seam is
        kept total under an out-of-scope concurrent-edit race by returning
        the most recent (``created_at DESC, note_id DESC``). Community
        scoping is mandatory and fail-closed (I-7, R-3): a null/empty
        ``community_id`` raises; a note owned by a different community reads
        as ``None``. ``community_id`` is keyword-only to prevent a silent
        positional swap between two ``str`` identifiers (D-088).
        """

    def count_event_chunks_for_source(self, source_message_id: str) -> int:
        """Count event chunks persisted for a given source."""

    def get_event_chunk(self, chunk_id: str, *, community_id: str) -> EventChunk | None:
        """Fetch a single chunk by id within a community, or ``None`` (D-025).

        Used by the ingest path's status reconciliation and by tests
        that need to inspect a chunk's ``embedding_status`` without
        going through retrieval. Community scoping is mandatory and
        fail-closed (I-7, R-3; Slice 8.1.1): a null/empty ``community_id``
        raises; a chunk owned by a different community reads as ``None``.
        ``community_id`` is keyword-only to prevent a silent positional
        swap between two ``str`` identifiers (D-088).
        """

    def get_active_chunk_for_note(self, note_id: str, *, community_id: str) -> EventChunk | None:
        """Return the single ``active`` chunk of a note, or ``None`` (ED-2, D-114).

        Used by the ``/edit`` supersession writer to find the prior
        revision's chunk for ``supersedes_chunk_id`` lineage. A date-only
        note has no chunk; one explicit ``/note`` is exactly one chunk
        (I-5 / D-106), so this returns at most one row (deterministic under
        any out-of-scope race via ``created_at DESC, chunk_id DESC``).
        Community scoping is mandatory and fail-closed (I-7, R-3): a
        null/empty ``community_id`` raises; a chunk owned by a different
        community reads as ``None``. ``community_id`` is keyword-only
        (D-088).
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

    def mark_note_superseded(self, note_id: str, *, community_id: str) -> None:
        """Flip a note's ``lifecycle_state`` ``active`` -> ``superseded`` (ED-2, D-114).

        The ``/edit`` supersession writer's note-level transition: the prior
        revision is retained (raw + chunk lineage + I-6 authorship intact)
        and marked inactive so retrieval excludes it (R-4). Mirrors
        ``set_chunk_embedding_status``' shape — a single-row UPDATE that
        raises ``KeyError`` when no row matches — but is **community-scoped**
        (the UPDATE filters ``community_id``) so a cross-community flip is
        structurally impossible (I-7, R-3); a null/empty ``community_id``
        raises ``ValueError``. ``community_id`` is keyword-only (D-088). ED-2
        only ever writes ``superseded``; the ``tombstoned`` transition is
        ED-3.
        """

    def mark_chunk_superseded(self, chunk_id: str, *, community_id: str) -> None:
        """Flip a chunk's ``lifecycle_state`` ``active`` -> ``superseded`` (ED-2, D-114).

        The chunk-level counterpart of ``mark_note_superseded`` — the
        retrieval-visible flip (both legs filter the chunk's
        ``lifecycle_state``). Same single-row, community-scoped,
        ``KeyError``-on-miss shape; ``community_id`` is keyword-only and a
        null/empty value raises ``ValueError`` (I-7, R-3, D-088).
        """

    def mark_note_tombstoned(self, note_id: str, *, community_id: str) -> None:
        """Flip a note's ``lifecycle_state`` ``active`` -> ``tombstoned`` (ED-3, D-114).

        The ``/delete`` writer's note-level transition: the active revision is
        soft-deleted (I-13) — retained (raw + chunk lineage + I-6 authorship
        intact) and marked inactive so retrieval excludes it (R-4). The
        tombstone counterpart of ``mark_note_superseded``; same single-row,
        community-scoped, ``KeyError``-on-miss shape, ``community_id`` keyword-only
        and a null/empty value raises ``ValueError`` (I-7, R-3, D-088). Writes
        only ``tombstoned``.
        """

    def mark_chunk_tombstoned(self, chunk_id: str, *, community_id: str) -> None:
        """Flip a chunk's ``lifecycle_state`` ``active`` -> ``tombstoned`` (ED-3, D-114).

        The chunk-level counterpart of ``mark_note_tombstoned`` — the
        retrieval-visible flip (both legs filter the chunk's ``lifecycle_state``,
        so the delete is effective immediately, regardless of
        ``embedding_status``). Same single-row, community-scoped,
        ``KeyError``-on-miss shape; ``community_id`` is keyword-only and a
        null/empty value raises ``ValueError`` (I-7, R-3, D-088).
        """

    def hard_delete_source_message(
        self, source_message_id: str, *, community_id: str
    ) -> HardDeleteOutcome:
        """Physically delete a raw source message and its derived rows (ED-3, I-13).

        The explicit, audited hard-delete the soft-delete default (I-13) reserves
        for raw-data removal. Deletes exactly the targeted ``source_messages``
        row and every row derived from it **within the same community** — its
        notes, event chunks, embedding records, and the retrieval-hit trace rows
        that reference those chunks — in FK-safe order inside one transaction
        (the baseline schema declares no ``ON DELETE CASCADE``). Community scoping
        is mandatory and fail-closed (I-7, R-3): a null/empty ``community_id``
        raises ``ValueError``; an unknown or cross-community target is not found
        and raises ``KeyError`` (nothing is deleted). Returns the per-table
        :class:`HardDeleteOutcome` tally; the caller emits the audit record.
        """

    def list_failed_event_chunks(
        self, community_id: str, *, limit: int | None = None
    ) -> list[EventChunk]:
        """List chunks stuck at ``embedding_status='failed'`` for a community (OP-3.1).

        The discovery seam for failed-embedding reconciliation: returns
        every ``EventChunk`` whose ``embedding_status`` is
        ``EmbeddingStatus.FAILED`` within ``community_id``. Order:
        ``(created_at ASC, chunk_id ASC)`` — oldest failure first, the
        FIFO order a future retry job consumes. Community scoping is
        mandatory (I-7, R-3). ``limit`` caps the result; ``None`` means
        no cap. When the result size equals ``limit`` more failed chunks
        may exist beyond the cap — this method reports a bounded slice,
        not a total. Read-only: it transitions no status.
        """

    def save_query(self, query: Query) -> None:
        """Persist a single ``Query`` row for an ``/ask`` call (Slice 3.5)."""

    def save_retrieval_hits(self, hits: list[RetrievalHit]) -> None:
        """Persist zero-or-more ``RetrievalHit`` rows for a query (Slice 3.5)."""

    def get_query(self, query_id: str, *, community_id: str) -> Query | None:
        """Fetch a single ``Query`` by id within a community, or ``None`` (Slice 3.5).

        Community scoping is mandatory and fail-closed (I-7, R-3;
        Slice 8.1.1): a null/empty ``community_id`` raises; a query owned
        by a different community reads as ``None``. ``community_id`` is
        keyword-only to prevent a silent positional swap between two
        ``str`` identifiers (D-088).
        """

    def get_retrieval_hits_for_query(
        self, query_id: str, *, community_id: str
    ) -> list[RetrievalHit]:
        """Return all ``RetrievalHit`` rows for a query in a community (Slice 3.5).

        Ordering is stable for inspection: ``(leg ASC, rank ASC)``.
        Community scoping is mandatory and fail-closed (I-7, R-3;
        Slice 8.1.1): a null/empty ``community_id`` raises; hits are
        scoped via the parent ``queries.community_id`` (the
        ``query_id -> queries`` join) since a ``RetrievalHit`` carries no
        ``community_id`` of its own, so a query owned by a different
        community reads as ``[]``. ``community_id`` is keyword-only to
        prevent a silent positional swap between two ``str`` identifiers
        (D-088).
        """

    def save_answer_trace(self, trace: AnswerTrace) -> None:
        """Persist one ``AnswerTrace`` row per ``/ask`` reply (Slice 4.3a, D-034).

        Backends enforce ``UNIQUE (query_id)`` so a single ``Query`` has at
        most one ``AnswerTrace`` — the answer-side counterpart of the
        D-032 retrieval traces. The caller is ``QueryService.answer`` on
        the success and no-evidence/empty-query contours.
        """

    def get_answer_trace_for_query(self, query_id: str, *, community_id: str) -> AnswerTrace | None:
        """Fetch the ``AnswerTrace`` for a query in a community, or ``None`` (Slice 4.3a).

        Community scoping is mandatory and fail-closed (I-7, R-3;
        Slice 8.1.1): a null/empty ``community_id`` raises; the trace is
        scoped via the parent ``queries.community_id`` (the
        ``query_id -> queries`` join), since ``answer_traces`` carries no
        ``community_id`` column (D-087 adds none), so a query owned by a
        different community reads as ``None``. ``community_id`` is
        keyword-only to prevent a silent positional swap between two
        ``str`` identifiers (D-088).
        """

    def save_chat_route_decision(self, decision: ChatRouteDecision) -> None:
        """Persist one routing-decision row per ``/chat`` call (RC-2, D-108).

        The caller is ``RoutedChatService.chat`` on every contour — the
        decision row is the R-6 requested-vs-effective record for the
        routed surface. Append-only: backends never update or delete it.
        """

    def get_chat_route_decision(
        self, decision_id: str, *, community_id: str
    ) -> ChatRouteDecision | None:
        """Fetch a routing decision by id within a community, or ``None`` (RC-2).

        Community scoping is mandatory and fail-closed (I-7, R-3): a
        null/empty ``community_id`` raises; a decision owned by a
        different community reads as ``None`` — the row carries its own
        ``community_id`` column, so no parent join is needed.
        ``community_id`` is keyword-only to prevent a silent positional
        swap between two ``str`` identifiers (D-088).
        """

    def save_chat_query_rewrite(self, rewrite: ChatQueryRewrite) -> None:
        """Persist one rewrite-trace row per ``notes_plus_model`` execution (RC-3).

        The caller is ``RoutedChatService.chat``, strictly after the
        :class:`ChatRouteDecision` row the rewrite links to. At most one
        rewrite row exists per decision (backends enforce uniqueness on
        ``decision_id``). Append-only: backends never update or delete
        it.
        """

    def get_chat_query_rewrite_for_decision(
        self, decision_id: str, *, community_id: str
    ) -> ChatQueryRewrite | None:
        """Fetch the rewrite row for a decision within a community, or ``None`` (RC-3).

        Community scoping is mandatory and fail-closed (I-7, R-3): a
        null/empty ``community_id`` raises; a rewrite owned by a
        different community reads as ``None`` — the row carries its own
        ``community_id`` column, so no parent join is needed.
        ``community_id`` is keyword-only to prevent a silent positional
        swap between two ``str`` identifiers (D-088).
        """

    def save_chat_knowledge_search(self, search: ChatKnowledgeSearch) -> None:
        """Persist one knowledge-search trace row per ``notes_plus_knowledge`` execution (RC-4).

        The caller is ``RoutedChatService.chat``, strictly after the
        :class:`ChatRouteDecision` row the search links to. At most one
        search row exists per decision (backends enforce uniqueness on
        ``decision_id``). Append-only: backends never update or delete
        it.
        """

    def get_chat_knowledge_search_for_decision(
        self, decision_id: str, *, community_id: str
    ) -> ChatKnowledgeSearch | None:
        """Fetch the knowledge-search row for a decision within a community, or ``None`` (RC-4).

        Community scoping is mandatory and fail-closed (I-7, R-3): a
        null/empty ``community_id`` raises; a search owned by a
        different community reads as ``None`` — the row carries its own
        ``community_id`` column, so no parent join is needed.
        ``community_id`` is keyword-only to prevent a silent positional
        swap between two ``str`` identifiers (D-088).
        """

    def save_indexing_dead_letter(self, record: IndexingDeadLetter) -> None:
        """Persist one dead-letter row for a failed indexing job (Slice 6.2).

        Called by ``DomainService`` when an embedding call fails during
        ingest, alongside the per-chunk ``embedding_status='failed'``
        marking. The record is append-only — backends never update or
        delete it. The caller treats this write as best-effort: a
        backend failure here must not undo the failure marking.
        """

    def list_indexing_dead_letters(
        self, community_id: str, *, limit: int | None = None
    ) -> list[IndexingDeadLetter]:
        """List dead-letter rows for a community in deterministic order.

        Order: ``(created_at DESC, dead_letter_id DESC)`` — most recent
        failures first. Community scoping is mandatory (I-7). ``limit``
        caps the result; ``None`` means no cap.
        """

    def get_indexing_dead_letter(self, dead_letter_id: str) -> IndexingDeadLetter | None:
        """Fetch a single dead-letter row by id, or ``None`` (Slice 6.2)."""
