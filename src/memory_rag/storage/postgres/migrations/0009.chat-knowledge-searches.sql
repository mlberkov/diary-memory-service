-- RC-4 (D-108) — chat_knowledge_searches table.
--
-- One row per notes_plus_knowledge execution recording the outward
-- query, the outward-rewrite provenance, and the knowledge-provider
-- result provenance (D-108 trace contract: web traces captured in the
-- trace plane; additive, non-destructive). The outward-rewrite
-- provenance is folded into this row rather than a second table — the
-- outward rewrite and the search are one pipeline step's trace with
-- the same zero-or-one-per-decision cardinality.
--
-- outward_query is always present: when no usable outward rewrite
-- existed the route degraded to searching with the stripped original
-- question, and that is what was searched.
-- outward_rewriter_model_name is '' only when no outward rewriter was
-- wired at all; outward_rewriter_raw_output is '' when no provider
-- output existed and the verbatim output otherwise. raw_output is the
-- knowledge provider's verbatim response body, '' when the search
-- failed with no output (the D-035 truthful-provenance rule applied to
-- the search seam). result_count is the number of excerpts the route
-- actually used (zero on the failed-search contour).
--
-- Non-destructive: a new table plus two indexes; no existing table or
-- row is touched.

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
    created_at                  TIMESTAMPTZ NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_knowledge_searches_decision_id
    ON chat_knowledge_searches(decision_id);

CREATE INDEX IF NOT EXISTS idx_chat_knowledge_searches_community_id
    ON chat_knowledge_searches(community_id);
