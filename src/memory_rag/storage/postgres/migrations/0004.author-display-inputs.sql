-- D-084 — author display-input side table (Telegram-adapter-owned).
--
-- Durable landing for the point-in-time author display-input snapshot pinned by
-- D-081 / D-082 / D-083. The table is an adapter artifact, not a core capability:
-- it is keyed only by the same message idempotency tuple the raw message uses —
-- (external_chat_id, external_message_id, edit_seq); R-2 / D-023 — carried as
-- opaque scalars, with NO foreign key and no dependency on any core table or
-- type (D-026 / D-041). The core continues to carry authorship solely as the
-- opaque author_user_id (I-1, I-6).
--
--  * username / first_name are nullable and non-authoritative (a user may
--    withhold either); a both-null snapshot is still recorded.
--  * The composite PRIMARY KEY enforces idempotency: with
--    INSERT ... ON CONFLICT DO NOTHING in the store, re-delivery of the same
--    tuple never duplicates or silently mutates a prior snapshot, and an edited
--    state (new edit_seq) lands a new row.

CREATE TABLE IF NOT EXISTS author_display_inputs (
    external_chat_id    TEXT NOT NULL,
    external_message_id TEXT NOT NULL,
    edit_seq            INTEGER NOT NULL DEFAULT 0,
    username            TEXT,
    first_name          TEXT,
    PRIMARY KEY (external_chat_id, external_message_id, edit_seq)
);
