"""yoyo-migrations runner for the Postgres schema (OP-1.1 / D-045).

The versioned migration history under ``migrations/`` is the single canonical
source of the Postgres schema; the previously-canonical ``schema.sql`` has been
retired. ``PostgresDomainStore`` applies migrations to head on construction.

yoyo's psycopg v3 backend is selected via the ``postgresql+psycopg`` URI scheme,
so migration tooling reuses the runtime psycopg v3 driver — no second Postgres
driver is introduced.

Operators can drive this module directly::

    python -m memory_rag.storage.postgres.migrations_runner apply
    python -m memory_rag.storage.postgres.migrations_runner stamp

``stamp`` is the supported one-time adoption step for a pre-existing local
Postgres volume created from the retired raw-schema bootstrap (see RUNBOOK.md).
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from yoyo import get_backend, read_migrations

_MIGRATIONS_PACKAGE = "memory_rag.storage.postgres"
_MIGRATIONS_DIRNAME = "migrations"

#: Id of the baseline migration (filename stem). ``stamp_baseline`` marks only
#: this migration, so adopting a pre-existing volume never silently skips a
#: later, real schema-changing upgrade.
BASELINE_MIGRATION_ID = "0001.baseline-schema"


def _yoyo_uri(dsn: str) -> str:
    """Rewrite a ``postgresql://`` DSN to yoyo's psycopg v3 backend scheme.

    The runtime store uses a plain ``postgresql://`` DSN with psycopg v3. yoyo
    selects its psycopg v3 backend from the ``postgresql+psycopg`` scheme; every
    other DSN component is left unchanged.
    """
    for prefix in ("postgresql://", "postgres://"):
        if dsn.startswith(prefix):
            return "postgresql+psycopg://" + dsn[len(prefix) :]
    raise ValueError(f"unsupported Postgres DSN scheme: {dsn!r}")


@contextmanager
def migrations_dir() -> Iterator[Path]:
    """Yield the packaged ``migrations/`` directory as a real filesystem path.

    Uses :func:`importlib.resources.as_file` so it resolves whether the package
    is run from source or from an installed wheel.
    """
    resource = resources.files(_MIGRATIONS_PACKAGE).joinpath(_MIGRATIONS_DIRNAME)
    with resources.as_file(resource) as path:
        yield path


def migration_ids() -> list[str]:
    """Return the ids of all discoverable migrations, in apply order."""
    with migrations_dir() as path:
        return [str(migration.id) for migration in read_migrations(str(path))]


def apply_migrations(dsn: str) -> None:
    """Apply every pending migration to head against ``dsn``.

    Idempotent: a database already at head is left untouched. Runs under yoyo's
    advisory lock so concurrent callers serialize.
    """
    backend = get_backend(_yoyo_uri(dsn))
    with migrations_dir() as path:
        migrations = read_migrations(str(path))
        with backend.lock():
            backend.apply_migrations(backend.to_apply(migrations))


def stamp_baseline(dsn: str) -> None:
    """Mark the baseline migration as applied WITHOUT running its DDL.

    The supported one-time adoption step for a pre-existing local Postgres
    volume created from the retired raw-schema bootstrap: it already carries the
    baseline schema but has no yoyo version table. After stamping,
    ``apply_migrations`` skips the baseline and applies only later migrations.
    Only the baseline migration is marked, so a future schema-changing upgrade
    is never silently skipped. See RUNBOOK.md.
    """
    backend = get_backend(_yoyo_uri(dsn))
    with migrations_dir() as path:
        migrations = read_migrations(str(path))
        baseline = [m for m in migrations if m.id == BASELINE_MIGRATION_ID]
        if not baseline:
            raise RuntimeError(f"baseline migration {BASELINE_MIGRATION_ID!r} not found in {path}")
        with backend.lock():
            backend.mark_migrations(baseline)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m memory_rag.storage.postgres.migrations_runner",
        description="Apply or stamp Postgres schema migrations (OP-1.1 / D-045).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("apply", help="apply all pending migrations to head")
    sub.add_parser(
        "stamp",
        help="mark the baseline migration as applied without running it "
        "(one-time adoption of a pre-existing local volume)",
    )
    args = parser.parse_args(argv)

    # Imported lazily so the module is importable (and discoverable by tests)
    # without constructing Settings.
    from memory_rag.config import Settings

    dsn = Settings().postgres_dsn()
    if args.command == "apply":
        apply_migrations(dsn)
        print("Postgres migrations applied to head.")
    elif args.command == "stamp":
        stamp_baseline(dsn)
        print(f"Baseline migration {BASELINE_MIGRATION_ID!r} stamped as applied.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
