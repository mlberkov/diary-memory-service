-- RC-2 (D-108) — chat_route_decisions table.
--
-- One row per /chat call recording the routing decision the routed-chat
-- service made: the classifier's requested route (NULL when no usable
-- classification existed — provider unavailable, unusable output, or an
-- empty question), the effective route that actually answered (R-6
-- requested-vs-effective discipline), the classifier's provenance
-- (model name, verbatim raw output, bounded-loop latency), and a link
-- to the queries row the dispatched route persisted (NULL only when the
-- delegated retrieval seam was unavailable before a Query row existed).
-- There is deliberately no confidence column (D-108 no-thresholds rule).
--
-- Non-destructive: a new table plus one index; no existing table or row
-- is touched.

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
    created_at            TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_route_decisions_community_id
    ON chat_route_decisions(community_id);
