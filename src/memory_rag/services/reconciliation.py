"""Failed-embedding reconciliation — discovery surface (OP-3.1).

When an embedding provider call fails during ingest, the affected
``event_chunks`` flip to ``embedding_status='failed'`` and stay there
(A-35). This module is the read-only discovery half of reconciliation:
it finds those chunks and reports them. It performs no retry, no
``failed -> ready`` transition, and no dead-letter write.

``ReconciliationService.discover_failed_chunks`` calls the
``DomainRepository.list_failed_event_chunks`` seam and wraps the result
in a :class:`FailedEmbeddingReport`. ``render_report`` turns that report
into operator-facing text.

The module is also runnable as an operator entrypoint::

    python -m memory_rag.services.reconciliation --community <id> [--limit N]

The CLI targets the canonical durable backend (Postgres): it builds a
``PostgresDomainStore`` from ``Settings``, mirroring
``storage.postgres.migrations_runner``. Failed chunks persist durably
only in Postgres, so the CLI replaces the hand-run ``psql`` probe that
``docs/RUNBOOK.md`` documented as the failed-chunk inspection surface.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from memory_rag.core.domain.models import EventChunk
from memory_rag.logging import get_logger
from memory_rag.storage.repository import DomainRepository

log = get_logger(__name__)

#: Bounded default cap the operator entrypoint applies when ``--limit`` is
#: omitted, so a discovery run never returns an unbounded result set.
DEFAULT_DISCOVERY_LIMIT = 100


@dataclass(frozen=True, slots=True)
class FailedEmbeddingReport:
    """A community-scoped, point-in-time snapshot of failed-embedding chunks.

    ``chunks`` is ordered oldest-failure-first. ``count`` is the size of
    this returned slice; when it equals the ``limit`` used for discovery,
    more failed chunks may exist beyond the cap.
    """

    community_id: str
    chunks: tuple[EventChunk, ...]

    @property
    def count(self) -> int:
        return len(self.chunks)


class ReconciliationService:
    """Read-only discovery over chunks stuck at ``embedding_status='failed'``."""

    def __init__(self, store: DomainRepository) -> None:
        self._store = store

    def discover_failed_chunks(
        self, community_id: str, *, limit: int | None = None
    ) -> FailedEmbeddingReport:
        """Return the failed-embedding chunks for ``community_id``.

        Delegates to ``DomainRepository.list_failed_event_chunks`` (oldest
        first, community-scoped, ``limit``-capped). No side effects: no
        retry, no status transition, no dead-letter write.
        """
        chunks = self._store.list_failed_event_chunks(community_id, limit=limit)
        log.info(
            "reconciliation.discovered community_id=%s failed_count=%d limit=%s",
            community_id,
            len(chunks),
            "none" if limit is None else limit,
        )
        return FailedEmbeddingReport(community_id=community_id, chunks=tuple(chunks))


def render_report(report: FailedEmbeddingReport) -> str:
    """Render a :class:`FailedEmbeddingReport` as operator-facing text.

    One header line plus one line per failed chunk, carrying the same
    columns the retired ``psql`` probe surfaced.
    """
    header = f"community_id={report.community_id} failed_chunks={report.count}"
    if report.count == 0:
        return header + "\nNo failed-embedding chunks."
    lines = [header]
    for chunk in report.chunks:
        lines.append(
            f"  chunk_id={chunk.chunk_id} "
            f"source_message_id={chunk.source_message_id} "
            f"note_date={chunk.note_date.isoformat()} "
            f"created_at={chunk.created_at.isoformat()}"
        )
    return "\n".join(lines)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m memory_rag.services.reconciliation",
        description="List failed-embedding chunks for a community (OP-3.1, read-only).",
    )
    parser.add_argument(
        "--community",
        required=True,
        help="community_id to inspect (community scoping is mandatory, R-3)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_DISCOVERY_LIMIT,
        help=f"maximum chunks to report (default {DEFAULT_DISCOVERY_LIMIT})",
    )
    args = parser.parse_args(argv)

    # Imported lazily so the module is importable (and CLI parsing is
    # testable) without constructing Settings or a Postgres connection.
    from memory_rag.config import Settings
    from memory_rag.storage.postgres import PostgresDomainStore

    store = PostgresDomainStore(Settings().postgres_dsn())
    try:
        report = ReconciliationService(store).discover_failed_chunks(
            args.community, limit=args.limit
        )
    finally:
        store.close()
    print(render_report(report))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
