"""Local-disk SQLite store implementing ``DomainRepository`` (ingest only).

Schema is bootstrapped at construction via ``CREATE TABLE IF NOT EXISTS``.
A fresh ``sqlite3.Connection`` is opened per public method call, so the
store is safe under FastAPI's threadpool without shared-connection care.
Dates and timestamps are serialized as ISO-8601 TEXT at the boundary;
no ``detect_types`` magic.

Idempotency (R-2 / D-023) is enforced by the
``UNIQUE (external_chat_id, external_message_id, edit_seq)`` constraint
plus ``INSERT OR IGNORE`` in ``get_or_create_source_message``: the DB is
the source of truth for dedupe, not a SELECT-then-INSERT race.

Phase 3.1+3.2 (D-024): SQLite is the opt-in dev backend and has no
pgvector. Embeddings are stored as little-endian ``f32`` ``BLOB``
payloads — correctness only; no ANN, no search optimisation.
``embedding_status`` lives on ``event_chunks`` so the column is visible
to plain SQL inspection.

Slice 3.3 (D-025): SQLite is an opt-in ingest-only backend. Postgres
is the canonical retrieval target; SQLite has no pgvector and no
FTS-with-ranking parity, so ``dense_candidates`` and
``sparse_candidates`` raise ``NotImplementedError``. ``Dispatcher``
converts that to ``FallbackMode.NO_EVIDENCE`` so an operator running
SQLite still gets a clean reply from ``/ask``.
"""

from __future__ import annotations

import array
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from memory_rag.core.chat.models import (
    ChatKnowledgeSearch,
    ChatQueryRewrite,
    ChatRoute,
    ChatRouteDecision,
)
from memory_rag.core.domain.models import (
    AnswerTrace,
    DateRange,
    EventChunk,
    FallbackMode,
    IndexingDeadLetter,
    LifecycleState,
    Note,
    Query,
    RetrievalHit,
    RetrievalLeg,
    SourceMessage,
)
from memory_rag.core.embeddings.models import EmbeddingRecord, EmbeddingStatus
from memory_rag.core.routing import RouteKind

