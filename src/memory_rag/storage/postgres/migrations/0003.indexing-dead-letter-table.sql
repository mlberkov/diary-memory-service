-- OP-2.2 / Slice 6.2 / D-048 — persistent dead-letter surface for failed
-- indexing jobs.
--
-- Additive and non-destructive: it creates one new table plus two indexes and
-- reads, rewrites, or drops no existing data. Applying it over a populated
-- database created from 0001/0002 (or from a stamp-adopted pre-OP-1.1 volume)
-- leaves every existing row untouched.
--
-- ``indexing_dead_letters`` records one row per failed embedding call during
-- ingest: when the embedding provider raises, ``DomainService`` flips the
-- affected chunks to ``embedding_status='failed'`` (A-35) and additionally
-- attempts to persist a dead-letter row here. ``chunk_ids`` is a ``TEXT[]`` of
-- every chunk the failed call covered (no foreign key — an array element
-- cannot be constrained, mirroring ``answer_traces.context_chunk_ids``).
-- ``error_class`` is the exception class name only — the same provenance the
-- ``embedding.failed`` log line carries. The table is append-only: it has no
-- status column; OP-3 reconciliation consumes this surface without mutating it.
--
-- ``CREATE TABLE / INDEX IF NOT EXISTS`` (plain, not CONCURRENTLY) runs inside
-- yoyo's per-migration transaction; index names follow the baseline
-- ``idx_<table>_<column>`` convention.

CREATE TABLE IF NOT EXISTS indexing_dead_letters (
    dead_letter_id    TEXT PRIMARY KEY,
    source_message_id TEXT NOT NULL REFERENCES source_messages(source_message_id),
    community_id      TEXT NOT NULL,
    chunk_ids         TEXT[] NOT NULL,
    model_name        TEXT NOT NULL,
    error_class       TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_indexing_dead_letters_community_id
    ON indexing_dead_letters(community_id);

CREATE INDEX IF NOT EXISTS idx_indexing_dead_letters_source_message_id
    ON indexing_dead_letters(source_message_id);
