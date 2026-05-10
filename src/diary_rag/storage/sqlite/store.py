"""Local-disk SQLite store implementing ``DiaryRepository``.

Schema is bootstrapped at construction via ``CREATE TABLE IF NOT EXISTS``
and a single ``CREATE INDEX``. A fresh ``sqlite3.Connection`` is opened
per public method call, so the store is safe under FastAPI's threadpool
without shared-connection care. Dates and timestamps are serialized as
ISO-8601 TEXT at the boundary; no ``detect_types`` magic.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

from diary_rag.core.diary.models import DiaryEntry, EventChunk, SourceMessage
from diary_rag.core.routing import RouteKind

_DDL = """
CREATE TABLE IF NOT EXISTS source_messages (
    source_message_id TEXT PRIMARY KEY,
    family_id         TEXT NOT NULL,
    author_user_id    TEXT NOT NULL,
    external_chat_id  TEXT NOT NULL,
    external_user_id  TEXT NOT NULL,
    raw_text          TEXT NOT NULL,
    detected_route    TEXT NOT NULL,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS diary_entries (
    diary_entry_id    TEXT PRIMARY KEY,
    source_message_id TEXT NOT NULL REFERENCES source_messages(source_message_id),
    family_id         TEXT NOT NULL,
    author_user_id    TEXT NOT NULL,
    entry_date        TEXT NOT NULL,
    entry_text        TEXT NOT NULL,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_chunks (
    chunk_id          TEXT PRIMARY KEY,
    diary_entry_id    TEXT NOT NULL REFERENCES diary_entries(diary_entry_id),
    source_message_id TEXT NOT NULL REFERENCES source_messages(source_message_id),
    family_id         TEXT NOT NULL,
    author_user_id    TEXT NOT NULL,
    entry_date        TEXT NOT NULL,
    event_index       INTEGER NOT NULL CHECK (event_index >= 0),
    chunk_text        TEXT NOT NULL,
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_event_chunks_family_id
    ON event_chunks(family_id);
"""


class SqliteDiaryStore:
    """Local-disk SQLite implementation of ``DiaryRepository``."""

    def __init__(self, path: str) -> None:
        self._path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executescript(_DDL)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def save_source_message(self, source: SourceMessage) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO source_messages "
                "(source_message_id, family_id, author_user_id, external_chat_id, "
                " external_user_id, raw_text, detected_route, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    source.source_message_id,
                    source.family_id,
                    source.author_user_id,
                    source.external_chat_id,
                    source.external_user_id,
                    source.raw_text,
                    source.detected_route.value,
                    source.created_at.isoformat(),
                ),
            )
            conn.commit()

    def save_diary_entry(self, entry: DiaryEntry) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO diary_entries "
                "(diary_entry_id, source_message_id, family_id, author_user_id, "
                " entry_date, entry_text, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.diary_entry_id,
                    entry.source_message_id,
                    entry.family_id,
                    entry.author_user_id,
                    entry.entry_date.isoformat(),
                    entry.entry_text,
                    entry.created_at.isoformat(),
                ),
            )
            conn.commit()

    def save_event_chunks(self, chunks: list[EventChunk]) -> None:
        if not chunks:
            return
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO event_chunks "
                "(chunk_id, diary_entry_id, source_message_id, family_id, "
                " author_user_id, entry_date, event_index, chunk_text, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        c.chunk_id,
                        c.diary_entry_id,
                        c.source_message_id,
                        c.family_id,
                        c.author_user_id,
                        c.entry_date.isoformat(),
                        c.event_index,
                        c.chunk_text,
                        c.created_at.isoformat(),
                    )
                    for c in chunks
                ],
            )
            conn.commit()

    def get_source_message(self, source_message_id: str) -> SourceMessage | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT source_message_id, family_id, author_user_id, "
                "       external_chat_id, external_user_id, raw_text, "
                "       detected_route, created_at "
                "  FROM source_messages "
                " WHERE source_message_id = ?",
                (source_message_id,),
            ).fetchone()
        if row is None:
            return None
        return SourceMessage(
            source_message_id=row["source_message_id"],
            family_id=row["family_id"],
            author_user_id=row["author_user_id"],
            external_chat_id=row["external_chat_id"],
            external_user_id=row["external_user_id"],
            raw_text=row["raw_text"],
            detected_route=RouteKind(row["detected_route"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def search_chunks(self, family_id: str, query_text: str, top_k: int) -> list[EventChunk]:
        if not family_id:
            raise ValueError("family_id is required (Runtime invariant R-3)")
        if top_k <= 0:
            return []
        needle = query_text.strip().lower()
        if not needle:
            return []
        like = f"%{needle}%"
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT chunk_id, diary_entry_id, source_message_id, family_id, "
                "       author_user_id, entry_date, event_index, chunk_text, "
                "       created_at "
                "  FROM event_chunks "
                " WHERE family_id = ? AND lower(chunk_text) LIKE ? "
                " ORDER BY created_at, event_index "
                " LIMIT ?",
                (family_id, like, top_k),
            ).fetchall()
        return [
            EventChunk(
                chunk_id=r["chunk_id"],
                diary_entry_id=r["diary_entry_id"],
                source_message_id=r["source_message_id"],
                family_id=r["family_id"],
                author_user_id=r["author_user_id"],
                entry_date=date.fromisoformat(r["entry_date"]),
                event_index=r["event_index"],
                chunk_text=r["chunk_text"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]
