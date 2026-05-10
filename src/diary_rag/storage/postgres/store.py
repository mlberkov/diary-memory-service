"""Local PostgreSQL store implementing ``DiaryRepository`` (D-022).

Schema is bootstrapped at construction by executing ``schema.sql`` (loaded
via :mod:`importlib.resources` so it works whether the package is run from
source or installed). Connections are managed by a small
:class:`psycopg_pool.ConnectionPool`. Native Postgres types are used for
``TIMESTAMPTZ`` and ``DATE``; ``detected_route`` is TEXT with a CHECK
listing every :class:`RouteKind` value.
"""

from __future__ import annotations

from importlib import resources

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from diary_rag.core.diary.models import DiaryEntry, EventChunk, SourceMessage
from diary_rag.core.routing import RouteKind


def _load_schema_sql() -> str:
    return (
        resources.files("diary_rag.storage.postgres")
        .joinpath("schema.sql")
        .read_text(encoding="utf-8")
    )


class PostgresDiaryStore:
    """Local Postgres implementation of ``DiaryRepository``."""

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 4) -> None:
        self._pool: ConnectionPool = ConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            timeout=10,
            open=False,
        )
        self._pool.open()
        self._pool.wait(timeout=10)
        self._bootstrap_schema()

    def _bootstrap_schema(self) -> None:
        ddl = _load_schema_sql()
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(ddl)
            conn.commit()

    def close(self) -> None:
        """Release pool resources. Safe to call multiple times."""
        self._pool.close()

    def save_source_message(self, source: SourceMessage) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO source_messages "
                "(source_message_id, family_id, author_user_id, external_chat_id, "
                " external_user_id, raw_text, detected_route, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    source.source_message_id,
                    source.family_id,
                    source.author_user_id,
                    source.external_chat_id,
                    source.external_user_id,
                    source.raw_text,
                    source.detected_route.value,
                    source.created_at,
                ),
            )
            conn.commit()

    def save_diary_entry(self, entry: DiaryEntry) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO diary_entries "
                "(diary_entry_id, source_message_id, family_id, author_user_id, "
                " entry_date, entry_text, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    entry.diary_entry_id,
                    entry.source_message_id,
                    entry.family_id,
                    entry.author_user_id,
                    entry.entry_date,
                    entry.entry_text,
                    entry.created_at,
                ),
            )
            conn.commit()

    def save_event_chunks(self, chunks: list[EventChunk]) -> None:
        if not chunks:
            return
        params = [
            (
                c.chunk_id,
                c.diary_entry_id,
                c.source_message_id,
                c.family_id,
                c.author_user_id,
                c.entry_date,
                c.event_index,
                c.chunk_text,
                c.created_at,
            )
            for c in chunks
        ]
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO event_chunks "
                "(chunk_id, diary_entry_id, source_message_id, family_id, "
                " author_user_id, entry_date, event_index, chunk_text, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                params,
            )
            conn.commit()

    def get_source_message(self, source_message_id: str) -> SourceMessage | None:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT source_message_id, family_id, author_user_id, "
                "       external_chat_id, external_user_id, raw_text, "
                "       detected_route, created_at "
                "  FROM source_messages "
                " WHERE source_message_id = %s",
                (source_message_id,),
            )
            row = cur.fetchone()
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
            created_at=row["created_at"],
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
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT chunk_id, diary_entry_id, source_message_id, family_id, "
                "       author_user_id, entry_date, event_index, chunk_text, "
                "       created_at "
                "  FROM event_chunks "
                " WHERE family_id = %s AND lower(chunk_text) LIKE %s "
                " ORDER BY created_at, event_index "
                " LIMIT %s",
                (family_id, like, top_k),
            )
            rows = cur.fetchall()
        return [
            EventChunk(
                chunk_id=r["chunk_id"],
                diary_entry_id=r["diary_entry_id"],
                source_message_id=r["source_message_id"],
                family_id=r["family_id"],
                author_user_id=r["author_user_id"],
                entry_date=r["entry_date"],
                event_index=r["event_index"],
                chunk_text=r["chunk_text"],
                created_at=r["created_at"],
            )
            for r in rows
        ]


__all__ = ["PostgresDiaryStore"]
