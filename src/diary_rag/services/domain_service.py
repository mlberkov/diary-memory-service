"""Channel-neutral ingestion service.

Persists the raw inbound message first (Invariant I-3, runtime R-1),
then — for note-lifecycle messages (``RouteKind.NOTE``) — parses the
date-led payload and creates one ``Note`` plus one ``EventChunk``
per event line (I-5). Authorship and family scope are carried through
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
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from diary_rag.core.domain import (
    EventChunk,
    FallbackMode,
    IngestResult,
    Note,
    SourceMessage,
    parse_note,
)
from diary_rag.core.embeddings import EmbeddingClient, EmbeddingRecord, EmbeddingStatus
from diary_rag.core.routing import InboundMessage, RouteKind
from diary_rag.logging import get_logger
from diary_rag.storage.repository import DomainRepository

log = get_logger(__name__)


def _community_id_for(message: InboundMessage) -> str:
    """Per-chat surrogate until explicit family bootstrap exists (A-14)."""
    return message.external_chat_id


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
        community_id = _community_id_for(message)
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

        note_id = str(uuid4())
        note = Note(
            note_id=note_id,
            source_message_id=source_message_id,
            community_id=community_id,
            author_user_id=author_user_id,
            note_date=parsed.note_date,
            note_text="\n".join(parsed.events),
            created_at=now,
        )
        self._store.save_note(note)

        chunks = [
            EventChunk(
                chunk_id=str(uuid4()),
                note_id=note_id,
                source_message_id=source_message_id,
                community_id=community_id,
                author_user_id=author_user_id,
                note_date=parsed.note_date,
                event_index=i,
                chunk_text=line,
                created_at=now,
            )
            for i, line in enumerate(parsed.events)
        ]
        self._store.save_event_chunks(chunks)

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
            log.warning(
                "embedding.failed source_message_id=%s model=%s chunks=%d error_class=%s",
                source_message_id,
                client.model_name,
                len(chunks),
                exc.__class__.__name__,
            )
            for chunk in chunks:
                self._store.set_chunk_embedding_status(chunk.chunk_id, EmbeddingStatus.FAILED)
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
        """Return the most recent ``RouteKind.DRAFT`` source messages for a family.

        Family-scoped, ordered most-recent-first, capped at ``limit``.
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
