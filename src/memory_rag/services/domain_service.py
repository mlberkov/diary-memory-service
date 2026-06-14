"""Channel-neutral ingestion service.

Persists the raw inbound message first (Invariant I-3, runtime R-1),
then — for note-lifecycle messages (``RouteKind.NOTE``) — parses the
date-led payload and creates one ``Note`` plus exactly one ``EventChunk``
holding the whole note body (I-5 / D-106); a date-only note creates the
``Note`` with no chunk. Authorship and community scope are carried through
(I-6, I-7).

Draft floor (D-027 / R-13): when the inbound route is
``RouteKind.DRAFT`` — set by the no-command default for plain text —
the source row is committed and the service returns without parsing,
chunking, or embedding. Drafts can be recalled via ``/drafts`` (D-030)
but are not note-candidates and have no promotion path.

Idempotency (R-2 / D-023): the source row is committed via
``DomainRepository.get_or_create_source_message`` keyed on
``(external_chat_id, external_message_id, edit_seq)``. A replay short-
circuits parse, chunking, and the embedding step (D-024) and
reconstructs the original ``IngestResult`` from persisted state; the
persisted ``detected_route`` tells the reconstruction whether the row
was a draft or a note.

Supersession (ED-2 / D-114): an edited message arrives with a new
``edit_seq`` (the ``edit_date`` epoch), so it is a fresh, non-replayed
source row. When it parses as a note and a prior ``active`` note already
exists for the same external message, the new revision is created
``active`` with ``supersedes_note_id`` / ``supersedes_chunk_id`` lineage
to the prior, the prior note and chunk are flipped to ``superseded``
(retained, not mutated or destroyed — source lineage and I-6 authorship
survive), and the new chunk is re-embedded by the embedding step below.
Both retrieval legs exclude the superseded revision immediately (R-4),
regardless of embedding state. Supersession is NOTE->NOTE only: a draft
edit and an unparseable edit short-circuit above, so they never supersede
the prior good revision; a fresh original finds no prior and is unchanged.

Deletion (ED-3 / D-114): the soft-delete default tombstones the active
revision (I-13). Two paths reach it. The ``/delete`` control surface calls
``delete_note_for_external_message`` for the note the user replies to; and a
NOTE->DRAFT edit — a captured ``/note`` edited to drop its command — tombstones
the prior active note from the DRAFT branch above. Both flip the active chunk
then the note to ``tombstoned`` (retained with I-6 authorship intact; excluded
from retrieval immediately, R-4) and are fail-closed no-ops when no active note
matches. Hard deletion of raw source data is the separate, explicit, audited
``hard_delete_source_message`` operation (I-13) — not a control-surface command.

Phase 3.1+3.2 embedding step (D-024): after the chunk rows are
committed, the configured ``EmbeddingClient`` is called once per
ingest with the chunk texts. On success, one ``EmbeddingRecord`` per
chunk is persisted and the chunk ``embedding_status`` flips to
``ready``. On any provider exception, chunks remain intact, their
status flips to ``failed``, zero embedding rows are written for that
source, and the ingest result remains ``FallbackMode.NONE`` — raw and
chunk lineage survived; embedding is downstream enrichment (I-2, I-3).
Failed chunks stay failed until a future Phase-6 reconciliation job
(A-35); replay does not retry.

Dead-letter surface (Slice 6.2): on that same provider exception the
service additionally attempts to persist one ``IndexingDeadLetter``
row recording the failed indexing job. That write is best-effort — it
runs after the ``embedding_status='failed'`` marking and a failure of
its own is logged and swallowed, so it can never undo the A-35
marking. ``event_chunks.embedding_status`` stays the authoritative
failure signal.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from memory_rag.core.domain import (
    DeleteOutcome,
    EventChunk,
    FallbackMode,
    HardDeleteOutcome,
    IndexingDeadLetter,
    IngestResult,
    Note,
    SourceMessage,
    parse_note,
)
from memory_rag.core.embeddings import EmbeddingClient, EmbeddingRecord, EmbeddingStatus
from memory_rag.core.routing import InboundMessage, RouteKind
from memory_rag.logging import get_logger
from memory_rag.storage.repository import DomainRepository

log = get_logger(__name__)


def _first_line(text: str) -> str:
    return text.splitlines()[0].strip() if text else ""


class DomainService:
    """Ingests an ``InboundMessage`` carrying a ``/note`` payload."""

    def __init__(
        self,
        store: DomainRepository,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self._store = store
        self._embedding_client = embedding_client

    def ingest(self, message: InboundMessage) -> IngestResult:
        now = datetime.now(tz=UTC)
        # Opaque community scope resolved by the adapter at the edge (D-093 /
        # G-1); the core never re-derives it from external_chat_id (I-1).
        community_id = message.community_id
        # Opaque subject scope assigned by the adapter axis (H-2 / D-097),
        # subordinate to community_id; None = community-wide. Carried onto
        # Note / EventChunk; the core never derives it from a host field (I-1).
        subject_id = message.subject_id
        author_user_id = message.external_user_id
        candidate_id = str(uuid4())

        candidate = SourceMessage(
            source_message_id=candidate_id,
            community_id=community_id,
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

        if message.route is RouteKind.DRAFT:
            # NOTE->DRAFT removal (ED-3 / D-114): editing a captured /note to drop
            # its command re-routes the edited delivery to DRAFT. If a prior
            # active note exists for this external message the edit expresses a
            # removal, so the prior note (+ chunk) is tombstoned — retrieval-
            # effective immediately (R-4), retained with I-6 authorship intact. A
            # fresh plain-text draft finds no prior active note and is unchanged.
            self._tombstone_active_note_for_external_message(
                message.external_chat_id, message.external_message_id, community_id
            )
            log.info(
                "draft.persisted source_message_id=%s community_id=%s effective_path=fresh",
                source_message_id,
                community_id,
            )
            return IngestResult(
                fallback=FallbackMode.NONE,
                source_message_id=source_message_id,
            )

        parsed = parse_note(message.payload)
        if parsed is None:
            return IngestResult(
                fallback=FallbackMode.INVALID_INPUT,
                source_message_id=source_message_id,
                invalid_first_line=_first_line(message.payload),
            )

        # Supersession (ED-2 / D-114): an edited /note creates a new revision
        # that supersedes the prior active one. The trigger is "a prior active
        # note exists for this external message," not the edit_seq value — a
        # redelivered edit short-circuits on replay above, a draft edit on the
        # DRAFT branch, and an unparseable edit on INVALID_INPUT, so only a
        # NOTE->NOTE edit (or a fresh original, which finds no prior) reaches
        # here. A fresh original leaves both lineage links None (unchanged
        # behavior). The prior revision is retained — only its lifecycle_state
        # flips — so source lineage and I-6 authorship survive.
        prior_note = self._store.get_active_note_for_external_message(
            message.external_chat_id,
            message.external_message_id,
            community_id=community_id,
        )
        prior_chunk = (
            self._store.get_active_chunk_for_note(prior_note.note_id, community_id=community_id)
            if prior_note is not None
            else None
        )

        note_id = str(uuid4())
        note = Note(
            note_id=note_id,
            source_message_id=source_message_id,
            community_id=community_id,
            author_user_id=author_user_id,
            note_date=parsed.note_date,
            note_text=parsed.body,
            created_at=now,
            subject_id=subject_id,
            supersedes_note_id=prior_note.note_id if prior_note is not None else None,
        )
        self._store.save_note(note)

        # One explicit /note is exactly one EventChunk holding the whole body
        # (I-5 / D-106); a date-only note (empty body) creates no chunk.
        chunks = (
            [
                EventChunk(
                    chunk_id=str(uuid4()),
                    note_id=note_id,
                    source_message_id=source_message_id,
                    community_id=community_id,
                    author_user_id=author_user_id,
                    note_date=parsed.note_date,
                    event_index=0,
                    chunk_text=parsed.body,
                    created_at=now,
                    subject_id=subject_id,
                    supersedes_chunk_id=(prior_chunk.chunk_id if prior_chunk is not None else None),
                )
            ]
            if parsed.body
            else []
        )
        self._store.save_event_chunks(chunks)

        # Flip the prior revision to superseded only after the new active
        # revision is durably saved (a partial failure never leaves zero active
        # revisions), and flip the chunk before the note: retrieval filters on
        # the chunk's lifecycle_state, so closing chunk visibility first makes
        # the edit retrieval-effective immediately, regardless of embedding
        # state. The superseded chunk is never re-embedded.
        if prior_chunk is not None:
            self._store.mark_chunk_superseded(prior_chunk.chunk_id, community_id=community_id)
        if prior_note is not None:
            self._store.mark_note_superseded(prior_note.note_id, community_id=community_id)
            log.info(
                "edit.superseded community_id=%s prior_note_id=%s new_note_id=%s",
                community_id,
                prior_note.note_id,
                note_id,
            )

        if chunks and self._embedding_client is not None:
            self._embed_chunks(chunks, source_message_id, community_id, now)

        return IngestResult(
            fallback=FallbackMode.NONE,
            source_message_id=source_message_id,
            note_date=parsed.note_date,
            events_count=len(chunks),
        )

    def _embed_chunks(
        self,
        chunks: list[EventChunk],
        source_message_id: str,
        community_id: str,
        now: datetime,
    ) -> None:
        client = self._embedding_client
        assert client is not None
        try:
            vectors = client.embed([c.chunk_text for c in chunks])
        except Exception as exc:
            dead_letter_id = str(uuid4())
            error_class = exc.__class__.__name__
            log.warning(
                "embedding.failed source_message_id=%s model=%s chunks=%d "
                "error_class=%s dead_letter_id=%s",
                source_message_id,
                client.model_name,
                len(chunks),
                error_class,
                dead_letter_id,
            )
            # A-35 failure marking runs first and unchanged: the best-effort
            # dead-letter write below must never be able to suppress it.
            for chunk in chunks:
                self._store.set_chunk_embedding_status(chunk.chunk_id, EmbeddingStatus.FAILED)
            # Dead-letter surface (Slice 6.2): record the failed indexing job.
            # Best-effort — a failure here is logged and swallowed so it cannot
            # undo the failure marking; embedding_status stays authoritative.
            dead_letter = IndexingDeadLetter(
                dead_letter_id=dead_letter_id,
                source_message_id=source_message_id,
                community_id=community_id,
                chunk_ids=tuple(c.chunk_id for c in chunks),
                model_name=client.model_name,
                error_class=error_class,
                created_at=now,
            )
            try:
                self._store.save_indexing_dead_letter(dead_letter)
            except Exception as dead_letter_exc:
                log.warning(
                    "dead_letter.write_failed dead_letter_id=%s error_class=%s",
                    dead_letter_id,
                    dead_letter_exc.__class__.__name__,
                )
            return

        records = [
            EmbeddingRecord(
                embedding_record_id=str(uuid4()),
                chunk_id=chunk.chunk_id,
                source_message_id=source_message_id,
                community_id=community_id,
                model_name=client.model_name,
                dimension=client.dimension,
                embedding=vec,
                created_at=now,
            )
            for chunk, vec in zip(chunks, vectors, strict=True)
        ]
        self._store.save_embedding_records(records)
        for chunk in chunks:
            self._store.set_chunk_embedding_status(chunk.chunk_id, EmbeddingStatus.READY)
        log.info(
            "embedding.ok source_message_id=%s model=%s chunks=%d dim=%d",
            source_message_id,
            client.model_name,
            len(chunks),
            client.dimension,
        )

    def list_recent_drafts(self, community_id: str, *, limit: int) -> list[SourceMessage]:
        """Return the most recent ``RouteKind.DRAFT`` source messages for a community.

        Community-scoped, ordered most-recent-first, capped at ``limit``.
        Read-only; no side effects. The dispatcher validates ``limit``;
        the assert below is defensive.
        """
        if limit < 1:
            raise ValueError("limit must be >= 1")
        drafts = self._store.list_recent_drafts(community_id, limit=limit)
        log.info(
            "drafts.recalled community_id=%s requested=%d returned=%d",
            community_id,
            limit,
            len(drafts),
        )
        return drafts

    def _reconstruct_result(self, source: SourceMessage) -> IngestResult:
        """Rebuild the original ``IngestResult`` from persisted state (R-2)."""
        if source.detected_route is RouteKind.DRAFT:
            log.info(
                "draft.persisted source_message_id=%s community_id=%s effective_path=replay",
                source.source_message_id,
                source.community_id,
            )
            return IngestResult(
                fallback=FallbackMode.NONE,
                source_message_id=source.source_message_id,
                replayed=True,
            )
        note = self._store.get_note_by_source_message_id(source.source_message_id)
        if note is None:
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
            note_date=note.note_date,
            events_count=events_count,
            replayed=True,
        )

    def _tombstone_active_note_for_external_message(
        self, external_chat_id: str, external_message_id: str, community_id: str
    ) -> Note | None:
        """Tombstone the active note (+ chunk) for an external message, if any.

        Shared by the ``/delete`` control path and the NOTE->DRAFT edit-removal
        path. Looks up the single ``active`` note for the external message
        (community-scoped); when present, flips its active chunk then the note to
        ``tombstoned`` (chunk-first, so the delete is retrieval-effective
        immediately — R-4 — regardless of embedding state). The prior rows are
        retained (raw + lineage + I-6 authorship intact). Returns the tombstoned
        note, or ``None`` when there is no active note — a fail-closed no-op for
        an unknown, non-note, already-deleted, or cross-community target.
        """
        prior_note = self._store.get_active_note_for_external_message(
            external_chat_id, external_message_id, community_id=community_id
        )
        if prior_note is None:
            return None
        prior_chunk = self._store.get_active_chunk_for_note(
            prior_note.note_id, community_id=community_id
        )
        if prior_chunk is not None:
            self._store.mark_chunk_tombstoned(prior_chunk.chunk_id, community_id=community_id)
        self._store.mark_note_tombstoned(prior_note.note_id, community_id=community_id)
        log.info(
            "delete.tombstoned community_id=%s note_id=%s external_message_id=%s",
            community_id,
            prior_note.note_id,
            external_message_id,
        )
        return prior_note

    def delete_note_for_external_message(
        self, external_chat_id: str, target_external_message_id: str, *, community_id: str
    ) -> DeleteOutcome:
        """Tombstone the active note a ``/delete`` targets (ED-3 / D-114).

        The ``/delete`` control surface resolves its target by reply: the user
        replies to the original ``/note`` message, so ``target_external_message_id``
        is that replied-to message. Soft delete by default (I-13): the active
        revision is tombstoned (retained; excluded from retrieval immediately,
        R-4). Every fail-closed miss — no active note for the target, an unknown
        or non-note target, an already-deleted target, or a target owned by
        another community — returns ``deleted=False`` (a friendly no-op, never an
        error). Idempotent: a second ``/delete`` finds no active note and is a
        no-op.
        """
        tombstoned = self._tombstone_active_note_for_external_message(
            external_chat_id, target_external_message_id, community_id
        )
        if tombstoned is None:
            return DeleteOutcome(deleted=False)
        return DeleteOutcome(deleted=True, note_date=tombstoned.note_date)

    def hard_delete_source_message(
        self, source_message_id: str, *, community_id: str, requested_by: str
    ) -> HardDeleteOutcome:
        """Operator-only audited hard-delete of a raw source message (ED-3 / I-13).

        The explicit, audited counterpart to the soft-delete default (I-13): it
        physically removes the targeted ``source_messages`` row and every row
        derived from it within ``community_id`` (notes, event chunks, embedding
        records, and the retrieval-hit traces referencing those chunks). This is
        **not** a control-surface command — there is no ``RouteKind`` for it; an
        operator calls it deliberately. The audit trail is the structured
        ``audit.hard_delete`` log record emitted here (requester + target +
        per-table tally) — the provenance the soft-default reserves for raw
        removal. Community scoping is fail-closed (I-7, R-3): an empty
        ``community_id`` raises ``ValueError``; an unknown or cross-community
        target raises ``KeyError`` and removes nothing.
        """
        outcome = self._store.hard_delete_source_message(
            source_message_id, community_id=community_id
        )
        log.info(
            "audit.hard_delete community_id=%s requested_by=%s source_message_id=%s "
            "source_messages=%d notes=%d event_chunks=%d embedding_records=%d "
            "retrieval_hits=%d",
            community_id,
            requested_by,
            source_message_id,
            outcome.source_messages,
            outcome.notes,
            outcome.event_chunks,
            outcome.embedding_records,
            outcome.retrieval_hits,
        )
        return outcome
