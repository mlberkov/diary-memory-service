"""Tests for the Postgres migration tooling (OP-1.1 / D-045).

The discovery tests run offline. The bootstrap/adoption tests need a live
Postgres and are skipped unless ``MEMORY_RAG_PG_TEST_DSN`` is set, so the
offline test flow stays green. The gated tests reset the ``public`` schema,
so point the DSN at a throwaway database.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from memory_rag.storage.postgres import migrations_runner as mr
from memory_rag.storage.postgres.migrations_runner import (
    BASELINE_MIGRATION_ID,
    apply_migrations,
    migration_ids,
    migrations_dir,
    stamp_baseline,
)

DOMAIN_TABLES = (
    "source_messages",
    "notes",
    "event_chunks",
    "embedding_records",
    "queries",
    "retrieval_hits",
    "answer_traces",
    "indexing_dead_letters",
    "author_display_inputs",
)

#: Id of the OP-1.2 / D-046 upgrade migration (filename stem).
UPGRADE_MIGRATION_ID = "0002.index-embedding-status"

#: Id of the OP-2.2 / D-048 dead-letter-table upgrade migration (filename stem).
DEAD_LETTER_MIGRATION_ID = "0003.indexing-dead-letter-table"

#: Id of the D-084 author display-input side-table migration (filename stem).
AUTHOR_DISPLAY_MIGRATION_ID = "0004.author-display-inputs"

#: Index added by the OP-1.2 upgrade migration on ``event_chunks``.
EMBEDDING_STATUS_INDEX = "idx_event_chunks_embedding_status"

#: Number of versioned migrations in the history (baseline + three upgrades).
MIGRATION_COUNT = 4

PG_DSN = os.environ.get("MEMORY_RAG_PG_TEST_DSN")

pgmark = pytest.mark.skipif(
    PG_DSN is None,
    reason="MEMORY_RAG_PG_TEST_DSN not set; Postgres integration tests skipped.",
)

if PG_DSN is not None:
    import psycopg

    from memory_rag.storage.postgres import PostgresDomainStore


# --------------------------------------------------------------------------
# Offline discovery tests — no database required.
# --------------------------------------------------------------------------


def test_migrations_discoverable() -> None:
    """The migration set is the baseline plus the three upgrades, in order."""
    assert migration_ids() == [
        BASELINE_MIGRATION_ID,
        UPGRADE_MIGRATION_ID,
        DEAD_LETTER_MIGRATION_ID,
        AUTHOR_DISPLAY_MIGRATION_ID,
    ]


def test_migrations_dir_is_packaged() -> None:
    """The packaged migrations directory resolves to the real .sql files."""
    with migrations_dir() as path:
        sql_files = sorted(p.name for p in path.glob("*.sql"))
    assert sql_files == [
        "0001.baseline-schema.sql",
        "0002.index-embedding-status.sql",
        "0003.indexing-dead-letter-table.sql",
        "0004.author-display-inputs.sql",
    ]


# --------------------------------------------------------------------------
# Gated integration tests — require MEMORY_RAG_PG_TEST_DSN.
# --------------------------------------------------------------------------


def _reset_schema(dsn: str) -> None:
    """Reset to a brand-new database: empty ``public`` schema, no yoyo state."""
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE")
        cur.execute("CREATE SCHEMA public")


def _table_exists(dsn: str, table: str) -> bool:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (table,))
        row = cur.fetchone()
    return row is not None and row[0] is not None


def _vector_extension_present(dsn: str) -> bool:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        return cur.fetchone() is not None


def _yoyo_row_count(dsn: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM _yoyo_migration")
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _baseline_is_pending(dsn: str) -> bool:
    """True when yoyo still considers the baseline migration un-applied."""
    from yoyo import get_backend, read_migrations

    backend = get_backend(mr._yoyo_uri(dsn))
    with migrations_dir() as path:
        pending = [str(m.id) for m in backend.to_apply(read_migrations(str(path)))]
    return BASELINE_MIGRATION_ID in pending


def _apply_baseline_ddl_raw(dsn: str) -> None:
    """Reproduce the retired raw-schema bootstrap: run the baseline DDL with
    no yoyo metadata, simulating a pre-OP-1.1 local volume."""
    with migrations_dir() as path:
        ddl = (path / "0001.baseline-schema.sql").read_text(encoding="utf-8")
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(ddl)


def _insert_source_row(dsn: str, source_message_id: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO source_messages "
            "(source_message_id, community_id, author_user_id, external_chat_id, "
            " external_user_id, external_message_id, edit_seq, raw_text, "
            " detected_route, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                source_message_id,
                "fam-A",
                "u1",
                "fam-A",
                "u1",
                source_message_id,
                0,
                "2026-05-17\nWalked the dog",
                "note",
                datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC),
            ),
        )


def _count_source_rows(dsn: str) -> int:
    return _count_rows(dsn, "source_messages")


def _count_rows(dsn: str, table: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _index_exists(dsn: str, index_name: str) -> bool:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (index_name,))
        row = cur.fetchone()
    return row is not None and row[0] is not None


def _apply_only_baseline(dsn: str) -> None:
    """Apply only the 0001 baseline through yoyo, leaving 0002 pending.

    Stages a genuine prior schema version so a later ``apply_migrations`` runs
    the 0002 upgrade as a real non-destructive upgrade over populated data."""
    from yoyo import get_backend, read_migrations

    backend = get_backend(mr._yoyo_uri(dsn))
    with migrations_dir() as path:
        migrations = read_migrations(str(path))
        baseline = migrations.filter(lambda m: m.id == BASELINE_MIGRATION_ID)
        with backend.lock():
            backend.apply_migrations(backend.to_apply(baseline))


def _apply_through_0002(dsn: str) -> None:
    """Apply 0001 + 0002 through yoyo, leaving 0003 pending.

    Stages a genuine prior schema version so a later ``apply_migrations`` runs
    the 0003 dead-letter migration as a real non-destructive upgrade over
    populated data."""
    from yoyo import get_backend, read_migrations

    backend = get_backend(mr._yoyo_uri(dsn))
    with migrations_dir() as path:
        migrations = read_migrations(str(path))
        prior = migrations.filter(lambda m: m.id != DEAD_LETTER_MIGRATION_ID)
        with backend.lock():
            backend.apply_migrations(backend.to_apply(prior))


def _insert_note_row(dsn: str, note_id: str, source_message_id: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO notes "
            "(note_id, source_message_id, community_id, author_user_id, "
            " note_date, note_text, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                note_id,
                source_message_id,
                "fam-A",
                "u1",
                datetime(2026, 5, 17).date(),
                "Walked the dog",
                datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC),
            ),
        )


def _insert_chunk_row(dsn: str, chunk_id: str, note_id: str, source_message_id: str) -> None:
    """Insert an event_chunk; ``chunk_text_tsv`` is generated and omitted."""
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO event_chunks "
            "(chunk_id, note_id, source_message_id, community_id, author_user_id, "
            " note_date, event_index, chunk_text, created_at, embedding_status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                chunk_id,
                note_id,
                source_message_id,
                "fam-A",
                "u1",
                datetime(2026, 5, 17).date(),
                0,
                "Walked the dog",
                datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC),
                "failed",
            ),
        )


@pytest.fixture
def clean_db() -> Iterator[str]:
    assert PG_DSN is not None
    _reset_schema(PG_DSN)
    yield PG_DSN


@pgmark
def test_fresh_bootstrap_applies_migrations_to_head(clean_db: str) -> None:
    """A fresh database is brought to head: all tables, the vector extension,
    and the OP-1.2 upgrade index."""
    apply_migrations(clean_db)

    for table in DOMAIN_TABLES:
        assert _table_exists(clean_db, table), f"missing table {table}"
    assert _vector_extension_present(clean_db)
    assert _index_exists(clean_db, EMBEDDING_STATUS_INDEX)
    assert _yoyo_row_count(clean_db) == MIGRATION_COUNT
    assert not _baseline_is_pending(clean_db)


@pgmark
def test_apply_is_idempotent(clean_db: str) -> None:
    """Re-running ``apply_migrations`` on a database at head is a no-op."""
    apply_migrations(clean_db)
    apply_migrations(clean_db)

    assert _yoyo_row_count(clean_db) == MIGRATION_COUNT
    assert not _baseline_is_pending(clean_db)


@pgmark
def test_upgrade_0002_preserves_data(clean_db: str) -> None:
    """Applying 0002 over a populated 0001 database is a non-destructive
    upgrade: the new index appears and every pre-existing row survives."""
    # Stage a prior schema version (0001 only) with realistic data.
    _apply_only_baseline(clean_db)
    _insert_source_row(clean_db, "src-1")
    _insert_note_row(clean_db, "note-1", "src-1")
    _insert_chunk_row(clean_db, "chunk-1", "note-1", "src-1")
    assert not _index_exists(clean_db, EMBEDDING_STATUS_INDEX)
    assert _yoyo_row_count(clean_db) == 1

    # The real upgrade: the pending migrations apply on top of the
    # populated database (0002, then 0003).
    apply_migrations(clean_db)

    assert _index_exists(clean_db, EMBEDDING_STATUS_INDEX)
    assert _yoyo_row_count(clean_db) == MIGRATION_COUNT
    assert _count_rows(clean_db, "source_messages") == 1
    assert _count_rows(clean_db, "notes") == 1
    assert _count_rows(clean_db, "event_chunks") == 1


@pgmark
def test_upgrade_0003_preserves_data(clean_db: str) -> None:
    """Applying 0003 over a populated 0001+0002 database is a non-destructive
    upgrade: the dead-letter table appears and every pre-existing row survives."""
    # Stage a prior schema version (0001 + 0002 only) with realistic data.
    _apply_through_0002(clean_db)
    _insert_source_row(clean_db, "src-1")
    _insert_note_row(clean_db, "note-1", "src-1")
    _insert_chunk_row(clean_db, "chunk-1", "note-1", "src-1")
    assert not _table_exists(clean_db, "indexing_dead_letters")
    assert _yoyo_row_count(clean_db) == 2

    # The real upgrade: 0003 applies on top of the populated database.
    apply_migrations(clean_db)

    assert _table_exists(clean_db, "indexing_dead_letters")
    assert _yoyo_row_count(clean_db) == MIGRATION_COUNT
    assert _count_rows(clean_db, "source_messages") == 1
    assert _count_rows(clean_db, "notes") == 1
    assert _count_rows(clean_db, "event_chunks") == 1


@pgmark
def test_adoption_stamp_path_then_upgrade(clean_db: str) -> None:
    """A pre-existing volume (baseline schema, no yoyo state) is adopted by
    ``stamp_baseline`` without a destructive reset, and the 0002 upgrade then
    applies non-destructively over its populated data."""
    # Simulate the old raw-schema bootstrap and some locally-ingested data.
    _apply_baseline_ddl_raw(clean_db)
    _insert_source_row(clean_db, "pre-existing-row")
    _insert_note_row(clean_db, "pre-existing-note", "pre-existing-row")
    _insert_chunk_row(clean_db, "pre-existing-chunk", "pre-existing-note", "pre-existing-row")
    assert _baseline_is_pending(clean_db)

    stamp_baseline(clean_db)
    assert not _baseline_is_pending(clean_db)
    assert _yoyo_row_count(clean_db) == 1

    # apply_migrations skips the stamped baseline and applies the later
    # migrations; the index appears and all pre-existing data survives.
    apply_migrations(clean_db)
    assert _yoyo_row_count(clean_db) == MIGRATION_COUNT
    assert _index_exists(clean_db, EMBEDDING_STATUS_INDEX)
    assert _count_rows(clean_db, "source_messages") == 1
    assert _count_rows(clean_db, "notes") == 1
    assert _count_rows(clean_db, "event_chunks") == 1


@pgmark
def test_store_constructor_bootstraps_via_migrations(clean_db: str) -> None:
    """Constructing ``PostgresDomainStore`` applies migrations to head."""
    store = PostgresDomainStore(clean_db)
    try:
        for table in DOMAIN_TABLES:
            assert _table_exists(clean_db, table), f"missing table {table}"
        assert _index_exists(clean_db, EMBEDDING_STATUS_INDEX)
        assert _yoyo_row_count(clean_db) == MIGRATION_COUNT
        assert not _baseline_is_pending(clean_db)
    finally:
        store.close()
