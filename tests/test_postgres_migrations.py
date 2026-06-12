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
    "chat_route_decisions",
    "chat_query_rewrites",
    "chat_knowledge_searches",
    "indexing_dead_letters",
    "author_display_inputs",
)

#: Id of the OP-1.2 / D-046 upgrade migration (filename stem).
UPGRADE_MIGRATION_ID = "0002.index-embedding-status"

#: Id of the OP-2.2 / D-048 dead-letter-table upgrade migration (filename stem).
DEAD_LETTER_MIGRATION_ID = "0003.indexing-dead-letter-table"

#: Id of the D-084 author display-input side-table migration (filename stem).
AUTHOR_DISPLAY_MIGRATION_ID = "0004.author-display-inputs"

#: Id of the H-1 / D-097 subject_id-columns migration (filename stem).
SUBJECT_ID_MIGRATION_ID = "0005.subject-id-columns"

#: Id of the H-3 / D-107 query-subject-scope migration (filename stem).
QUERY_SUBJECT_SCOPE_MIGRATION_ID = "0006.query-subject-scope"

#: Id of the RC-2 / D-108 chat-route-decisions migration (filename stem).
CHAT_ROUTE_DECISIONS_MIGRATION_ID = "0007.chat-route-decisions"

#: Id of the RC-3 / D-108 chat-query-rewrites migration (filename stem).
CHAT_QUERY_REWRITES_MIGRATION_ID = "0008.chat-query-rewrites"

#: Id of the RC-4 / D-108 chat-knowledge-searches migration (filename stem).
CHAT_KNOWLEDGE_SEARCHES_MIGRATION_ID = "0009.chat-knowledge-searches"

#: Index added by the OP-1.2 upgrade migration on ``event_chunks``.
EMBEDDING_STATUS_INDEX = "idx_event_chunks_embedding_status"

#: Number of versioned migrations in the history (baseline + eight upgrades).
MIGRATION_COUNT = 9

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
    """The migration set is the baseline plus the eight upgrades, in order."""
    assert migration_ids() == [
        BASELINE_MIGRATION_ID,
        UPGRADE_MIGRATION_ID,
        DEAD_LETTER_MIGRATION_ID,
        AUTHOR_DISPLAY_MIGRATION_ID,
        SUBJECT_ID_MIGRATION_ID,
        QUERY_SUBJECT_SCOPE_MIGRATION_ID,
        CHAT_ROUTE_DECISIONS_MIGRATION_ID,
        CHAT_QUERY_REWRITES_MIGRATION_ID,
        CHAT_KNOWLEDGE_SEARCHES_MIGRATION_ID,
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
        "0005.subject-id-columns.sql",
        "0006.query-subject-scope.sql",
        "0007.chat-route-decisions.sql",
        "0008.chat-query-rewrites.sql",
        "0009.chat-knowledge-searches.sql",
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


def _column_exists(dsn: str, table: str, column: str) -> bool:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            " WHERE table_name = %s AND column_name = %s",
            (table, column),
        )
        row = cur.fetchone()
    return row is not None


def _column_all_null(dsn: str, table: str, column: str) -> bool:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table} WHERE {column} IS NOT NULL")
        row = cur.fetchone()
    assert row is not None
    return int(row[0]) == 0


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
        prior = migrations.filter(lambda m: m.id in {BASELINE_MIGRATION_ID, UPGRADE_MIGRATION_ID})
        with backend.lock():
            backend.apply_migrations(backend.to_apply(prior))


def _apply_through_0004(dsn: str) -> None:
    """Apply 0001..0004, leaving the 0005..0009 tail pending.

    Stages a genuine prior schema version (no ``subject_id`` columns, no
    ``queries.subject_scope``, no ``chat_route_decisions``, no
    ``chat_query_rewrites``, no ``chat_knowledge_searches``) so a later
    ``apply_migrations`` runs the pending tail as a real non-destructive
    upgrade over populated data."""
    from yoyo import get_backend, read_migrations

    backend = get_backend(mr._yoyo_uri(dsn))
    with migrations_dir() as path:
        migrations = read_migrations(str(path))
        prior = migrations.filter(
            lambda m: m.id
            not in {
                SUBJECT_ID_MIGRATION_ID,
                QUERY_SUBJECT_SCOPE_MIGRATION_ID,
                CHAT_ROUTE_DECISIONS_MIGRATION_ID,
                CHAT_QUERY_REWRITES_MIGRATION_ID,
                CHAT_KNOWLEDGE_SEARCHES_MIGRATION_ID,
            }
        )
        with backend.lock():
            backend.apply_migrations(backend.to_apply(prior))


