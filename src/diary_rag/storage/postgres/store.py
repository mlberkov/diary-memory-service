"""Local PostgreSQL store implementing ``DiaryRepository`` (D-022, D-023, D-024).

Schema is bootstrapped at construction by executing ``schema.sql`` (loaded
via :mod:`importlib.resources` so it works whether the package is run from
source or installed). Connections are managed by a small
:class:`psycopg_pool.ConnectionPool`. Native Postgres types are used for
``TIMESTAMPTZ`` and ``DATE``; ``detected_route`` is TEXT with a CHECK
listing every :class:`RouteKind` value.

Idempotency (R-2 / D-023) is enforced by the
``UNIQUE (external_chat_id, external_message_id, edit_seq)`` constraint on
``source_messages`` plus ``INSERT ... ON CONFLICT DO NOTHING`` in
``get_or_create_source_message``: the DB is the source of truth for "this
message-state has already been ingested," not a SELECT-then-INSERT race.

Phase 3.1+3.2 (D-024): the pgvector ``vector(3072)`` column on
``embedding_records`` matches the production embedding contour
(``text-embedding-3-large``, 3072 dim). The ``pgvector`` Python package
is registered on each pooled connection so list[float] writes and reads
go through native binding. ``embedding_status`` on ``event_chunks`` is
the per-chunk observable state (``pending`` / ``ready`` / ``failed``).
"""

from __future__ import annotations

from importlib import resources
from typing import Any

from pgvector.psycopg import register_vector
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from diary_rag.core.diary.models import DiaryEntry, EventChunk, SourceMessage
from diary_rag.core.embeddings.models import EmbeddingRecord, EmbeddingStatus
from diary_rag.core.routing import RouteKind


def _load_schema_sql() -> str:
    return (
        resources.files("diary_rag.storage.postgres")
        .joinpath("schema.sql")
        .read_text(encoding="utf-8")
    )


def _configure_connection(conn: Connection[Any]) -> None:
    """Register the pgvector codec on every pooled connection."""
    register_vector(conn)


