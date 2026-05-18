"""Failed-embedding reconciliation — discovery and retry (OP-3.1, OP-3.2).

When an embedding provider call fails during ingest, the affected
``event_chunks`` flip to ``embedding_status='failed'`` and stay there
(A-35). This module has two halves:

* **Discovery** (OP-3.1, read-only): ``discover_failed_chunks`` calls the
  ``DomainRepository.list_failed_event_chunks`` seam and wraps the result
  in a :class:`FailedEmbeddingReport`. It performs no retry, no status
  transition, and no dead-letter write.
* **Retry** (OP-3.2, mutating): ``retry_failed_chunks`` re-embeds the
  discovered failed chunks, persists ``EmbeddingRecord`` rows, and
  transitions succeeded chunks ``failed -> ready`` (OP-3.2a). Chunks whose
  retry fails are left ``failed`` (no state regression), reported, and
  routed to the ``indexing_dead_letters`` surface with a best-effort,
  append-only write (OP-3.2b).

Retry groups discovered chunks by ``source_message_id`` so each provider
call replays the same per-source batch ingest used. The bounded retry /
backoff loop stays internal to ``EmbeddingClient.embed`` (OP-2): the
retry path issues one ``embed`` call per group and adds no second loop.

The module is also runnable as an operator entrypoint::

    python -m memory_rag.services.reconciliation --community <id> [--limit N]
    python -m memory_rag.services.reconciliation --community <id> --retry [--limit N]

The CLI targets the canonical durable backend (Postgres): it builds a
``PostgresDomainStore`` from ``Settings``, mirroring
``storage.postgres.migrations_runner``. ``--retry`` additionally builds
an ``EmbeddingClient`` via ``build_embedding_client(Settings())``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from memory_rag.core.domain.models import EventChunk, IndexingDeadLetter
from memory_rag.core.embeddings import EmbeddingClient, EmbeddingRecord, EmbeddingStatus
from memory_rag.logging import get_logger
from memory_rag.storage.repository import DomainRepository

log = get_logger(__name__)

#: Bounded default cap the operator entrypoint applies when ``--limit`` is
#: omitted, so a discovery or retry run never processes an unbounded set.
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


@dataclass(frozen=True, slots=True)
class RetryGroupOutcome:
    """The result of retrying one ``source_message_id`` batch.

    A group is the set of failed chunks sharing a ``source_message_id``;
    it is retried with a single ``EmbeddingClient.embed`` call, so its
    chunks succeed or fail together. ``error_class`` carries the failing
    exception's class name only (never its message) and is set iff the
    group did not succeed. ``dead_letter_id`` is set iff the group failed
    *and* its best-effort ``indexing_dead_letters`` write succeeded; it
    stays ``None`` for succeeded groups and for failed groups whose
    dead-letter write itself failed (logged as ``dead_letter.write_failed``).
    """

    source_message_id: str
    chunk_ids: tuple[str, ...]
    succeeded: bool
    error_class: str | None = None
    dead_letter_id: str | None = None


@dataclass(frozen=True, slots=True)
class RetryOutcomeReport:
    """A community-scoped summary of one retry run.

    ``groups`` is ordered oldest-failure-first — the order discovery
    returns the underlying chunks. The chunk counts are derived so the
    report stays a thin view over the per-group outcomes.
    """

    community_id: str
    groups: tuple[RetryGroupOutcome, ...]

    @property
    def attempted_chunks(self) -> int:
        return sum(len(g.chunk_ids) for g in self.groups)

    @property
    def succeeded_chunks(self) -> int:
        return sum(len(g.chunk_ids) for g in self.groups if g.succeeded)

    @property
    def failed_chunks(self) -> int:
        return self.attempted_chunks - self.succeeded_chunks

    @property
    def groups_succeeded(self) -> int:
        return sum(1 for g in self.groups if g.succeeded)

    @property
    def groups_failed(self) -> int:
        return len(self.groups) - self.groups_succeeded


class ReconciliationService:
    """Discovery and retry over chunks stuck at ``embedding_status='failed'``.

    ``discover_failed_chunks`` is read-only (OP-3.1). ``retry_failed_chunks``
    mutates state (OP-3.2a) and requires an ``EmbeddingClient``; pass one
    to the constructor to enable it.
    """

    def __init__(
        self, store: DomainRepository, embedding_client: EmbeddingClient | None = None
    ) -> None:
        self._store = store
        self._embedding_client = embedding_client

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

    def retry_failed_chunks(
        self, community_id: str, *, limit: int | None = None
    ) -> RetryOutcomeReport:
        """Re-embed the failed chunks for ``community_id`` and report outcomes.

        Discovers failed chunks via ``list_failed_event_chunks`` (the same
        ``limit`` semantics as :meth:`discover_failed_chunks`), groups them
        by ``source_message_id``, and retries each group with one
        ``EmbeddingClient.embed`` call. A succeeding group has its
        ``EmbeddingRecord`` rows persisted before its chunks transition
        ``failed -> ready``; a failing group is left ``failed`` (no state
        regression), reported with the exception class name, and routed to
        the ``indexing_dead_letters`` surface with a best-effort, append-only
        write whose own failure is logged and swallowed. Groups are
        independent — one failure does not stop the others.

        Raises ``RuntimeError`` if the service was built without an
        ``EmbeddingClient``.
        """
        client = self._embedding_client
        if client is None:
            raise RuntimeError(
                "retry_failed_chunks requires an EmbeddingClient; "
                "construct ReconciliationService with one"
            )

        chunks = self._store.list_failed_event_chunks(community_id, limit=limit)
        # Group by source_message_id; insertion order preserves the
        # oldest-failure-first order discovery returned, and replays the
        # per-source batching ingest used.
        groups: dict[str, list[EventChunk]] = {}
        for chunk in chunks:
            groups.setdefault(chunk.source_message_id, []).append(chunk)

        now = datetime.now(tz=UTC)
        outcomes: list[RetryGroupOutcome] = []
        for source_message_id, group in groups.items():
            chunk_ids = tuple(c.chunk_id for c in group)
            try:
                vectors = client.embed([c.chunk_text for c in group])
                # Build records with the run timestamp and honest provider
                # provenance; shape mirrors DomainService._embed_chunks.
                records = [
                    EmbeddingRecord(
                        embedding_record_id=str(uuid4()),
                        chunk_id=chunk.chunk_id,
                        source_message_id=source_message_id,
                        community_id=community_id,
                        model_name=client.model_name,
                        dimension=client.dimension,
                        embedding=vector,
                        created_at=now,
                    )
                    for chunk, vector in zip(group, vectors, strict=True)
                ]
                # Records before status: a chunk is never ``ready`` without
                # its EmbeddingRecord persisted first.
                self._store.save_embedding_records(records)
                for chunk in group:
                    self._store.set_chunk_embedding_status(chunk.chunk_id, EmbeddingStatus.READY)
            except Exception as exc:
                error_class = exc.__class__.__name__
                # Exhausted retry: route the failed group to the OP-2.2
                # dead-letter surface. The group is already failed before
                # this write — the write is best-effort and append-only,
                # so a failure of its own is logged (dead_letter.write_failed)
                # and swallowed, and can never regress the failed outcome.
                dead_letter = IndexingDeadLetter(
                    dead_letter_id=str(uuid4()),
                    source_message_id=source_message_id,
                    community_id=community_id,
                    chunk_ids=chunk_ids,
                    model_name=client.model_name,
                    error_class=error_class,
                    created_at=now,
                )
                # Set iff the write below succeeds — see RetryGroupOutcome.
                dead_letter_id: str | None = None
                try:
                    self._store.save_indexing_dead_letter(dead_letter)
                    dead_letter_id = dead_letter.dead_letter_id
                except Exception as dead_letter_exc:
                    log.warning(
                        "dead_letter.write_failed dead_letter_id=%s error_class=%s",
                        dead_letter.dead_letter_id,
                        dead_letter_exc.__class__.__name__,
                    )
                log.warning(
                    "reconciliation.retry.group.failed community_id=%s "
                    "source_message_id=%s chunks=%d error_class=%s dead_letter_id=%s",
                    community_id,
                    source_message_id,
                    len(group),
                    error_class,
                    "none" if dead_letter_id is None else dead_letter_id,
                )
                outcomes.append(
                    RetryGroupOutcome(
                        source_message_id=source_message_id,
                        chunk_ids=chunk_ids,
                        succeeded=False,
                        error_class=error_class,
                        dead_letter_id=dead_letter_id,
                    )
                )
                continue
            log.info(
                "reconciliation.retry.group.ok community_id=%s "
                "source_message_id=%s chunks=%d model=%s",
                community_id,
                source_message_id,
                len(group),
                client.model_name,
            )
            outcomes.append(
                RetryGroupOutcome(
                    source_message_id=source_message_id,
                    chunk_ids=chunk_ids,
                    succeeded=True,
                )
            )

        report = RetryOutcomeReport(community_id=community_id, groups=tuple(outcomes))
        log.info(
            "reconciliation.retry.summary community_id=%s retried_chunks=%d "
            "succeeded=%d failed=%d groups=%d limit=%s",
            community_id,
            report.attempted_chunks,
            report.succeeded_chunks,
            report.failed_chunks,
            len(report.groups),
            "none" if limit is None else limit,
        )
        return report


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


def render_retry_report(report: RetryOutcomeReport) -> str:
    """Render a :class:`RetryOutcomeReport` as operator-facing text.

    One header line of run totals plus one line per retried group;
    ``error_class`` appears only on failed groups, and ``dead_letter_id``
    only on a failed group whose dead-letter write succeeded.
    """
    header = (
        f"community_id={report.community_id} "
        f"retried_chunks={report.attempted_chunks} "
        f"succeeded={report.succeeded_chunks} "
        f"failed={report.failed_chunks} "
        f"groups={len(report.groups)}"
    )
    if not report.groups:
        return header + "\nNo failed-embedding chunks to retry."
    lines = [header]
    for group in report.groups:
        outcome = "ready" if group.succeeded else "failed"
        line = (
            f"  source_message_id={group.source_message_id} "
            f"chunks={len(group.chunk_ids)} outcome={outcome}"
        )
        if not group.succeeded:
            line += f" error_class={group.error_class}"
            if group.dead_letter_id is not None:
                line += f" dead_letter_id={group.dead_letter_id}"
        lines.append(line)
    return "\n".join(lines)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m memory_rag.services.reconciliation",
        description=(
            "Inspect or retry failed-embedding chunks for a community "
            "(OP-3.1 discovery, OP-3.2a retry)."
        ),
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
        help=f"maximum chunks to process (default {DEFAULT_DISCOVERY_LIMIT})",
    )
    parser.add_argument(
        "--retry",
        action="store_true",
        help="re-embed the failed chunks and transition succeeded ones to ready",
    )
    args = parser.parse_args(argv)

    # Imported lazily so the module is importable (and CLI parsing is
    # testable) without constructing Settings or a Postgres connection.
    from memory_rag.config import Settings
    from memory_rag.storage.postgres import PostgresDomainStore

    settings = Settings()
    store = PostgresDomainStore(settings.postgres_dsn())
    try:
        if args.retry:
            from memory_rag.adapters.embeddings.factory import build_embedding_client

            service = ReconciliationService(store, build_embedding_client(settings))
            output = render_retry_report(
                service.retry_failed_chunks(args.community, limit=args.limit)
            )
        else:
            report = ReconciliationService(store).discover_failed_chunks(
                args.community, limit=args.limit
            )
            output = render_report(report)
    finally:
        store.close()
    print(output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