def _apply_through_0005(dsn: str) -> None:
    """Apply 0001..0005, leaving the 0006..0009 tail pending.

    Stages a genuine prior schema version (no ``queries.subject_scope``
    column, no ``chat_route_decisions``, no ``chat_query_rewrites``, no
    ``chat_knowledge_searches``) so a later ``apply_migrations`` runs
    the pending tail as a real non-destructive upgrade over populated
    data."""
    from yoyo import get_backend, read_migrations

    backend = get_backend(mr._yoyo_uri(dsn))
    with migrations_dir() as path:
        migrations = read_migrations(str(path))
        prior = migrations.filter(
            lambda m: m.id
            not in {
                QUERY_SUBJECT_SCOPE_MIGRATION_ID,
                CHAT_ROUTE_DECISIONS_MIGRATION_ID,
                CHAT_QUERY_REWRITES_MIGRATION_ID,
                CHAT_KNOWLEDGE_SEARCHES_MIGRATION_ID,
            }
        )
        with backend.lock():
            backend.apply_migrations(backend.to_apply(prior))


def _apply_through_0006(dsn: str) -> None:
    """Apply 0001..0006, leaving the 0007..0009 tail pending.

    Stages a genuine prior schema version (no ``chat_route_decisions``
    table, no ``chat_query_rewrites``, no ``chat_knowledge_searches``)
    so a later ``apply_migrations`` runs the pending tail as a real
    non-destructive upgrade over populated data."""
    from yoyo import get_backend, read_migrations

    backend = get_backend(mr._yoyo_uri(dsn))
    with migrations_dir() as path:
        migrations = read_migrations(str(path))
        prior = migrations.filter(
            lambda m: m.id
            not in {
                CHAT_ROUTE_DECISIONS_MIGRATION_ID,
                CHAT_QUERY_REWRITES_MIGRATION_ID,
                CHAT_KNOWLEDGE_SEARCHES_MIGRATION_ID,
            }
        )
        with backend.lock():
            backend.apply_migrations(backend.to_apply(prior))


def _apply_through_0007(dsn: str) -> None:
    """Apply 0001..0007, leaving the 0008..0009 tail pending.

    Stages a genuine prior schema version (no ``chat_query_rewrites``
    table, no ``chat_knowledge_searches``) so a later
    ``apply_migrations`` runs the pending tail as a real non-destructive
    upgrade over populated data."""
    from yoyo import get_backend, read_migrations

    backend = get_backend(mr._yoyo_uri(dsn))
    with migrations_dir() as path:
        migrations = read_migrations(str(path))
        prior = migrations.filter(
            lambda m: m.id
            not in {CHAT_QUERY_REWRITES_MIGRATION_ID, CHAT_KNOWLEDGE_SEARCHES_MIGRATION_ID}
        )
        with backend.lock():
            backend.apply_migrations(backend.to_apply(prior))


def _apply_through_0008(dsn: str) -> None:
    """Apply every migration except the 0009 tail, leaving it pending.

    Stages a genuine prior schema version (no ``chat_knowledge_searches``
    table) so a later ``apply_migrations`` runs the 0009
    chat-knowledge-searches migration as a real non-destructive upgrade
    over populated data."""
    from yoyo import get_backend, read_migrations

    backend = get_backend(mr._yoyo_uri(dsn))
    with migrations_dir() as path:
        migrations = read_migrations(str(path))
        prior = migrations.filter(lambda m: m.id != CHAT_KNOWLEDGE_SEARCHES_MIGRATION_ID)
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


def _insert_query_row(dsn: str, query_id: str) -> None:
    """Insert a queries row using the pre-0006 column list (no subject_scope)."""
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO queries "
            "(query_id, community_id, query_text, model_name, fallback, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                query_id,
                "fam-A",
                "what happened",
                "mock-embedding",
                "none",
                datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC),
            ),
        )


def _insert_decision_row(dsn: str, decision_id: str) -> None:
    """Insert a chat_route_decisions row using the 0007 column list."""
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO chat_route_decisions "
            "(decision_id, community_id, question_text, requested_route, "
            " effective_route, classifier_model_name, classifier_raw_output, "
            " classifier_latency_ms, query_id, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                decision_id,
                "fam-A",
                "what happened",
                "notes_lookup",
                "notes_lookup",
                "mock",
                '{"route": "notes_lookup"}',
                0,
                None,
                datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC),
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
def test_upgrade_0005_preserves_data(clean_db: str) -> None:
    """Applying 0005 over a populated 0001..0004 database is a non-destructive
    upgrade: the nullable ``subject_id`` columns appear, every pre-existing row
    survives, and those rows are ``subject_id IS NULL`` (community-wide)."""
    # Stage a prior schema version (0001..0004) with realistic data.
    _apply_through_0004(clean_db)
    _insert_source_row(clean_db, "src-1")
    _insert_note_row(clean_db, "note-1", "src-1")
    _insert_chunk_row(clean_db, "chunk-1", "note-1", "src-1")
    assert not _column_exists(clean_db, "notes", "subject_id")
    assert not _column_exists(clean_db, "event_chunks", "subject_id")
    assert _yoyo_row_count(clean_db) == MIGRATION_COUNT - 5

    # The real upgrade: the pending tail (0005..0009) applies on top
    # of the populated database.
    apply_migrations(clean_db)

    assert _column_exists(clean_db, "notes", "subject_id")
    assert _column_exists(clean_db, "event_chunks", "subject_id")
    assert _yoyo_row_count(clean_db) == MIGRATION_COUNT
    assert _count_rows(clean_db, "source_messages") == 1
    assert _count_rows(clean_db, "notes") == 1
    assert _count_rows(clean_db, "event_chunks") == 1
    assert _column_all_null(clean_db, "notes", "subject_id")
    assert _column_all_null(clean_db, "event_chunks", "subject_id")


