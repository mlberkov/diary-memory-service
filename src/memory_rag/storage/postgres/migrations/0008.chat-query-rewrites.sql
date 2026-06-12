-- RC-3 (D-108) — chat_query_rewrites table.
--
-- One row per notes_plus_model execution recording the retrieval-side
-- query rewrite (D-108 trace contract: rewritten queries captured in
-- the trace plane; additive, non-destructive). rewritten_query NULL =
-- no usable rewrite existed (rewriter unavailable or unusable output —
-- the route degraded to the original question with no date constraint).
-- rewriter_raw_output is '' when no provider output existed and the
-- verbatim output otherwise (the D-035 truthful-provenance rule applied
-- to the rewriter seam). subject_scope is the rewriter-emitted value —
-- seam-ready and always NULL in this packet (see docs/assumptions.md);
-- the caller-provided scope the retrieval ran with is recorded on the
-- queries row instead.
--
-- Non-destructive: a new table plus two indexes; no existing table or
-- row is touched.

CREATE TABLE IF NOT EXISTS chat_query_rewrites (
    rewrite_id          TEXT PRIMARY KEY,
    decision_id         TEXT NOT NULL REFERENCES chat_route_decisions(decision_id),
    community_id        TEXT NOT NULL,
    rewritten_query     TEXT,
    date_start          DATE,
    date_end            DATE,
    subject_scope       TEXT,
    rewriter_model_name TEXT NOT NULL,
    rewriter_raw_output TEXT NOT NULL,
    rewriter_latency_ms INTEGER NOT NULL CHECK (rewriter_latency_ms >= 0),
    created_at          TIMESTAMPTZ NOT NULL,
    CHECK (date_start IS NULL OR date_end IS NULL OR date_start <= date_end)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_query_rewrites_decision_id
    ON chat_query_rewrites(decision_id);

CREATE INDEX IF NOT EXISTS idx_chat_query_rewrites_community_id
    ON chat_query_rewrites(community_id);
