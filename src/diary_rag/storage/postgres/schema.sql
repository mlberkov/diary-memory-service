-- Canonical Postgres schema for the durable diary backend.
-- Mirrors the SQLite seam (same tables, same lineage) using native Postgres
-- types: TIMESTAMPTZ for created_at, DATE for note_date. The detected_route
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
-- Draft floor (D-027): ``detected_route`` includes ``'draft'`` so a
-- ``SourceMessage`` persisted under the no-silent-loss floor (raw-only,
-- no parse/chunk/embed) is durable and inspectable by plain SQL. The
-- column doubles as the lifecycle marker per A-38; adding a dedicated
-- lifecycle column is a separate packet.
--
-- Slice 3.5: retrieval-trace persistence adds the ``queries`` and
-- ``retrieval_hits`` tables; ``QueryService.answer`` writes one query row
-- per ``/ask`` plus per-leg + merged hit rows so an operator can inspect
-- what each leg saw and what survived RRF via plain SQL.
--
-- Slice 4.3a (D-034): answer-side trace persistence adds the
-- ``answer_traces`` table; ``QueryService.answer`` writes one trace row
-- per /ask reply on the success and no-evidence/empty-query contours.
-- Weak-evidence / ambiguous / provider-unavailable grading is deferred
-- to Slice 4.3.
--
-- Bootstrapped by PostgresDomainStore at __init__; safe to re-run on a fresh
-- database. Note: there is no migration tool yet
-- (D-022/D-023/D-024/D-025/Slice-3.5/D-034), so existing local volumes
-- that pre-date these tables must be reset (drop the named volume)
-- before this DDL applies cleanly. See RUNBOOK.md.

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

-- Slice 3.5: retrieval-trace persistence.
-- One queries row per /ask call; zero-or-more retrieval_hits rows per
-- call carrying leg in {dense, sparse, merged}, 1-based rank, and the
-- RRF-contribution score (1/(K+rank) on per-leg rows; fused score on
-- merged rows). Slice 4.3a (D-034) added answer_traces below.
-- Slice 4.3b (D-035) widened queries.fallback to carry the answer-side
-- modes graded in QueryService.answer (weak_evidence / ambiguous /
-- provider_unavailable / parse_failure) so Query.fallback and the
-- paired AnswerTrace.fallback_mode are aligned by construction.

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

-- Slice 4.3a (D-034): answer-side trace persistence. One row per /ask
-- reply. UNIQUE on query_id pins the one-trace-per-query shape.
-- fallback_mode mirrors FallbackMode and uses the same CHECK set as
-- queries.fallback. token_counts is provider-attributed and free-form
-- (JSONB so future backends can store richer shapes without a schema
-- change). Slice 4.3b (D-035) widened the CHECK set to include the
-- four new answer-side modes.

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
