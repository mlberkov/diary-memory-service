"""Local-disk SQLite store implementing ``DiaryRepository`` (ingest only).

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

from diary_rag.core.diary.models import (
    AnswerTrace,
    DateRange,
    DiaryEntry,
    EventChunk,
    FallbackMode,
    Query,
    RetrievalHit,
    RetrievalLeg,
    SourceMessage,
)
from diary_rag.core.embeddings.models import EmbeddingRecord, EmbeddingStatus
from diary_rag.core.routing import RouteKind

_DDL = """
CREATE TABLE IF NOT EXISTS source_messages (
    source_message_id   TEXT PRIMARY KEY,
    family_id           TEXT NOT NULL,
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

CREATE TABLE IF NOT EXISTS diary_entries (
    diary_entry_id    TEXT PRIMARY KEY,
    source_message_id TEXT NOT NULL REFERENCES source_messages(source_message_id),
    family_id         TEXT NOT NULL,
    author_user_id    TEXT NOT NULL,
    entry_date        TEXT NOT NULL,
    entry_text        TEXT NOT NULL,
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_diary_entries_source_message_id
    ON diary_entries(source_message_id);

CREATE TABLE IF NOT EXISTS event_chunks (
    chunk_id          TEXT PRIMARY KEY,
    diary_entry_id    TEXT NOT NULL REFERENCES diary_entries(diary_entry_id),
    source_message_id TEXT NOT NULL REFERENCES source_messages(source_message_id),
    family_id         TEXT NOT NULL,
    author_user_id    TEXT NOT NULL,
    entry_date        TEXT NOT NULL,
    event_index       INTEGER NOT NULL CHECK (event_index >= 0),
    chunk_text        TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    embedding_status  TEXT NOT NULL DEFAULT 'pending'
        CHECK (embedding_status IN ('pending','ready','failed'))
);

CREATE INDEX IF NOT EXISTS idx_event_chunks_family_id
    ON event_chunks(family_id);

CREATE INDEX IF NOT EXISTS idx_event_chunks_source_message_id
    ON event_chunks(source_message_id);

CREATE TABLE IF NOT EXISTS embedding_records (
    embedding_record_id TEXT PRIMARY KEY,
    chunk_id            TEXT NOT NULL REFERENCES event_chunks(chunk_id),
    source_message_id   TEXT NOT NULL REFERENCES source_messages(source_message_id),
    family_id           TEXT NOT NULL,
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
    family_id    TEXT NOT NULL,
    query_text   TEXT NOT NULL,
    model_name   TEXT NOT NULL,
    fallback     TEXT NOT NULL
        CHECK (fallback IN (
            'none','no_evidence','invalid_input',
            'weak_evidence','ambiguous','provider_unavailable','parse_failure'
        )),
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_queries_family_id ON queries(family_id);

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
"""


def _encode_vector(vec: list[float]) -> bytes:
    return array.array("f", vec).tobytes()


def _decode_vector(blob: bytes, dimension: int) -> list[float]:
    arr = array.array("f")
    arr.frombytes(blob)
    if len(arr) != dimension:
        raise ValueError(f"embedding BLOB has {len(arr)} floats, expected {dimension}")
    return list(arr)


class SqliteDiaryStore:
    """Local-disk SQLite implementation of ``DiaryRepository``."""

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
                "(source_message_id, family_id, author_user_id, external_chat_id, "
                " external_user_id, external_message_id, edit_seq, raw_text, "
                " detected_route, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    source.source_message_id,
                    source.family_id,
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
                "(source_message_id, family_id, author_user_id, external_chat_id, "
                " external_user_id, external_message_id, edit_seq, raw_text, "
                " detected_route, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    source.source_message_id,
                    source.family_id,
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
                "SELECT source_message_id, family_id, author_user_id, "
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

    def save_diary_entry(self, entry: DiaryEntry) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO diary_entries "
                "(diary_entry_id, source_message_id, family_id, author_user_id, "
                " entry_date, entry_text, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.diary_entry_id,
                    entry.source_message_id,
                    entry.family_id,
                    entry.author_user_id,
                    entry.entry_date.isoformat(),
                    entry.entry_text,
                    entry.created_at.isoformat(),
                ),
            )
            conn.commit()

    def save_event_chunks(self, chunks: list[EventChunk]) -> None:
        if not chunks:
            return
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO event_chunks "
                "(chunk_id, diary_entry_id, source_message_id, family_id, "
                " author_user_id, entry_date, event_index, chunk_text, created_at, "
                " embedding_status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        c.chunk_id,
                        c.diary_entry_id,
                        c.source_message_id,
                        c.family_id,
                        c.author_user_id,
                        c.entry_date.isoformat(),
                        c.event_index,
                        c.chunk_text,
                        c.created_at.isoformat(),
                        c.embedding_status.value,
                    )
                    for c in chunks
                ],
            )
            conn.commit()

    def get_source_message(self, source_message_id: str) -> SourceMessage | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT source_message_id, family_id, author_user_id, "
                "       external_chat_id, external_user_id, external_message_id, "
                "       edit_seq, raw_text, detected_route, created_at "
                "  FROM source_messages "
                " WHERE source_message_id = ?",
                (source_message_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_source(row)

    def list_source_messages(
        self, family_id: str, *, limit: int | None = None
    ) -> list[SourceMessage]:
        raise NotImplementedError(
            "sqlite raw export not supported; "
            "postgres is the canonical durable backend (D-022, D-029)"
        )

    def list_recent_drafts(self, family_id: str, *, limit: int) -> list[SourceMessage]:
        raise NotImplementedError(
            "sqlite drafts recall not supported; "
            "postgres is the canonical durable backend (D-022, D-030)"
        )

    def get_diary_entry_by_source_message_id(self, source_message_id: str) -> DiaryEntry | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT diary_entry_id, source_message_id, family_id, author_user_id, "
                "       entry_date, entry_text, created_at "
                "  FROM diary_entries "
                " WHERE source_message_id = ? "
                " LIMIT 1",
                (source_message_id,),
            ).fetchone()
        if row is None:
            return None
        return DiaryEntry(
            diary_entry_id=row["diary_entry_id"],
            source_message_id=row["source_message_id"],
            family_id=row["family_id"],
            author_user_id=row["author_user_id"],
            entry_date=date.fromisoformat(row["entry_date"]),
            entry_text=row["entry_text"],
            created_at=datetime.fromisoformat(row["created_at"]),
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

    def get_event_chunk(self, chunk_id: str) -> EventChunk | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT chunk_id, diary_entry_id, source_message_id, family_id, "
                "       author_user_id, entry_date, event_index, chunk_text, "
                "       created_at, embedding_status "
                "  FROM event_chunks "
                " WHERE chunk_id = ?",
                (chunk_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_chunk(row)

    def dense_candidates(
        self,
        family_id: str,
        query_embedding: list[float],
        model_name: str,
        limit: int,
        *,
        date_range: DateRange | None = None,
    ) -> list[EventChunk]:
        raise NotImplementedError(
            "sqlite hybrid retrieval not supported; "
            "postgres is the canonical retrieval backend (D-022, D-025)"
        )

    def sparse_candidates(
        self,
        family_id: str,
        query_text: str,
        limit: int,
        *,
        date_range: DateRange | None = None,
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
                r.family_id,
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
                "(embedding_record_id, chunk_id, source_message_id, family_id, "
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

    def save_query(self, query: Query) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO queries "
                "(query_id, family_id, query_text, model_name, fallback, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    query.query_id,
                    query.family_id,
                    query.query_text,
                    query.model_name,
                    query.fallback.value,
                    query.created_at.isoformat(),
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

    def get_query(self, query_id: str) -> Query | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT query_id, family_id, query_text, model_name, fallback, "
                "       created_at "
                "  FROM queries "
                " WHERE query_id = ?",
                (query_id,),
            ).fetchone()
        if row is None:
            return None
        return Query(
            query_id=row["query_id"],
            family_id=row["family_id"],
            query_text=row["query_text"],
            model_name=row["model_name"],
            fallback=FallbackMode(row["fallback"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def get_retrieval_hits_for_query(self, query_id: str) -> list[RetrievalHit]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT retrieval_hit_id, query_id, chunk_id, leg, rank, score, "
                "       model_name, created_at "
                "  FROM retrieval_hits "
                " WHERE query_id = ? "
                " ORDER BY leg ASC, rank ASC",
                (query_id,),
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

    def get_answer_trace_for_query(self, query_id: str) -> AnswerTrace | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT answer_trace_id, query_id, prompt_version, context_chunk_ids, "
                "       answer_text, fallback_mode, model_name, token_counts, "
                "       latency_ms, created_at "
                "  FROM answer_traces "
                " WHERE query_id = ?",
                (query_id,),
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


def _row_to_source(row: sqlite3.Row) -> SourceMessage:
    return SourceMessage(
        source_message_id=row["source_message_id"],
        family_id=row["family_id"],
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
        diary_entry_id=row["diary_entry_id"],
        source_message_id=row["source_message_id"],
        family_id=row["family_id"],
        author_user_id=row["author_user_id"],
        entry_date=date.fromisoformat(row["entry_date"]),
        event_index=row["event_index"],
        chunk_text=row["chunk_text"],
        created_at=datetime.fromisoformat(row["created_at"]),
        embedding_status=EmbeddingStatus(row["embedding_status"]),
    )
