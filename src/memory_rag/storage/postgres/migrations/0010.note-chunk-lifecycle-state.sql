-- ED-1 (D-114) — lifecycle_state + supersession lineage on notes / event_chunks.
--
-- First code realization of the edit/delete contract ratified by D-114: the
-- revision lifecycle state model `active | superseded | tombstoned` is carried
-- as a single low-cardinality state column on the two revision-bearing core
-- records (Note, EventChunk), mirroring the embedding_status column shape
-- (TEXT + CHECK + DEFAULT). The active-state filter on retrieval (R-4)
-- generalizes to return only `active` rows (this packet wires the predicate;
-- see storage/postgres/store.py). A nullable supersedes_* lineage column is
-- added now so the /edit supersession writer (ED-2) needs no further migration;
-- it is left NULL until then. The /delete tombstone writer is ED-3.
--
-- Non-destructive: lifecycle_state lands NOT NULL DEFAULT 'active', so existing
-- rows are backfilled to 'active' by the constant default (no table rewrite on
-- PostgreSQL 11+); supersedes_* is a nullable column with no default. No data is
-- otherwise rewritten. lifecycle_state is low-cardinality and composes with the
-- existing community_id / tsv / vector scans, so no index is added here.

ALTER TABLE notes ADD COLUMN IF NOT EXISTS lifecycle_state TEXT NOT NULL DEFAULT 'active'
    CHECK (lifecycle_state IN ('active','superseded','tombstoned'));
ALTER TABLE notes ADD COLUMN IF NOT EXISTS supersedes_note_id TEXT;

ALTER TABLE event_chunks ADD COLUMN IF NOT EXISTS lifecycle_state TEXT NOT NULL DEFAULT 'active'
    CHECK (lifecycle_state IN ('active','superseded','tombstoned'));
ALTER TABLE event_chunks ADD COLUMN IF NOT EXISTS supersedes_chunk_id TEXT;
