-- OP-1.2 / D-046 — first non-destructive schema-changing upgrade migration.
--
-- This is the first versioned migration that changes the schema beyond the
-- 0001 baseline. It is additive and non-destructive: it adds a single index on
-- ``event_chunks(embedding_status)`` and reads, rewrites, or drops no data.
-- Applying it over a populated database created from 0001 (or from a
-- stamp-adopted pre-OP-1.1 volume) leaves every existing row untouched.
--
-- The index backs the A-35 / RUNBOOK operator probe
-- (``SELECT ... FROM event_chunks WHERE embedding_status = 'failed'``), which
-- otherwise performs a sequential scan. ``CREATE INDEX IF NOT EXISTS`` (plain,
-- not CONCURRENTLY) runs inside yoyo's per-migration transaction; the index
-- name follows the ``idx_event_chunks_*`` convention from the baseline.

CREATE INDEX IF NOT EXISTS idx_event_chunks_embedding_status
    ON event_chunks(embedding_status);
