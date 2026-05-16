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
)

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


def test_baseline_migration_discoverable() -> None:
    """The migration set is exactly the OP-1.1 baseline."""
    assert migration_ids() == [BASELINE_MIGRATION_ID]


def test_migrations_dir_is_packaged() -> None:
    """The packaged migrations directory resolves to a real .sql file."""
    with migrations_dir() as path:
        sql_files = sorted(p.name for p in path.glob("*.sql"))
    assert sql_files == ["0001.baseline-schema.sql"]


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
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM source_messages")
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


@pytest.fixture
def clean_db() -> Iterator[str]:
    assert PG_DSN is not None
    _reset_schema(PG_DSN)
    yield PG_DSN


@pgmark
def test_fresh_bootstrap_applies_baseline(clean_db: str) -> None:
    """A fresh database is brought to head: all tables + the vector extension."""
    apply_migrations(clean_db)

    for table in DOMAIN_TABLES:
        assert _table_exists(clean_db, table), f"missing table {table}"
    assert _vector_extension_present(clean_db)
    assert _yoyo_row_count(clean_db) == 1
    assert not _baseline_is_pending(clean_db)


@pgmark
def test_apply_is_idempotent(clean_db: str) -> None:
    """Re-running ``apply_migrations`` on a database at head is a no-op."""
    apply_migrations(clean_db)
    apply_migrations(clean_db)

    assert _yoyo_row_count(clean_db) == 1
    assert not _baseline_is_pending(clean_db)


@pgmark
def test_adoption_stamp_path(clean_db: str) -> None:
    """A pre-existing volume (baseline schema, no yoyo state) is adopted by
    ``stamp_baseline`` without a destructive reset and without re-running DDL."""
    # Simulate the old raw-schema bootstrap and some locally-ingested data.
    _apply_baseline_ddl_raw(clean_db)
    _insert_source_row(clean_db, "pre-existing-row")
    assert _baseline_is_pending(clean_db)

    stamp_baseline(clean_db)
    assert not _baseline_is_pending(clean_db)
    assert _yoyo_row_count(clean_db) == 1

    # apply_migrations now skips the already-present baseline; data survives.
    apply_migrations(clean_db)
    assert _yoyo_row_count(clean_db) == 1
    assert _count_source_rows(clean_db) == 1


@pgmark
def test_store_constructor_bootstraps_via_migrations(clean_db: str) -> None:
    """Constructing ``PostgresDomainStore`` applies migrations to head."""
    store = PostgresDomainStore(clean_db)
    try:
        for table in DOMAIN_TABLES:
            assert _table_exists(clean_db, table), f"missing table {table}"
        assert _yoyo_row_count(clean_db) == 1
        assert not _baseline_is_pending(clean_db)
    finally:
        store.close()