_DDL = """
CREATE TABLE IF NOT EXISTS source_messages (
    source_message_id   TEXT PRIMARY KEY,
    community_id           TEXT NOT NULL,
    author_user_id      TEXT NOT NULL,
    external_chat_id    TEXT NOT NULL,
    external_user_id    TEXT NOT NULL,
    external_message_id TEXT NOT NULL,
    edit_seq            INTEGER NOT NULL DEFAULT 0,
    raw_text            TEXT NOT NULL,
    detected_route      TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    UNIQUE (external_chat_id, external_message_id, edit_seq)
);

CREATE TABLE IF NOT EXISTS notes (
    note_id    TEXT PRIMARY KEY,
    source_message_id TEXT NOT NULL REFERENCES source_messages(source_message_id),
    community_id         TEXT NOT NULL,
    author_user_id    TEXT NOT NULL,
    note_date        TEXT NOT NULL,
    note_text        TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    subject_id        TEXT,
    lifecycle_state  TEXT NOT NULL DEFAULT 'active'
        CHECK (lifecycle_state IN ('active','superseded','tombstoned')),
    supersedes_note_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_notes_source_message_id
    ON notes(source_message_id);

CREATE TABLE IF NOT EXISTS event_chunks (
    chunk_id          TEXT PRIMARY KEY,
    note_id    TEXT NOT NULL REFERENCES notes(note_id),
    source_message_id TEXT NOT NULL REFERENCES source_messages(source_message_id),
    community_id         TEXT NOT NULL,
    author_user_id    TEXT NOT NULL,
    note_date        TEXT NOT NULL,
    event_index       INTEGER NOT NULL CHECK (event_index >= 0),
    chunk_text        TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    embedding_status  TEXT NOT NULL DEFAULT 'pending'
        CHECK (embedding_status IN ('pending','ready','failed')),
    subject_id        TEXT,
    lifecycle_state  TEXT NOT NULL DEFAULT 'active'
        CHECK (lifecycle_state IN ('active','superseded','tombstoned')),
    supersedes_chunk_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_event_chunks_community_id
    ON event_chunks(community_id);

CREATE INDEX IF NOT EXISTS idx_event_chunks_source_message_id
    ON event_chunks(source_message_id);

CREATE TABLE IF NOT EXISTS embedding_records (
    embedding_record_id TEXT PRIMARY KEY,
    chunk_id            TEXT NOT NULL REFERENCES event_chunks(chunk_id),
    source_message_id   TEXT NOT NULL REFERENCES source_messages(source_message_id),
    community_id           TEXT NOT NULL,
    model_name          TEXT NOT NULL,
    dimension           INTEGER NOT NULL,
    embedding           BLOB NOT NULL,
    created_at          TEXT NOT NULL,
    UNIQUE (chunk_id, model_name)
);

CREATE INDEX IF NOT EXISTS idx_embedding_records_chunk_id
    ON embedding_records(chunk_id);

CREATE INDEX IF NOT EXISTS idx_embedding_records_source_message_id
    ON embedding_records(source_message_id);

CREATE TABLE IF NOT EXISTS queries (
    query_id     TEXT PRIMARY KEY,
    community_id    TEXT NOT NULL,
    query_text   TEXT NOT NULL,
    model_name   TEXT NOT NULL,
    fallback     TEXT NOT NULL
        CHECK (fallback IN (
            'none','no_evidence','invalid_input',
            'weak_evidence','ambiguous','provider_unavailable','parse_failure'
        )),
    created_at   TEXT NOT NULL,
    subject_scope TEXT
);

CREATE INDEX IF NOT EXISTS idx_queries_community_id ON queries(community_id);

CREATE TABLE IF NOT EXISTS retrieval_hits (
    retrieval_hit_id TEXT PRIMARY KEY,
    query_id         TEXT NOT NULL REFERENCES queries(query_id),
    chunk_id         TEXT NOT NULL REFERENCES event_chunks(chunk_id),
    leg              TEXT NOT NULL CHECK (leg IN ('dense','sparse','merged')),
    rank             INTEGER NOT NULL CHECK (rank >= 1),
    score            REAL NOT NULL,
    model_name       TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    UNIQUE (query_id, chunk_id, leg)
);

CREATE INDEX IF NOT EXISTS idx_retrieval_hits_query_id ON retrieval_hits(query_id);

CREATE TABLE IF NOT EXISTS answer_traces (
    answer_trace_id   TEXT PRIMARY KEY,
    query_id          TEXT NOT NULL UNIQUE REFERENCES queries(query_id),
    prompt_version    TEXT NOT NULL,
    context_chunk_ids TEXT NOT NULL,
    answer_text       TEXT NOT NULL,
    fallback_mode     TEXT NOT NULL
        CHECK (fallback_mode IN (
            'none','no_evidence','invalid_input',
            'weak_evidence','ambiguous','provider_unavailable','parse_failure'
        )),
    model_name        TEXT NOT NULL,
    token_counts      TEXT NOT NULL,
    latency_ms        INTEGER NOT NULL CHECK (latency_ms >= 0),
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_answer_traces_query_id ON answer_traces(query_id);

CREATE TABLE IF NOT EXISTS chat_route_decisions (
    decision_id           TEXT PRIMARY KEY,
    community_id          TEXT NOT NULL,
    question_text         TEXT NOT NULL,
    requested_route       TEXT
        CHECK (requested_route IS NULL OR requested_route IN (
            'notes_lookup','notes_plus_model','notes_plus_knowledge','model_only'
        )),
    effective_route       TEXT NOT NULL
        CHECK (effective_route IN (
            'notes_lookup','notes_plus_model','notes_plus_knowledge','model_only'
        )),
    classifier_model_name TEXT NOT NULL,
    classifier_raw_output TEXT NOT NULL,
    classifier_latency_ms INTEGER NOT NULL CHECK (classifier_latency_ms >= 0),
    query_id              TEXT REFERENCES queries(query_id),
    created_at            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_route_decisions_community_id
    ON chat_route_decisions(community_id);

CREATE TABLE IF NOT EXISTS chat_query_rewrites (
    rewrite_id          TEXT PRIMARY KEY,
    decision_id         TEXT NOT NULL REFERENCES chat_route_decisions(decision_id),
    community_id        TEXT NOT NULL,
    rewritten_query     TEXT,
    date_start          TEXT,
    date_end            TEXT,
    subject_scope       TEXT,
    rewriter_model_name TEXT NOT NULL,
    rewriter_raw_output TEXT NOT NULL,
    rewriter_latency_ms INTEGER NOT NULL CHECK (rewriter_latency_ms >= 0),
    created_at          TEXT NOT NULL,
    CHECK (date_start IS NULL OR date_end IS NULL OR date_start <= date_end)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_query_rewrites_decision_id
    ON chat_query_rewrites(decision_id);

CREATE INDEX IF NOT EXISTS idx_chat_query_rewrites_community_id
    ON chat_query_rewrites(community_id);

CREATE TABLE IF NOT EXISTS chat_knowledge_searches (
    search_id                   TEXT PRIMARY KEY,
    decision_id                 TEXT NOT NULL REFERENCES chat_route_decisions(decision_id),
    community_id                TEXT NOT NULL,
    outward_query               TEXT NOT NULL,
    outward_rewriter_model_name TEXT NOT NULL,
    outward_rewriter_raw_output TEXT NOT NULL,
    outward_rewriter_latency_ms INTEGER NOT NULL CHECK (outward_rewriter_latency_ms >= 0),
    provider_name               TEXT NOT NULL,
    result_count                INTEGER NOT NULL CHECK (result_count >= 0),
    raw_output                  TEXT NOT NULL,
    latency_ms                  INTEGER NOT NULL CHECK (latency_ms >= 0),
    created_at                  TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_knowledge_searches_decision_id
    ON chat_knowledge_searches(decision_id);

CREATE INDEX IF NOT EXISTS idx_chat_knowledge_searches_community_id
    ON chat_knowledge_searches(community_id);

CREATE TABLE IF NOT EXISTS indexing_dead_letters (
    dead_letter_id    TEXT PRIMARY KEY,
    source_message_id TEXT NOT NULL REFERENCES source_messages(source_message_id),
    community_id      TEXT NOT NULL,
    chunk_ids         TEXT NOT NULL,
    model_name        TEXT NOT NULL,
    error_class       TEXT NOT NULL,
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_indexing_dead_letters_community_id
    ON indexing_dead_letters(community_id);

CREATE INDEX IF NOT EXISTS idx_indexing_dead_letters_source_message_id
    ON indexing_dead_letters(source_message_id);

CREATE TABLE IF NOT EXISTS author_display_inputs (
    external_chat_id    TEXT NOT NULL,
    external_message_id TEXT NOT NULL,
    edit_seq            INTEGER NOT NULL DEFAULT 0,
    username            TEXT,
    first_name          TEXT,
    PRIMARY KEY (external_chat_id, external_message_id, edit_seq)
);
"""