@pgmark
def test_upgrade_0006_preserves_data(clean_db: str) -> None:
    """Applying 0006 over a populated 0001..0005 database is a non-destructive
    upgrade: the nullable ``queries.subject_scope`` column appears, every
    pre-existing row survives, and those rows are ``subject_scope IS NULL``
    (no subject constraint)."""
    # Stage a prior schema version (0001..0005) with realistic data.
    _apply_through_0005(clean_db)
    _insert_query_row(clean_db, "q-1")
    assert not _column_exists(clean_db, "queries", "subject_scope")
    assert _yoyo_row_count(clean_db) == MIGRATION_COUNT - 4

    # The real upgrade: the pending tail (0006..0009) applies on top
    # of the populated database.
    apply_migrations(clean_db)

    assert _column_exists(clean_db, "queries", "subject_scope")
    assert _yoyo_row_count(clean_db) == MIGRATION_COUNT
    assert _count_rows(clean_db, "queries") == 1
    assert _column_all_null(clean_db, "queries", "subject_scope")


@pgmark
def test_upgrade_0007_preserves_data(clean_db: str) -> None:
    """Applying 0007 over a populated 0001..0006 database is a non-destructive
    upgrade: the ``chat_route_decisions`` table appears and every pre-existing
    row survives."""
    # Stage a prior schema version (0001..0006) with realistic data.
    _apply_through_0006(clean_db)
    _insert_query_row(clean_db, "q-1")
    assert not _table_exists(clean_db, "chat_route_decisions")
    assert _yoyo_row_count(clean_db) == MIGRATION_COUNT - 3

    # The real upgrade: the pending tail (0007..0009) applies on top
    # of the populated database.
    apply_migrations(clean_db)

    assert _table_exists(clean_db, "chat_route_decisions")
    assert _yoyo_row_count(clean_db) == MIGRATION_COUNT
    assert _count_rows(clean_db, "queries") == 1
    assert _count_rows(clean_db, "chat_route_decisions") == 0


@pgmark
def test_upgrade_0008_preserves_data(clean_db: str) -> None:
    """Applying 0008 over a populated 0001..0007 database is a non-destructive
    upgrade: the ``chat_query_rewrites`` table appears and every pre-existing
    row survives."""
    # Stage a prior schema version (0001..0007) with realistic data.
    _apply_through_0007(clean_db)
    _insert_query_row(clean_db, "q-1")
    _insert_decision_row(clean_db, "dec-1")
    assert not _table_exists(clean_db, "chat_query_rewrites")
    assert _yoyo_row_count(clean_db) == MIGRATION_COUNT - 2

    # The real upgrade: the pending tail (0008, then 0009) applies on top
    # of the populated database.
    apply_migrations(clean_db)

    assert _table_exists(clean_db, "chat_query_rewrites")
    assert _yoyo_row_count(clean_db) == MIGRATION_COUNT
    assert _count_rows(clean_db, "queries") == 1
    assert _count_rows(clean_db, "chat_route_decisions") == 1
    assert _count_rows(clean_db, "chat_query_rewrites") == 0


@pgmark
def test_upgrade_0009_preserves_data(clean_db: str) -> None:
    """Applying 0009 over a populated 0001..0008 database is a non-destructive
    upgrade: the ``chat_knowledge_searches`` table appears and every
    pre-existing row survives."""
    # Stage a prior schema version (0001..0008) with realistic data.
    _apply_through_0008(clean_db)
    _insert_query_row(clean_db, "q-1")
    _insert_decision_row(clean_db, "dec-1")
    assert not _table_exists(clean_db, "chat_knowledge_searches")
    assert _yoyo_row_count(clean_db) == MIGRATION_COUNT - 1

    # The real upgrade: 0009 applies on top of the populated database.
    apply_migrations(clean_db)

    assert _table_exists(clean_db, "chat_knowledge_searches")
    assert _yoyo_row_count(clean_db) == MIGRATION_COUNT
    assert _count_rows(clean_db, "queries") == 1
    assert _count_rows(clean_db, "chat_route_decisions") == 1
    assert _count_rows(clean_db, "chat_knowledge_searches") == 0


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
