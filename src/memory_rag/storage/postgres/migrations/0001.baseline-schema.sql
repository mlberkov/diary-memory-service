-- OP-1.1 / D-045 — baseline migration.
--
-- This is the first versioned migration. It captures, verbatim, the Postgres
-- schema that was previously bootstrapped by executing the now-retired
-- ``schema.sql`` directly. It introduces NO schema changes: a database created
-- by the old raw-schema bootstrap and a database created by applying this
-- migration are identical.
--
-- The ``CREATE ... IF NOT EXISTS`` clauses are kept verbatim from the retired
-- ``schema.sql`` so this migration faithfully reproduces the prior bootstrap
-- behaviour. They are NOT an adoption mechanism: a pre-existing local volume
-- created from the old raw-schema bootstrap is brought into the versioned
-- world by the documented one-time ``stamp`` step (see RUNBOOK.md), which is
-- the only supported adoption path.
--
-- Schema notes carried over from the retired schema.sql:
--  * Mirrors the SQLite seam (same tables, same lineage) using native Postgres
--    types: TIMESTAMPTZ for created_at, DATE for note_date. The detected_route
--    CHECK lists every value in core.routing.RouteKind.
--  * UNIQUE (external_chat_id, external_message_id, edit_seq) enforces the R-2
--    idempotency contract (D-023).
--  * pgvector ``vector(3072)`` matches the production embedding contour
--    (``text-embedding-3-large``, 3072 dim). No HNSW / IVFFlat index — pgvector
--    caps those at 2000 dim; the dense leg is an exact community-scoped scan
--    (D-024, D-025; A-36b defers a halfvec / HNSW migration).
--  * ``event_chunks.chunk_text_tsv`` is a generated stored column over
--    ``to_tsvector('simple', chunk_text)`` with a GIN index for the sparse
--    (FTS) leg (D-025).
--  * ``queries`` + ``retrieval_hits`` carry retrieval-trace persistence
--    (Slice 3.5); ``answer_traces`` carries answer-side trace persistence
--    (Slice 4.3a, D-034); the fallback CHECK sets were widened by D-035.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS source_messages (
    source_message_id   TEXT PRIMARY KEY,
    community_id           TEXT NOT NULL,
    author_user_id      TEXT NOT NULL,
    external_chat_id    TEXT NOT NULL,
    external_user_id    TEXT NOT NULL,
    external_message_id TEXT NOT NULL,
    edit_seq            INTEGER NOT NULL DEFAULT 0,
    raw_text            TEXT NOT NULL,
    detected_route      TEXT NOT NULL
        CHECK (detected_route IN ('start','help','note','ask','draft','clarify','unknown')),
    created_at          TIMESTAMPTZ NOT NULL,
    UNIQUE (external_chat_id, external_message_id, edit_seq)
);

CREATE TABLE IF NOT EXISTS notes (
    note_id    TEXT PRIMARY KEY,
    source_message_id TEXT NOT NULL REFERENCES source_messages(source_message_id),
    community_id         TEXT NOT NULL,
    author_user_id    TEXT NOT NULL,
    note_date        DATE NOT NULL,
    note_text        TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notes_source_message_id
    ON notes(source_message_id);

CREATE TABLE IF NOT EXISTS event_chunks (
    chunk_id          TEXT PRIMARY KEY,
    note_id    TEXT NOT NULL REFERENCES notes(note_id),
    source_message_id TEXT NOT NULL REFERENCES source_messages(source_message_id),
    community_id         TEXT NOT NULL,
    author_user_id    TEXT NOT NULL,
    note_date        DATE NOT NULL,
    event_index       INTEGER NOT NULL CHECK (event_index >= 0),
    chunk_text        TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL,
    embedding_status  TEXT NOT NULL DEFAULT 'pending'
        CHECK (embedding_status IN ('pending','ready','failed')),
    chunk_text_tsv    tsvector GENERATED ALWAYS AS
        (to_tsvector('simple', chunk_text)) STORED
);

CREATE INDEX IF NOT EXISTS idx_event_chunks_community_id
    ON event_chunks(community_id);

CREATE INDEX IF NOT EXISTS idx_event_chunks_source_message_id
    ON event_chunks(source_message_id);

CREATE INDEX IF NOT EXISTS idx_event_chunks_chunk_text_tsv
    ON event_chunks USING GIN (chunk_text_tsv);

CREATE TABLE IF NOT EXISTS embedding_records (
    embedding_record_id TEXT PRIMARY KEY,
    chunk_id            TEXT NOT NULL REFERENCES event_chunks(chunk_id),
    source_message_id   TEXT NOT NULL REFERENCES source_messages(source_message_id),
    community_id           TEXT NOT NULL,
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

CREATE INDEX IF NOT EXISTS idx_embedding_records_community_id
    ON embedding_records(community_id);

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
    created_at   TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_queries_community_id ON queries(community_id);

CREATE TABLE IF NOT EXISTS retrieval_hits (
    retrieval_hit_id TEXT PRIMARY KEY,
    query_id         TEXT NOT NULL REFERENCES queries(query_id),
    chunk_id         TEXT NOT NULL REFERENCES event_chunks(chunk_id),
    leg              TEXT NOT NULL CHECK (leg IN ('dense','sparse','merged')),
    rank             INTEGER NOT NULL CHECK (rank >= 1),
    score            DOUBLE PRECISION NOT NULL,
    model_name       TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL,
    UNIQUE (query_id, chunk_id, leg)
);

CREATE INDEX IF NOT EXISTS idx_retrieval_hits_query_id ON retrieval_hits(query_id);

CREATE TABLE IF NOT EXISTS answer_traces (
    answer_trace_id   TEXT PRIMARY KEY,
    query_id          TEXT NOT NULL UNIQUE REFERENCES queries(query_id),
    prompt_version    TEXT NOT NULL,
    context_chunk_ids TEXT[] NOT NULL,
    answer_text       TEXT NOT NULL,
    fallback_mode     TEXT NOT NULL
        CHECK (fallback_mode IN (
            'none','no_evidence','invalid_input',
            'weak_evidence','ambiguous','provider_unavailable','parse_failure'
        )),
    model_name        TEXT NOT NULL,
    token_counts      JSONB NOT NULL,
    latency_ms        INTEGER NOT NULL CHECK (latency_ms >= 0),
    created_at        TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_answer_traces_query_id ON answer_traces(query_id);
