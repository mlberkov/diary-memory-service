-- Canonical Postgres schema for the durable diary backend.
-- Mirrors the SQLite seam (same tables, same lineage) using native Postgres
-- types: TIMESTAMPTZ for created_at, DATE for entry_date. The detected_route
-- CHECK lists every value in core.routing.RouteKind.
--
-- The UNIQUE constraint on (external_chat_id, external_message_id, edit_seq)
-- enforces the R-2 idempotency contract (D-023): repeated delivery of the
-- same channel message-state cannot create a second source row.
--
-- Bootstrapped by PostgresDiaryStore at __init__; safe to re-run on a fresh
-- database. Note: there is no migration tool yet (D-022/D-023), so existing
-- local volumes that pre-date these columns must be reset (drop the named
-- volume) before this DDL applies cleanly. See RUNBOOK.md.

CREATE TABLE IF NOT EXISTS source_messages (
    source_message_id   TEXT PRIMARY KEY,
    family_id           TEXT NOT NULL,
    author_user_id      TEXT NOT NULL,
    external_chat_id    TEXT NOT NULL,
    external_user_id    TEXT NOT NULL,
    external_message_id TEXT NOT NULL,
    edit_seq            INTEGER NOT NULL DEFAULT 0,
    raw_text            TEXT NOT NULL,
    detected_route      TEXT NOT NULL
        CHECK (detected_route IN ('start','help','entry','ask','clarify','unknown')),
    created_at          TIMESTAMPTZ NOT NULL,
    UNIQUE (external_chat_id, external_message_id, edit_seq)
);

CREATE TABLE IF NOT EXISTS diary_entries (
    diary_entry_id    TEXT PRIMARY KEY,
    source_message_id TEXT NOT NULL REFERENCES source_messages(source_message_id),
    family_id         TEXT NOT NULL,
    author_user_id    TEXT NOT NULL,
    entry_date        DATE NOT NULL,
    entry_text        TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_diary_entries_source_message_id
    ON diary_entries(source_message_id);

CREATE TABLE IF NOT EXISTS event_chunks (
    chunk_id          TEXT PRIMARY KEY,
    diary_entry_id    TEXT NOT NULL REFERENCES diary_entries(diary_entry_id),
    source_message_id TEXT NOT NULL REFERENCES source_messages(source_message_id),
    family_id         TEXT NOT NULL,
    author_user_id    TEXT NOT NULL,
    entry_date        DATE NOT NULL,
    event_index       INTEGER NOT NULL CHECK (event_index >= 0),
    chunk_text        TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_event_chunks_family_id
    ON event_chunks(family_id);

CREATE INDEX IF NOT EXISTS idx_event_chunks_source_message_id
    ON event_chunks(source_message_id);
