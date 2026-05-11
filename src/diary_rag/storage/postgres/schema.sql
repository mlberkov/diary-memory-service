-- Canonical Postgres schema for the durable diary backend.
-- Mirrors the SQLite seam (same tables, same lineage) using native Postgres
-- types: TIMESTAMPTZ for created_at, DATE for entry_date. The detected_route
-- CHECK lists every value in core.routing.RouteKind.
--
-- The UNIQUE constraint on (external_chat_id, external_message_id, edit_seq)
-- enforces the R-2 idempotency contract (D-023): repeated delivery of the
-- same channel message-state cannot create a second source row.
--
-- Phase 3.1+3.2 (D-024): pgvector is the dense-vector seam. ``vector(3072)``
-- matches the production embedding contour (``text-embedding-3-large``,
-- 3072 dim). No HNSW / IVFFlat index on the vector column — pgvector caps
-- those at 2000 dim; for Slice 3.3 the dense leg is an exact family-scoped
-- sequential scan against the canonical vector(3072) column. A halfvec /
-- HNSW migration belongs to a later quality-decision packet (A-36b).
--
-- Slice 3.3 (D-025): baseline hybrid retrieval. ``event_chunks`` carries a
-- generated stored ``chunk_text_tsv`` column built from
-- ``to_tsvector('simple', chunk_text)`` plus a GIN index so the sparse
-- (FTS) leg can run with ``websearch_to_tsquery('simple', query)``. The
-- ``simple`` dictionary avoids a language commitment because diary
-- content may mix English and Russian.
--
-- Bootstrapped by PostgresDiaryStore at __init__; safe to re-run on a fresh
-- database. Note: there is no migration tool yet (D-022/D-023/D-024/D-025),
-- so existing local volumes that pre-date these columns must be reset
-- (drop the named volume) before this DDL applies cleanly. See RUNBOOK.md.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS source_messages (
    source_message_id   TEXT PRIMARY KEY,
    family_id           TEXT NOT NULL,
    author_user_id      TEXT NOT NULL,
    external_chat_id    TEXT NOT NULL,
    external_user_id    TEXT NOT NULL,
    external_message_id TEXT NOT NULL,
    edit_seq            INTEGER NOT NULL DEFAULT 0,
    raw_text            TEXT NOT NULL,
    detected_route      TEXT NOT NULL
        CHECK (detected_route IN ('start','help','entry','ask','clarify','unknown')),
    created_at          TIMESTAMPTZ NOT NULL,
    UNIQUE (external_chat_id, external_message_id, edit_seq)
);

CREATE TABLE IF NOT EXISTS diary_entries (
    diary_entry_id    TEXT PRIMARY KEY,
    source_message_id TEXT NOT NULL REFERENCES source_messages(source_message_id),
    family_id         TEXT NOT NULL,
    author_user_id    TEXT NOT NULL,
    entry_date        DATE NOT NULL,
    entry_text        TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_diary_entries_source_message_id
    ON diary_entries(source_message_id);

CREATE TABLE IF NOT EXISTS event_chunks (
    chunk_id          TEXT PRIMARY KEY,
    diary_entry_id    TEXT NOT NULL REFERENCES diary_entries(diary_entry_id),
    source_message_id TEXT NOT NULL REFERENCES source_messages(source_message_id),
    family_id         TEXT NOT NULL,
    author_user_id    TEXT NOT NULL,
    entry_date        DATE NOT NULL,
    event_index       INTEGER NOT NULL CHECK (event_index >= 0),
    chunk_text        TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL,
    embedding_status  TEXT NOT NULL DEFAULT 'pending'
        CHECK (embedding_status IN ('pending','ready','failed')),
    chunk_text_tsv    tsvector GENERATED ALWAYS AS
        (to_tsvector('simple', chunk_text)) STORED
);

CREATE INDEX IF NOT EXISTS idx_event_chunks_family_id
    ON event_chunks(family_id);

CREATE INDEX IF NOT EXISTS idx_event_chunks_source_message_id
    ON event_chunks(source_message_id);

CREATE INDEX IF NOT EXISTS idx_event_chunks_chunk_text_tsv
    ON event_chunks USING GIN (chunk_text_tsv);

CREATE TABLE IF NOT EXISTS embedding_records (
    embedding_record_id TEXT PRIMARY KEY,
    chunk_id            TEXT NOT NULL REFERENCES event_chunks(chunk_id),
    source_message_id   TEXT NOT NULL REFERENCES source_messages(source_message_id),
    family_id           TEXT NOT NULL,
    model_name          TEXT NOT NULL,
    dimension           INTEGER NOT NULL,
    embedding           vector(3072) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL,
    UNIQUE (chunk_id, model_name)
);

CREATE INDEX IF NOT EXISTS idx_embedding_records_chunk_id
    ON embedding_records(chunk_id);

CREATE INDEX IF NOT EXISTS idx_embedding_records_source_message_id
    ON embedding_records(source_message_id);

CREATE INDEX IF NOT EXISTS idx_embedding_records_family_id
    ON embedding_records(family_id);