def _encode_vector(vec: list[float]) -> bytes:
    return array.array("f", vec).tobytes()


def _decode_vector(blob: bytes, dimension: int) -> list[float]:
    arr = array.array("f")
    arr.frombytes(blob)
    if len(arr) != dimension:
        raise ValueError(f"embedding BLOB has {len(arr)} floats, expected {dimension}")
    return list(arr)


class SqliteDomainStore:
    """Local-disk SQLite implementation of ``DomainRepository``."""

    def __init__(self, path: str) -> None:
        self._path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executescript(_DDL)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def save_source_message(self, source: SourceMessage) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO source_messages "
                "(source_message_id, community_id, author_user_id, external_chat_id, "
                " external_user_id, external_message_id, edit_seq, raw_text, "
                " detected_route, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    source.created_at.isoformat(),
                ),
            )
            conn.commit()

    def get_or_create_source_message(self, source: SourceMessage) -> tuple[SourceMessage, bool]:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO source_messages "
                "(source_message_id, community_id, author_user_id, external_chat_id, "
                " external_user_id, external_message_id, edit_seq, raw_text, "
                " detected_route, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    source.created_at.isoformat(),
                ),
            )
            inserted = cur.rowcount == 1
            if inserted:
                conn.commit()
                return source, False
            row = conn.execute(
                "SELECT source_message_id, community_id, author_user_id, "
                "       external_chat_id, external_user_id, external_message_id, "
                "       edit_seq, raw_text, detected_route, created_at "
                "  FROM source_messages "
                " WHERE external_chat_id = ? "
                "   AND external_message_id = ? "
                "   AND edit_seq = ?",
                (source.external_chat_id, source.external_message_id, source.edit_seq),
            ).fetchone()
            conn.commit()
        assert row is not None
        return _row_to_source(row), True

    def save_note(self, note: Note) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO notes "
                "(note_id, source_message_id, community_id, author_user_id, "
                " note_date, note_text, created_at, subject_id, "
                " lifecycle_state, supersedes_note_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    note.note_id,
                    note.source_message_id,
                    note.community_id,
                    note.author_user_id,
                    note.note_date.isoformat(),
                    note.note_text,
                    note.created_at.isoformat(),
                    note.subject_id,
                    note.lifecycle_state.value,
                    note.supersedes_note_id,
                ),
            )
            conn.commit()

    def save_event_chunks(self, chunks: list[EventChunk]) -> None:
        if not chunks:
            return
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO event_chunks "
                "(chunk_id, note_id, source_message_id, community_id, "
                " author_user_id, note_date, event_index, chunk_text, created_at, "
                " embedding_status, subject_id, lifecycle_state, supersedes_chunk_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        c.chunk_id,
                        c.note_id,
                        c.source_message_id,
                        c.community_id,
                        c.author_user_id,
                        c.note_date.isoformat(),
                        c.event_index,
                        c.chunk_text,
                        c.created_at.isoformat(),
                        c.embedding_status.value,
                        c.subject_id,
                        c.lifecycle_state.value,
                        c.supersedes_chunk_id,
                    )
                    for c in chunks
                ],
            )
            conn.commit()

    def get_source_message(
        self, source_message_id: str, *, community_id: str
    ) -> SourceMessage | None:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT source_message_id, community_id, author_user_id, "
                "       external_chat_id, external_user_id, external_message_id, "
                "       edit_seq, raw_text, detected_route, created_at "
                "  FROM source_messages "
                " WHERE source_message_id = ? AND community_id = ?",
                (source_message_id, community_id),
            ).fetchone()
        if row is None:
            return None
        return _row_to_source(row)

    def list_source_messages(
        self, community_id: str, *, limit: int | None = None
    ) -> list[SourceMessage]:
        raise NotImplementedError(
            "sqlite raw export not supported; "
            "postgres is the canonical durable backend (D-022, D-029)"
        )

    def list_recent_drafts(self, community_id: str, *, limit: int) -> list[SourceMessage]:
        raise NotImplementedError(
            "sqlite drafts recall not supported; "
            "postgres is the canonical durable backend (D-022, D-030)"
        )

    def get_note_by_source_message_id(self, source_message_id: str) -> Note | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT note_id, source_message_id, community_id, author_user_id, "
                "       note_date, note_text, created_at, subject_id, "
                "       lifecycle_state, supersedes_note_id "
                "  FROM notes "
                " WHERE source_message_id = ? "
                " LIMIT 1",
                (source_message_id,),
            ).fetchone()
        if row is None:
            return None
        return Note(
            note_id=row["note_id"],
            source_message_id=row["source_message_id"],
            community_id=row["community_id"],
            author_user_id=row["author_user_id"],
            note_date=date.fromisoformat(row["note_date"]),
            note_text=row["note_text"],
            created_at=datetime.fromisoformat(row["created_at"]),
            subject_id=row["subject_id"],
            lifecycle_state=LifecycleState(row["lifecycle_state"]),
            supersedes_note_id=row["supersedes_note_id"],
        )

    def count_event_chunks_for_source(self, source_message_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT count(*) FROM event_chunks WHERE source_message_id = ?",
                (source_message_id,),
            ).fetchone()
        if row is None:
            return 0
        return int(row[0])

    def get_event_chunk(self, chunk_id: str, *, community_id: str) -> EventChunk | None:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT chunk_id, note_id, source_message_id, community_id, "
                "       author_user_id, note_date, event_index, chunk_text, "
                "       created_at, embedding_status, subject_id, "
                "       lifecycle_state, supersedes_chunk_id "
                "  FROM event_chunks "
                " WHERE chunk_id = ? AND community_id = ?",
                (chunk_id, community_id),
            ).fetchone()
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
        subject_scope: str | None = None,
    ) -> list[EventChunk]:
        raise NotImplementedError(
            "sqlite hybrid retrieval not supported; "
            "postgres is the canonical retrieval backend (D-022, D-025)"
        )

    def sparse_candidates(
        self,
        community_id: str,
        query_text: str,
        limit: int,
        *,
        date_range: DateRange | None = None,
        subject_scope: str | None = None,
    ) -> list[EventChunk]:
        raise NotImplementedError(
            "sqlite hybrid retrieval not supported; "
            "postgres is the canonical retrieval backend (D-022, D-025)"
        )

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
                _encode_vector(r.embedding),
                r.created_at.isoformat(),
            )
            for r in records
        ]
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO embedding_records "
                "(embedding_record_id, chunk_id, source_message_id, community_id, "
                " model_name, dimension, embedding, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                params,
            )
            conn.commit()

    def count_embedding_records_for_source(self, source_message_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT count(*) FROM embedding_records WHERE source_message_id = ?",
                (source_message_id,),
            ).fetchone()
        if row is None:
            return 0
        return int(row[0])

    def set_chunk_embedding_status(self, chunk_id: str, status: EmbeddingStatus) -> None:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE event_chunks SET embedding_status = ? WHERE chunk_id = ?",
                (status.value, chunk_id),
            )
            if cur.rowcount != 1:
                raise KeyError(f"unknown chunk_id={chunk_id}")
            conn.commit()

    def list_failed_event_chunks(
        self, community_id: str, *, limit: int | None = None
    ) -> list[EventChunk]:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        sql = (
            "SELECT chunk_id, note_id, source_message_id, community_id, "
            "       author_user_id, note_date, event_index, chunk_text, "
            "       created_at, embedding_status, subject_id, "
            "       lifecycle_state, supersedes_chunk_id "
            "  FROM event_chunks "
            " WHERE community_id = ? AND embedding_status = 'failed' "
            " ORDER BY created_at ASC, chunk_id ASC"
        )
        params: tuple[object, ...] = (community_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (community_id, limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_chunk(row) for row in rows]

    def save_query(self, query: Query) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO queries "
                "(query_id, community_id, query_text, model_name, fallback, "
                " created_at, subject_scope) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    query.query_id,
                    query.community_id,
                    query.query_text,
                    query.model_name,
                    query.fallback.value,
                    query.created_at.isoformat(),
                    query.subject_scope,
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
                h.created_at.isoformat(),
            )
            for h in hits
        ]
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO retrieval_hits "
                "(retrieval_hit_id, query_id, chunk_id, leg, rank, score, "
                " model_name, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                params,
            )
            conn.commit()

    def get_query(self, query_id: str, *, community_id: str) -> Query | None:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT query_id, community_id, query_text, model_name, fallback, "
                "       created_at, subject_scope "
                "  FROM queries "
                " WHERE query_id = ? AND community_id = ?",
                (query_id, community_id),
            ).fetchone()
        if row is None:
            return None
        return Query(
            query_id=row["query_id"],
            community_id=row["community_id"],
            query_text=row["query_text"],
            model_name=row["model_name"],
            fallback=FallbackMode(row["fallback"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            subject_scope=row["subject_scope"],
        )

    def get_retrieval_hits_for_query(
        self, query_id: str, *, community_id: str
    ) -> list[RetrievalHit]:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        # Scope via the parent queries.community_id (query_id -> queries join):
        # a retrieval_hits row carries no community_id of its own.
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT rh.retrieval_hit_id, rh.query_id, rh.chunk_id, rh.leg, "
                "       rh.rank, rh.score, rh.model_name, rh.created_at "
                "  FROM retrieval_hits rh "
                "  JOIN queries q ON q.query_id = rh.query_id "
                " WHERE rh.query_id = ? AND q.community_id = ? "
                " ORDER BY rh.leg ASC, rh.rank ASC",
                (query_id, community_id),
            ).fetchall()
        return [
            RetrievalHit(
                retrieval_hit_id=r["retrieval_hit_id"],
                query_id=r["query_id"],
                chunk_id=r["chunk_id"],
                leg=RetrievalLeg(r["leg"]),
                rank=int(r["rank"]),
                score=float(r["score"]),
                model_name=r["model_name"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    def save_answer_trace(self, trace: AnswerTrace) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO answer_traces "
                "(answer_trace_id, query_id, prompt_version, context_chunk_ids, "
                " answer_text, fallback_mode, model_name, token_counts, "
                " latency_ms, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    trace.answer_trace_id,
                    trace.query_id,
                    trace.prompt_version,
                    json.dumps(list(trace.context_chunk_ids)),
                    trace.answer_text,
                    trace.fallback_mode.value,
                    trace.model_name,
                    json.dumps(trace.token_counts, sort_keys=True),
                    trace.latency_ms,
                    trace.created_at.isoformat(),
                ),
            )
            conn.commit()

    def get_answer_trace_for_query(self, query_id: str, *, community_id: str) -> AnswerTrace | None:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        # Scope via the parent queries.community_id (query_id -> queries join):
        # answer_traces carries no community_id column (D-087 adds none).
        with self._connect() as conn:
            row = conn.execute(
                "SELECT at.answer_trace_id, at.query_id, at.prompt_version, "
                "       at.context_chunk_ids, at.answer_text, at.fallback_mode, "
                "       at.model_name, at.token_counts, at.latency_ms, at.created_at "
                "  FROM answer_traces at "
                "  JOIN queries q ON q.query_id = at.query_id "
                " WHERE at.query_id = ? AND q.community_id = ?",
                (query_id, community_id),
            ).fetchone()
        if row is None:
            return None
        return AnswerTrace(
            answer_trace_id=row["answer_trace_id"],
            query_id=row["query_id"],
            prompt_version=row["prompt_version"],
            context_chunk_ids=tuple(json.loads(row["context_chunk_ids"])),
            answer_text=row["answer_text"],
            fallback_mode=FallbackMode(row["fallback_mode"]),
            model_name=row["model_name"],
            token_counts=json.loads(row["token_counts"]),
            latency_ms=int(row["latency_ms"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def save_chat_route_decision(self, decision: ChatRouteDecision) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_route_decisions "
                "(decision_id, community_id, question_text, requested_route, "
                " effective_route, classifier_model_name, classifier_raw_output, "
                " classifier_latency_ms, query_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    decision.decision_id,
                    decision.community_id,
                    decision.question_text,
                    decision.requested_route.value if decision.requested_route else None,
                    decision.effective_route.value,
                    decision.classifier_model_name,
                    decision.classifier_raw_output,
                    decision.classifier_latency_ms,
                    decision.query_id,
                    decision.created_at.isoformat(),
                ),
            )
            conn.commit()

    def get_chat_route_decision(
        self, decision_id: str, *, community_id: str
    ) -> ChatRouteDecision | None:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT decision_id, community_id, question_text, requested_route, "
                "       effective_route, classifier_model_name, classifier_raw_output, "
                "       classifier_latency_ms, query_id, created_at "
                "  FROM chat_route_decisions "
                " WHERE decision_id = ? AND community_id = ?",
                (decision_id, community_id),
            ).fetchone()
        if row is None:
            return None
        return ChatRouteDecision(
            decision_id=row["decision_id"],
            community_id=row["community_id"],
            question_text=row["question_text"],
            requested_route=(ChatRoute(row["requested_route"]) if row["requested_route"] else None),
            effective_route=ChatRoute(row["effective_route"]),
            classifier_model_name=row["classifier_model_name"],
            classifier_raw_output=row["classifier_raw_output"],
            classifier_latency_ms=int(row["classifier_latency_ms"]),
            query_id=row["query_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def save_chat_query_rewrite(self, rewrite: ChatQueryRewrite) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_query_rewrites "
                "(rewrite_id, decision_id, community_id, rewritten_query, "
                " date_start, date_end, subject_scope, rewriter_model_name, "
                " rewriter_raw_output, rewriter_latency_ms, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rewrite.rewrite_id,
                    rewrite.decision_id,
                    rewrite.community_id,
                    rewrite.rewritten_query,
                    rewrite.date_start.isoformat() if rewrite.date_start else None,
                    rewrite.date_end.isoformat() if rewrite.date_end else None,
                    rewrite.subject_scope,
                    rewrite.rewriter_model_name,
                    rewrite.rewriter_raw_output,
                    rewrite.rewriter_latency_ms,
                    rewrite.created_at.isoformat(),
                ),
            )
            conn.commit()

    def get_chat_query_rewrite_for_decision(
        self, decision_id: str, *, community_id: str
    ) -> ChatQueryRewrite | None:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT rewrite_id, decision_id, community_id, rewritten_query, "
                "       date_start, date_end, subject_scope, rewriter_model_name, "
                "       rewriter_raw_output, rewriter_latency_ms, created_at "
                "  FROM chat_query_rewrites "
                " WHERE decision_id = ? AND community_id = ?",
                (decision_id, community_id),
            ).fetchone()
        if row is None:
            return None
        return ChatQueryRewrite(
            rewrite_id=row["rewrite_id"],
            decision_id=row["decision_id"],
            community_id=row["community_id"],
            rewritten_query=row["rewritten_query"],
            date_start=(date.fromisoformat(row["date_start"]) if row["date_start"] else None),
            date_end=(date.fromisoformat(row["date_end"]) if row["date_end"] else None),
            subject_scope=row["subject_scope"],
            rewriter_model_name=row["rewriter_model_name"],
            rewriter_raw_output=row["rewriter_raw_output"],
            rewriter_latency_ms=int(row["rewriter_latency_ms"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def save_chat_knowledge_search(self, search: ChatKnowledgeSearch) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_knowledge_searches "
                "(search_id, decision_id, community_id, outward_query, "
                " outward_rewriter_model_name, outward_rewriter_raw_output, "
                " outward_rewriter_latency_ms, provider_name, result_count, "
                " raw_output, latency_ms, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    search.search_id,
                    search.decision_id,
                    search.community_id,
                    search.outward_query,
                    search.outward_rewriter_model_name,
                    search.outward_rewriter_raw_output,
                    search.outward_rewriter_latency_ms,
                    search.provider_name,
                    search.result_count,
                    search.raw_output,
                    search.latency_ms,
                    search.created_at.isoformat(),
                ),
            )
            conn.commit()

    def get_chat_knowledge_search_for_decision(
        self, decision_id: str, *, community_id: str
    ) -> ChatKnowledgeSearch | None:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT search_id, decision_id, community_id, outward_query, "
                "       outward_rewriter_model_name, outward_rewriter_raw_output, "
                "       outward_rewriter_latency_ms, provider_name, result_count, "
                "       raw_output, latency_ms, created_at "
                "  FROM chat_knowledge_searches "
                " WHERE decision_id = ? AND community_id = ?",
                (decision_id, community_id),
            ).fetchone()
        if row is None:
            return None
        return ChatKnowledgeSearch(
            search_id=row["search_id"],
            decision_id=row["decision_id"],
            community_id=row["community_id"],
            outward_query=row["outward_query"],
            outward_rewriter_model_name=row["outward_rewriter_model_name"],
            outward_rewriter_raw_output=row["outward_rewriter_raw_output"],
            outward_rewriter_latency_ms=int(row["outward_rewriter_latency_ms"]),
            provider_name=row["provider_name"],
            result_count=int(row["result_count"]),
            raw_output=row["raw_output"],
            latency_ms=int(row["latency_ms"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def save_indexing_dead_letter(self, record: IndexingDeadLetter) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO indexing_dead_letters "
                "(dead_letter_id, source_message_id, community_id, chunk_ids, "
                " model_name, error_class, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record.dead_letter_id,
                    record.source_message_id,
                    record.community_id,
                    json.dumps(list(record.chunk_ids)),
                    record.model_name,
                    record.error_class,
                    record.created_at.isoformat(),
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
            " WHERE community_id = ? "
            " ORDER BY created_at DESC, dead_letter_id DESC"
        )
        params: tuple[object, ...] = (community_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (community_id, limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_dead_letter(row) for row in rows]

    def get_indexing_dead_letter(self, dead_letter_id: str) -> IndexingDeadLetter | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT dead_letter_id, source_message_id, community_id, chunk_ids, "
                "       model_name, error_class, created_at "
                "  FROM indexing_dead_letters "
                " WHERE dead_letter_id = ?",
                (dead_letter_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_dead_letter(row)

    def save_author_display_input(
        self,
        *,
        external_chat_id: str,
        external_message_id: str,
        edit_seq: int,
        username: str | None,
        first_name: str | None,
    ) -> None:
        # INSERT OR IGNORE makes re-delivery of the same tuple a no-op that
        # preserves the original snapshot (R-2 / D-084); an edit (new edit_seq)
        # is a distinct key and lands a new row.
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO author_display_inputs "
                "(external_chat_id, external_message_id, edit_seq, username, first_name) "
                "VALUES (?, ?, ?, ?, ?)",
                (external_chat_id, external_message_id, edit_seq, username, first_name),
            )
            conn.commit()

    def get_author_display_input(
        self,
        *,
        external_chat_id: str,
        external_message_id: str,
        edit_seq: int,
    ) -> tuple[str | None, str | None] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT username, first_name FROM author_display_inputs "
                " WHERE external_chat_id = ? AND external_message_id = ? AND edit_seq = ?",
                (external_chat_id, external_message_id, edit_seq),
            ).fetchone()
        if row is None:
            return None
        return (row["username"], row["first_name"])


def _row_to_dead_letter(row: sqlite3.Row) -> IndexingDeadLetter:
    return IndexingDeadLetter(
        dead_letter_id=row["dead_letter_id"],
        source_message_id=row["source_message_id"],
        community_id=row["community_id"],
        chunk_ids=tuple(json.loads(row["chunk_ids"])),
        model_name=row["model_name"],
        error_class=row["error_class"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_source(row: sqlite3.Row) -> SourceMessage:
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
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_chunk(row: sqlite3.Row) -> EventChunk:
    return EventChunk(
        chunk_id=row["chunk_id"],
        note_id=row["note_id"],
        source_message_id=row["source_message_id"],
        community_id=row["community_id"],
        author_user_id=row["author_user_id"],
        note_date=date.fromisoformat(row["note_date"]),
        event_index=row["event_index"],
        chunk_text=row["chunk_text"],
        created_at=datetime.fromisoformat(row["created_at"]),
        embedding_status=EmbeddingStatus(row["embedding_status"]),
        subject_id=row["subject_id"],
        lifecycle_state=LifecycleState(row["lifecycle_state"]),
        supersedes_chunk_id=row["supersedes_chunk_id"],
    )
