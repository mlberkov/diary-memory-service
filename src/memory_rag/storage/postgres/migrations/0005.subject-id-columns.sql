-- H-1 (D-097) — subject_id columns on notes / event_chunks.
--
-- First code realization of the subject-scoping contract ratified by D-097:
-- an opaque, community-scoped, NULLABLE subject_id carried on the two
-- subject-bearing core records (Note, EventChunk). It is subordinate to
-- community_id and never widens or crosses community scope; NULL = community-wide
-- (the access model that exists today), so this upgrade is additive and does not
-- retro-scope existing rows. The field is born directly as subject_id (canonical
-- D-041 vocabulary); child / child_id stay use-case labels, never a core column.
--
-- Non-destructive: a nullable column with no default. Existing rows keep
-- subject_id NULL; no data is rewritten. Assignment (H-2) and the optional
-- retrieval filter (H-3) are separate later packets, so no index is added here.

ALTER TABLE notes ADD COLUMN IF NOT EXISTS subject_id TEXT;
ALTER TABLE event_chunks ADD COLUMN IF NOT EXISTS subject_id TEXT;
