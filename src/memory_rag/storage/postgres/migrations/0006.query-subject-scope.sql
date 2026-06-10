-- H-3 (D-107) — subject_scope column on queries.
--
-- The optional subject retrieval filter (H-3) records, per /ask call, the
-- subject_scope the call was made with: the opaque, community-subordinate
-- subject_id value both retrieval legs were restricted to, or NULL when no
-- subject constraint was requested (the default, the only shape that exists
-- today — there is no inbound subject syntax yet). Persisting it keeps the
-- requested retrieval scope inspectable via plain SQL next to the rest of
-- the query trace (R-5 provenance discipline), mirroring how the row already
-- records query_text / model_name / fallback.
--
-- Non-destructive: a nullable column with no default. Existing rows keep
-- subject_scope NULL (no subject constraint); no data is rewritten and no
-- index is added.

ALTER TABLE queries ADD COLUMN IF NOT EXISTS subject_scope TEXT;