class PostgresDiaryStore:
    """Local Postgres implementation of ``DiaryRepository``."""

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 4) -> None:
        # Bootstrap pass: a tiny pool with no codec config so `CREATE EXTENSION`
        # can run before pgvector is registered. The real pool below registers
        # the codec on every connection it opens.
        boot_pool = ConnectionPool(
            conninfo=dsn,
            min_size=1,
            max_size=1,
            timeout=10,
            open=False,
        )
        boot_pool.open()
        boot_pool.wait(timeout=10)
        try:
            ddl = _load_schema_sql()
            with boot_pool.connection() as conn, conn.cursor() as cur:
                cur.execute(ddl)
                conn.commit()
        finally:
            boot_pool.close()

        self._pool: ConnectionPool = ConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            timeout=10,
            open=False,
            configure=_configure_connection,
        )
        self._pool.open()
        self._pool.wait(timeout=10)

    def close(self) -> None:
        """Release pool resources. Safe to call multiple times."""
        self._pool.close()

    def save_source_message(self, source: SourceMessage) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO source_messages "
                "(source_message_id, family_id, author_user_id, external_chat_id, "
                " external_user_id, external_message_id, edit_seq, raw_text, "
                " detected_route, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    source.source_message_id,
                    source.family_id,
                    source.author_user_id,
                    source.external_chat_id,
                    source.external_user_id,
                    source.external_message_id,
                    source.edit_seq,
                    source.raw_text,
                    source.detected_route.value,
                    source.created_at,
                ),
            )
            conn.commit()

    def get_or_create_source_message(self, source: SourceMessage) -> tuple[SourceMessage, bool]:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "INSERT INTO source_messages "
                "(source_message_id, family_id, author_user_id, external_chat_id, "
                " external_user_id, external_message_id, edit_seq, raw_text, "
                " detected_route, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (external_chat_id, external_message_id, edit_seq) "
                "DO NOTHING",
                (
                    source.source_message_id,
                    source.family_id,
                    source.author_user_id,
                    source.external_chat_id,
                    source.external_user_id,
                    source.external_message_id,
                    source.edit_seq,
                    source.raw_text,
                    source.detected_route.value,
                    source.created_at,
                ),
            )
            inserted = cur.rowcount == 1
            if inserted:
                conn.commit()
                return source, False
            cur.execute(
                "SELECT source_message_id, family_id, author_user_id, "
                "       external_chat_id, external_user_id, external_message_id, "
                "       edit_seq, raw_text, detected_route, created_at "
                "  FROM source_messages "
                " WHERE external_chat_id = %s "
                "   AND external_message_id = %s "
                "   AND edit_seq = %s",
                (source.external_chat_id, source.external_message_id, source.edit_seq),
            )
            row = cur.fetchone()
            conn.commit()
        assert row is not None
        return _row_to_source(row), True

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
                c.embedding_status.value,
            )
            for c in chunks
        ]
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO event_chunks "
                "(chunk_id, diary_entry_id, source_message_id, family_id, "
                " author_user_id, entry_date, event_index, chunk_text, created_at, "
                " embedding_status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                params,
            )
            conn.commit()

    def get_source_message(self, source_message_id: str) -> SourceMessage | None:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT source_message_id, family_id, author_user_id, "
                "       external_chat_id, external_user_id, external_message_id, "
                "       edit_seq, raw_text, detected_route, created_at "
                "  FROM source_messages "
                " WHERE source_message_id = %s",
                (source_message_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return _row_to_source(row)

    def get_diary_entry_by_source_message_id(self, source_message_id: str) -> DiaryEntry | None:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT diary_entry_id, source_message_id, family_id, author_user_id, "
                "       entry_date, entry_text, created_at "
                "  FROM diary_entries "
                " WHERE source_message_id = %s "
                " LIMIT 1",
                (source_message_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return DiaryEntry(
            diary_entry_id=row["diary_entry_id"],
            source_message_id=row["source_message_id"],
            family_id=row["family_id"],
            author_user_id=row["author_user_id"],
            entry_date=row["entry_date"],
            entry_text=row["entry_text"],
            created_at=row["created_at"],
        )

    def count_event_chunks_for_source(self, source_message_id: str) -> int:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM event_chunks WHERE source_message_id = %s",
                (source_message_id,),
            )
            row = cur.fetchone()
        if row is None:
            return 0
        return int(row[0])

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
                "       created_at, embedding_status "
                "  FROM event_chunks "
                " WHERE family_id = %s AND lower(chunk_text) LIKE %s "
                " ORDER BY created_at, event_index "
                " LIMIT %s",
                (family_id, like, top_k),
            )
            rows = cur.fetchall()
        return [_row_to_chunk(r) for r in rows]

    def save_embedding_records(self, records: list[EmbeddingRecord]) -> None:
        if not records:
            return
        params = [
            (
                r.embedding_record_id,
                r.chunk_id,
                r.source_message_id,
                r.family_id,
                r.model_name,
                r.dimension,
                r.embedding,
                r.created_at,
            )
            for r in records
        ]
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO embedding_records "
                "(embedding_record_id, chunk_id, source_message_id, family_id, "
                " model_name, dimension, embedding, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                params,
            )
            conn.commit()

    def count_embedding_records_for_source(self, source_message_id: str) -> int:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM embedding_records WHERE source_message_id = %s",
                (source_message_id,),
            )
            row = cur.fetchone()
        if row is None:
            return 0
        return int(row[0])

    def set_chunk_embedding_status(self, chunk_id: str, status: EmbeddingStatus) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE event_chunks SET embedding_status = %s WHERE chunk_id = %s",
                (status.value, chunk_id),
            )
            if cur.rowcount != 1:
                raise KeyError(f"unknown chunk_id={chunk_id}")
            conn.commit()


def _row_to_source(row: dict[str, Any]) -> SourceMessage:
    return SourceMessage(
        source_message_id=row["source_message_id"],
        family_id=row["family_id"],
        author_user_id=row["author_user_id"],
        external_chat_id=row["external_chat_id"],
        external_user_id=row["external_user_id"],
        external_message_id=row["external_message_id"],
        edit_seq=int(row["edit_seq"]),
        raw_text=row["raw_text"],
        detected_route=RouteKind(row["detected_route"]),
        created_at=row["created_at"],
    )


def _row_to_chunk(row: dict[str, Any]) -> EventChunk:
    return EventChunk(
        chunk_id=row["chunk_id"],
        diary_entry_id=row["diary_entry_id"],
        source_message_id=row["source_message_id"],
        family_id=row["family_id"],
        author_user_id=row["author_user_id"],
        entry_date=row["entry_date"],
        event_index=row["event_index"],
        chunk_text=row["chunk_text"],
        created_at=row["created_at"],
        embedding_status=EmbeddingStatus(row["embedding_status"]),
    )


__all__ = ["PostgresDiaryStore"]
