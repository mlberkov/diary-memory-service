"""Local PostgreSQL store implementing ``DomainRepository`` and
``SearchRepository`` (D-022, D-023, D-024, D-025).

Schema is bootstrapped at construction by applying the versioned migrations
under ``migrations/`` to head via
:mod:`memory_rag.storage.postgres.migrations_runner` (OP-1.1 / D-045). The
migration history is the single canonical schema source. Connections are
managed by a small :class:`psycopg_pool.ConnectionPool`. Native Postgres
types are used for ``TIMESTAMPTZ`` and ``DATE``; ``detected_route`` is TEXT
with a CHECK listing every :class:`RouteKind` value.

Idempotency (R-2 / D-023) is enforced by the
``UNIQUE (external_chat_id, external_message_id, edit_seq)`` constraint on
``source_messages`` plus ``INSERT ... ON CONFLICT DO NOTHING`` in
``get_or_create_source_message``: the DB is the source of truth for "this
message-state has already been ingested," not a SELECT-then-INSERT race.

Phase 3.1+3.2 (D-024): the pgvector ``vector(3072)`` column on
``embedding_records`` matches the production embedding contour
(``text-embedding-3-large``, 3072 dim). The ``pgvector`` Python package
is registered on each pooled connection so list[float] writes and reads
go through native binding. ``embedding_status`` on ``event_chunks`` is
the per-chunk observable state (``pending`` / ``ready`` / ``failed``).

Slice 3.3 (D-025): baseline hybrid retrieval. The dense leg is an exact
community-scoped sequential scan ordered by ``embedding <=> query`` (cosine
distance) over the canonical ``vector(3072)`` column, joined to
``event_chunks`` on ``chunk_id`` and filtered to
``embedding_status='ready'`` and the active ``model_name``. The sparse
leg uses the generated stored ``chunk_text_tsv`` column built from
``to_tsvector('simple', chunk_text)`` with a GIN index, ranked by
``ts_rank_cd``. Fusion is RRF in the service layer; backends do not
calibrate scores across legs.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from pgvector.psycopg import register_vector
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from memory_rag.core.domain.models import (
    AnswerTrace,
    DateRange,
    EventChunk,
    FallbackMode,
    IndexingDeadLetter,
    Note,
    Query,
    RetrievalHit,
    RetrievalLeg,
    SourceMessage,
)
from memory_rag.core.embeddings.models import EmbeddingRecord, EmbeddingStatus
from memory_rag.core.routing import RouteKind
from memory_rag.storage.postgres.migrations_runner import apply_migrations


def _date_range_sql(date_range: DateRange | None) -> tuple[str, list[date]]:
    """Build the optional ``note_date`` predicate for a hybrid leg query.

    Returns a SQL fragment (leading space, splices onto an existing
    ``WHERE`` clause before ``ORDER BY``) and the positional params it
    introduces. Both are empty when there is no constraint, so the
    placeholder count always matches the params list (Slice 3.4, D-040).
    """
    if date_range is None:
        return "", []
    fragment = ""
    params: list[date] = []
    if date_range.start is not None:
        fragment += " AND ec.note_date >= %s"
        params.append(date_range.start)
    if date_range.end is not None:
        fragment += " AND ec.note_date <= %s"
        params.append(date_range.end)
    return fragment, params


def _configure_connection(conn: Connection[Any]) -> None:
    """Register the pgvector codec on every pooled connection."""
    register_vector(conn)


class PostgresDomainStore:
    """Local Postgres implementation of ``DomainRepository``."""

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 4) -> None:
        # Schema bootstrap: apply the versioned migrations to head before the
        # connection pool opens (OP-1.1 / D-045). The migration runner manages
        # its own connection; the baseline migration runs `CREATE EXTENSION
        # vector`, so the pool below can register the pgvector codec safely.
        apply_migrations(dsn)

        self._pool: ConnectionPool = ConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            timeout=10,
            open=False,
            configure=_configure_connection,
        )
        self._pool.open()
        self._pool.wait(timeout=10)

    def close(self) -> None:
        """Release pool resources. Safe to call multiple times."""
        self._pool.close()

    def save_source_message(self, source: SourceMessage) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO source_messages "
                "(source_message_id, community_id, author_user_id, external_chat_id, "
                " external_user_id, external_message_id, edit_seq, raw_text, "
                " detected_route, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    source.source_message_id,
                    source.community_id,
                    source.author_user_id,
                    source.external_chat_id,
                    source.external_user_id,
                    source.external_message_id,
                    source.edit_seq,
                    source.raw_text,
                    source.detected_route.value,
                    source.created_at,
                ),
            )
            conn.commit()

    def get_or_create_source_message(self, source: SourceMessage) -> tuple[SourceMessage, bool]:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "INSERT INTO source_messages "
                "(source_message_id, community_id, author_user_id, external_chat_id, "
                " external_user_id, external_message_id, edit_seq, raw_text, "
                " detected_route, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (external_chat_id, external_message_id, edit_seq) "
                "DO NOTHING",
                (
                    source.source_message_id,
                    source.community_id,
                    source.author_user_id,
                    source.external_chat_id,
                    source.external_user_id,
                    source.external_message_id,
                    source.edit_seq,
                    source.raw_text,
                    source.detected_route.value,
                    source.created_at,
                ),
            )
            inserted = cur.rowcount == 1
            if inserted:
                conn.commit()
                return source, False
            cur.execute(
                "SELECT source_message_id, community_id, author_user_id, "
                "       external_chat_id, external_user_id, external_message_id, "
                "       edit_seq, raw_text, detected_route, created_at "
                "  FROM source_messages "
                " WHERE external_chat_id = %s "
                "   AND external_message_id = %s "
                "   AND edit_seq = %s",
                (source.external_chat_id, source.external_message_id, source.edit_seq),
            )
            row = cur.fetchone()
            conn.commit()
        assert row is not None
        return _row_to_source(row), True

    def save_note(self, note: Note) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO notes "
                "(note_id, source_message_id, community_id, author_user_id, "
                " note_date, note_text, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    note.note_id,
                    note.source_message_id,
                    note.community_id,
                    note.author_user_id,
                    note.note_date,
                    note.note_text,
                    note.created_at,
                ),
            )
            conn.commit()

    def save_event_chunks(self, chunks: list[EventChunk]) -> None:
        if not chunks:
            return
        params = [
            (
                c.chunk_id,
                c.note_id,
                c.source_message_id,
                c.community_id,
                c.author_user_id,
                c.note_date,
                c.event_index,
                c.chunk_text,
                c.created_at,
                c.embedding_status.value,
            )
            for c in chunks
        ]
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO event_chunks "
                "(chunk_id, note_id, source_message_id, community_id, "
                " author_user_id, note_date, event_index, chunk_text, created_at, "
                " embedding_status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                params,
            )
            conn.commit()

    def get_source_message(self, source_message_id: str) -> SourceMessage | None:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT source_message_id, community_id, author_user_id, "
                "       external_chat_id, external_user_id, external_message_id, "
                "       edit_seq, raw_text, detected_route, created_at "
                "  FROM source_messages "
                " WHERE source_message_id = %s",
                (source_message_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return _row_to_source(row)

    def list_source_messages(
        self, community_id: str, *, limit: int | None = None
    ) -> list[SourceMessage]:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        sql = (
            "SELECT source_message_id, community_id, author_user_id, "
            "       external_chat_id, external_user_id, external_message_id, "
            "       edit_seq, raw_text, detected_route, created_at "
            "  FROM source_messages "
            " WHERE community_id = %s "
            " ORDER BY created_at ASC, source_message_id ASC"
        )
        params: tuple[object, ...] = (community_id,)
        if limit is not None:
            sql += " LIMIT %s"
            params = (community_id, limit)
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [_row_to_source(row) for row in rows]

    def list_recent_drafts(self, community_id: str, *, limit: int) -> list[SourceMessage]:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        if limit < 1:
            raise ValueError("limit must be >= 1")
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT source_message_id, community_id, author_user_id, "
                "       external_chat_id, external_user_id, external_message_id, "
                "       edit_seq, raw_text, detected_route, created_at "
                "  FROM source_messages "
                " WHERE community_id = %s AND detected_route = 'draft' "
                " ORDER BY created_at DESC, source_message_id DESC "
                " LIMIT %s",
                (community_id, limit),
            )
            rows = cur.fetchall()
        return [_row_to_source(row) for row in rows]

    def get_note_by_source_message_id(self, source_message_id: str) -> Note | None:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT note_id, source_message_id, community_id, author_user_id, "
                "       note_date, note_text, created_at "
                "  FROM notes "
                " WHERE source_message_id = %s "
                " LIMIT 1",
                (source_message_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return Note(
            note_id=row["note_id"],
            source_message_id=row["source_message_id"],
            community_id=row["community_id"],
            author_user_id=row["author_user_id"],
            note_date=row["note_date"],
            note_text=row["note_text"],
            created_at=row["created_at"],
        )

    def count_event_chunks_for_source(self, source_message_id: str) -> int:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM event_chunks WHERE source_message_id = %s",
                (source_message_id,),
            )
            row = cur.fetchone()
        if row is None:
            return 0
        return int(row[0])

    def get_event_chunk(self, chunk_id: str) -> EventChunk | None:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT chunk_id, note_id, source_message_id, community_id, "
                "       author_user_id, note_date, event_index, chunk_text, "
                "       created_at, embedding_status "
                "  FROM event_chunks "
                " WHERE chunk_id = %s",
                (chunk_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return _row_to_chunk(row)

    def dense_candidates(
        self,
        community_id: str,
        query_embedding: list[float],
        model_name: str,
        limit: int,
        *,
        date_range: DateRange | None = None,
    ) -> list[EventChunk]:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        if limit <= 0:
            return []
        date_sql, date_params = _date_range_sql(date_range)
        # Bare list[float] is encoded by psycopg as ``double precision[]``;
        # pgvector's ``<=>`` operator only accepts ``vector``. The
        # ``::vector`` cast bridges that without forcing callers to wrap
        # the embedding in a pgvector-specific type.
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT ec.chunk_id, ec.note_id, ec.source_message_id, "
                "       ec.community_id, ec.author_user_id, ec.note_date, "
                "       ec.event_index, ec.chunk_text, ec.created_at, "
                "       ec.embedding_status "
                "  FROM event_chunks ec "
                "  JOIN embedding_records er "
                "    ON er.chunk_id = ec.chunk_id AND er.model_name = %s "
                " WHERE ec.community_id = %s "
                "   AND ec.embedding_status = 'ready'" + date_sql + " "
                " ORDER BY er.embedding <=> %s::vector "
                " LIMIT %s",
                (model_name, community_id, *date_params, query_embedding, limit),
            )
            rows = cur.fetchall()
        return [_row_to_chunk(r) for r in rows]

    def sparse_candidates(
        self,
        community_id: str,
        query_text: str,
        limit: int,
        *,
        date_range: DateRange | None = None,
    ) -> list[EventChunk]:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        if limit <= 0:
            return []
        if not query_text.strip():
            return []
        date_sql, date_params = _date_range_sql(date_range)
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "WITH q AS (SELECT websearch_to_tsquery('simple', %s) AS tsq) "
                "SELECT ec.chunk_id, ec.note_id, ec.source_message_id, "
                "       ec.community_id, ec.author_user_id, ec.note_date, "
                "       ec.event_index, ec.chunk_text, ec.created_at, "
                "       ec.embedding_status "
                "  FROM event_chunks ec, q "
                " WHERE ec.community_id = %s "
                "   AND ec.chunk_text_tsv @@ q.tsq" + date_sql + " "
                " ORDER BY ts_rank_cd(ec.chunk_text_tsv, q.tsq) DESC, "
                "          ec.created_at, ec.event_index "
                " LIMIT %s",
                (query_text, community_id, *date_params, limit),
            )
            rows = cur.fetchall()
        return [_row_to_chunk(r) for r in rows]

    def save_embedding_records(self, records: list[EmbeddingRecord]) -> None:
        if not records:
            return
        params = [
            (
                r.embedding_record_id,
                r.chunk_id,
                r.source_message_id,
                r.community_id,
                r.model_name,
                r.dimension,
                r.embedding,
                r.created_at,
            )
            for r in records
        ]
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO embedding_records "
                "(embedding_record_id, chunk_id, source_message_id, community_id, "
                " model_name, dimension, embedding, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                params,
            )
            conn.commit()

    def count_embedding_records_for_source(self, source_message_id: str) -> int:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM embedding_records WHERE source_message_id = %s",
                (source_message_id,),
            )
            row = cur.fetchone()
        if row is None:
            return 0
        return int(row[0])

    def set_chunk_embedding_status(self, chunk_id: str, status: EmbeddingStatus) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE event_chunks SET embedding_status = %s WHERE chunk_id = %s",
                (status.value, chunk_id),
            )
            if cur.rowcount != 1:
                raise KeyError(f"unknown chunk_id={chunk_id}")
            conn.commit()

    def save_query(self, query: Query) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO queries "
                "(query_id, community_id, query_text, model_name, fallback, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    query.query_id,
                    query.community_id,
                    query.query_text,
                    query.model_name,
                    query.fallback.value,
                    query.created_at,
                ),
            )
            conn.commit()

    def save_retrieval_hits(self, hits: list[RetrievalHit]) -> None:
        if not hits:
            return
        params = [
            (
                h.retrieval_hit_id,
                h.query_id,
                h.chunk_id,
                h.leg.value,
                h.rank,
                h.score,
                h.model_name,
                h.created_at,
            )
            for h in hits
        ]
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO retrieval_hits "
                "(retrieval_hit_id, query_id, chunk_id, leg, rank, score, "
                " model_name, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                params,
            )
            conn.commit()

    def get_query(self, query_id: str) -> Query | None:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT query_id, community_id, query_text, model_name, fallback, "
                "       created_at "
                "  FROM queries "
                " WHERE query_id = %s",
                (query_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return Query(
            query_id=row["query_id"],
            community_id=row["community_id"],
            query_text=row["query_text"],
            model_name=row["model_name"],
            fallback=FallbackMode(row["fallback"]),
            created_at=row["created_at"],
        )

    def get_retrieval_hits_for_query(self, query_id: str) -> list[RetrievalHit]:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT retrieval_hit_id, query_id, chunk_id, leg, rank, score, "
                "       model_name, created_at "
                "  FROM retrieval_hits "
                " WHERE query_id = %s "
                " ORDER BY leg ASC, rank ASC",
                (query_id,),
            )
            rows = cur.fetchall()
        return [
            RetrievalHit(
                retrieval_hit_id=r["retrieval_hit_id"],
                query_id=r["query_id"],
                chunk_id=r["chunk_id"],
                leg=RetrievalLeg(r["leg"]),
                rank=int(r["rank"]),
                score=float(r["score"]),
                model_name=r["model_name"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def save_answer_trace(self, trace: AnswerTrace) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO answer_traces "
                "(answer_trace_id, query_id, prompt_version, context_chunk_ids, "
                " answer_text, fallback_mode, model_name, token_counts, "
                " latency_ms, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    trace.answer_trace_id,
                    trace.query_id,
                    trace.prompt_version,
                    list(trace.context_chunk_ids),
                    trace.answer_text,
                    trace.fallback_mode.value,
                    trace.model_name,
                    Jsonb(trace.token_counts),
                    trace.latency_ms,
                    trace.created_at,
                ),
            )
            conn.commit()

    def get_answer_trace_for_query(self, query_id: str) -> AnswerTrace | None:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT answer_trace_id, query_id, prompt_version, context_chunk_ids, "
                "       answer_text, fallback_mode, model_name, token_counts, "
                "       latency_ms, created_at "
                "  FROM answer_traces "
                " WHERE query_id = %s",
                (query_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        token_counts_raw = row["token_counts"]
        if isinstance(token_counts_raw, str):
            token_counts = json.loads(token_counts_raw)
        else:
            token_counts = dict(token_counts_raw)
        return AnswerTrace(
            answer_trace_id=row["answer_trace_id"],
            query_id=row["query_id"],
            prompt_version=row["prompt_version"],
            context_chunk_ids=tuple(row["context_chunk_ids"]),
            answer_text=row["answer_text"],
            fallback_mode=FallbackMode(row["fallback_mode"]),
            model_name=row["model_name"],
            token_counts=token_counts,
            latency_ms=int(row["latency_ms"]),
            created_at=row["created_at"],
        )

    def save_indexing_dead_letter(self, record: IndexingDeadLetter) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO indexing_dead_letters "
                "(dead_letter_id, source_message_id, community_id, chunk_ids, "
                " model_name, error_class, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    record.dead_letter_id,
                    record.source_message_id,
                    record.community_id,
                    list(record.chunk_ids),
                    record.model_name,
                    record.error_class,
                    record.created_at,
                ),
            )
            conn.commit()

    def list_indexing_dead_letters(
        self, community_id: str, *, limit: int | None = None
    ) -> list[IndexingDeadLetter]:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        sql = (
            "SELECT dead_letter_id, source_message_id, community_id, chunk_ids, "
            "       model_name, error_class, created_at "
            "  FROM indexing_dead_letters "
            " WHERE community_id = %s "
            " ORDER BY created_at DESC, dead_letter_id DESC"
        )
        params: tuple[object, ...] = (community_id,)
        if limit is not None:
            sql += " LIMIT %s"
            params = (community_id, limit)
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [_row_to_dead_letter(row) for row in rows]

    def get_indexing_dead_letter(self, dead_letter_id: str) -> IndexingDeadLetter | None:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT dead_letter_id, source_message_id, community_id, chunk_ids, "
                "       model_name, error_class, created_at "
                "  FROM indexing_dead_letters "
                " WHERE dead_letter_id = %s",
                (dead_letter_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return _row_to_dead_letter(row)


def _row_to_dead_letter(row: dict[str, Any]) -> IndexingDeadLetter:
    return IndexingDeadLetter(
        dead_letter_id=row["dead_letter_id"],
        source_message_id=row["source_message_id"],
        community_id=row["community_id"],
        chunk_ids=tuple(row["chunk_ids"]),
        model_name=row["model_name"],
        error_class=row["error_class"],
        created_at=row["created_at"],
    )


def _row_to_source(row: dict[str, Any]) -> SourceMessage:
    return SourceMessage(
        source_message_id=row["source_message_id"],
        community_id=row["community_id"],
        author_user_id=row["author_user_id"],
        external_chat_id=row["external_chat_id"],
        external_user_id=row["external_user_id"],
        external_message_id=row["external_message_id"],
        edit_seq=int(row["edit_seq"]),
        raw_text=row["raw_text"],
        detected_route=RouteKind(row["detected_route"]),
        created_at=row["created_at"],
    )


def _row_to_chunk(row: dict[str, Any]) -> EventChunk:
    return EventChunk(
        chunk_id=row["chunk_id"],
        note_id=row["note_id"],
        source_message_id=row["source_message_id"],
        community_id=row["community_id"],
        author_user_id=row["author_user_id"],
        note_date=row["note_date"],
        event_index=row["event_index"],
        chunk_text=row["chunk_text"],
        created_at=row["created_at"],
        embedding_status=EmbeddingStatus(row["embedding_status"]),
    )


__all__ = ["PostgresDomainStore"]
