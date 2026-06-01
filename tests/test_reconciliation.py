"""Tests for the failed-embedding reconciliation service (OP-3.1, OP-3.2).

Covers ``ReconciliationService.discover_failed_chunks`` (read-only
discovery), ``retry_failed_chunks`` (mutating retry, including the
OP-3.2b exhausted-retry dead-letter routing), the report renderers, and
the ``_main`` operator entrypoint. The CLI targets
Postgres in production; ``_main`` is exercised here with injected
dependencies so the wiring is covered offline under ``make check``.
Postgres-gated cases exercise the service against the real backend.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest

from memory_rag.adapters.embeddings.mock import MockEmbeddingClient
from memory_rag.core.domain.models import (
    EventChunk,
    IndexingDeadLetter,
    Note,
    SourceMessage,
)
from memory_rag.core.embeddings.models import EmbeddingRecord, EmbeddingStatus
from memory_rag.core.routing import RouteKind
from memory_rag.services.reconciliation import (
    DEFAULT_DISCOVERY_LIMIT,
    FailedEmbeddingReport,
    ReconciliationService,
    RetryGroupOutcome,
    RetryOutcomeReport,
    _main,
    render_report,
    render_retry_report,
)
from memory_rag.storage.mock import MockDomainStore

PG_DSN = os.environ.get("MEMORY_RAG_PG_TEST_DSN")

_NOTE_DATE = date(2026, 5, 9)


def _at(hour: int) -> datetime:
    return datetime(2026, 5, 9, hour, 0, 0, tzinfo=UTC)


def _source(sid: str, community_id: str) -> SourceMessage:
    return SourceMessage(
        source_message_id=sid,
        community_id=community_id,
        author_user_id="u1",
        external_chat_id=community_id,
        external_user_id="u1",
        external_message_id=sid,
        edit_seq=0,
        raw_text="2026-05-09\nWalked the dog",
        detected_route=RouteKind.NOTE,
        created_at=_at(12),
    )


def _note(nid: str, sid: str, community_id: str) -> Note:
    return Note(
        note_id=nid,
        source_message_id=sid,
        community_id=community_id,
        author_user_id="u1",
        note_date=_NOTE_DATE,
        note_text="Walked the dog",
        created_at=_at(12),
    )


def _chunk(
    cid: str,
    status: EmbeddingStatus,
    created_at: datetime,
    *,
    sid: str = "s1",
    text: str = "Walked the dog",
) -> EventChunk:
    return EventChunk(
        chunk_id=cid,
        note_id="n1",
        source_message_id=sid,
        community_id="fam-A",
        author_user_id="u1",
        note_date=_NOTE_DATE,
        event_index=0,
        chunk_text=text,
        created_at=created_at,
        embedding_status=status,
    )


def _seeded_mock_store() -> MockDomainStore:
    store = MockDomainStore()
    store.save_source_message(_source("s1", "fam-A"))
    store.save_note(_note("n1", "s1", "fam-A"))
    store.save_event_chunks(
        [
            _chunk("c-new", EmbeddingStatus.FAILED, _at(12)),
            _chunk("c-old", EmbeddingStatus.FAILED, _at(10)),
            _chunk("c-ready", EmbeddingStatus.READY, _at(11)),
        ]
    )
    return store


# ---------------------------------------------------------------------------
# ReconciliationService.discover_failed_chunks
# ---------------------------------------------------------------------------


def test_discover_returns_failed_chunks_oldest_first() -> None:
    report = ReconciliationService(_seeded_mock_store()).discover_failed_chunks("fam-A")
    assert isinstance(report, FailedEmbeddingReport)
    assert report.community_id == "fam-A"
    assert [c.chunk_id for c in report.chunks] == ["c-old", "c-new"]
    assert report.count == 2


def test_discover_empty_community_reports_zero() -> None:
    report = ReconciliationService(_seeded_mock_store()).discover_failed_chunks("fam-none")
    assert report.chunks == ()
    assert report.count == 0


def test_discover_respects_limit() -> None:
    report = ReconciliationService(_seeded_mock_store()).discover_failed_chunks("fam-A", limit=1)
    assert [c.chunk_id for c in report.chunks] == ["c-old"]
    assert report.count == 1


def test_discover_is_read_only() -> None:
    """Discovery transitions no status and adds/removes no chunk."""
    store = _seeded_mock_store()
    ReconciliationService(store).discover_failed_chunks("fam-A")
    statuses = {}
    for cid in ("c-old", "c-new", "c-ready"):
        chunk = store.get_event_chunk(cid, community_id="fam-A")
        assert chunk is not None
        statuses[cid] = chunk.embedding_status
    assert statuses["c-old"] is EmbeddingStatus.FAILED
    assert statuses["c-new"] is EmbeddingStatus.FAILED
    assert statuses["c-ready"] is EmbeddingStatus.READY
    assert store.len_chunks() == 3


# ---------------------------------------------------------------------------
# render_report
# ---------------------------------------------------------------------------


def test_render_report_lists_each_failed_chunk() -> None:
    report = ReconciliationService(_seeded_mock_store()).discover_failed_chunks("fam-A")
    text = render_report(report)
    assert "community_id=fam-A failed_chunks=2" in text
    assert "chunk_id=c-old" in text
    assert "chunk_id=c-new" in text
    assert text.count("chunk_id=") == 2


def test_render_report_empty_result() -> None:
    text = render_report(FailedEmbeddingReport(community_id="fam-A", chunks=()))
    assert "failed_chunks=0" in text
    assert "No failed-embedding chunks." in text


# ---------------------------------------------------------------------------
# _main operator entrypoint
# ---------------------------------------------------------------------------


def test_main_requires_community() -> None:
    """`--community` is mandatory; argparse exits before any store is built."""
    with pytest.raises(SystemExit):
        _main(["--limit", "5"])


class _ClosableMockStore(MockDomainStore):
    """MockDomainStore with the `close()` the CLI calls on a Postgres store."""

    def close(self) -> None:  # pragma: no cover - trivial
        pass


def test_main_lists_failed_chunks_with_injected_store(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`_main` wires parse -> discover -> render -> print with a stand-in store."""
    store = _ClosableMockStore()
    store.save_source_message(_source("s1", "fam-A"))
    store.save_note(_note("n1", "s1", "fam-A"))
    store.save_event_chunks([_chunk("c-old", EmbeddingStatus.FAILED, _at(10))])

    class _FakeSettings:
        def postgres_dsn(self) -> str:
            return "postgresql://unused/in-this-test"

    monkeypatch.setattr("memory_rag.config.Settings", _FakeSettings)
    monkeypatch.setattr("memory_rag.storage.postgres.PostgresDomainStore", lambda _dsn: store)

    exit_code = _main(["--community", "fam-A"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "community_id=fam-A failed_chunks=1" in out
    assert "chunk_id=c-old" in out


def test_default_discovery_limit_is_bounded() -> None:
    assert isinstance(DEFAULT_DISCOVERY_LIMIT, int)
    assert DEFAULT_DISCOVERY_LIMIT > 0


# ---------------------------------------------------------------------------
# ReconciliationService.retry_failed_chunks (OP-3.2a)
# ---------------------------------------------------------------------------


class _RaisingEmbeddingClient(MockEmbeddingClient):
    """Embedding client whose ``embed()`` always raises.

    Simulates a provider retry loop (OP-2) that exhausted: the bounded
    backoff lives inside the real client, so reconciliation sees only the
    re-raised exception.
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("provider exhausted")


class _FlakyEmbeddingClient(MockEmbeddingClient):
    """Raises for any batch carrying the ``BOOM`` marker; embeds the rest."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        if any("BOOM" in t for t in texts):
            raise RuntimeError("provider exhausted")
        return super().embed(texts)


class _CountingEmbeddingClient(MockEmbeddingClient):
    """Records how many ``embed()`` calls it received."""

    def __init__(self, dimension: int = 64) -> None:
        super().__init__(dimension=dimension)
        self.embed_calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls += 1
        return super().embed(texts)


class _StatusFailingStore(MockDomainStore):
    """MockDomainStore whose status flip always raises, as if the chunk
    vanished between discovery and the ``failed -> ready`` transition."""

    def set_chunk_embedding_status(self, chunk_id: str, status: EmbeddingStatus) -> None:
        raise KeyError(f"unknown chunk_id={chunk_id}")


def _two_source_store() -> MockDomainStore:
    """Failed chunks spread across two ``source_message_id`` batches."""
    store = MockDomainStore()
    store.save_event_chunks(
        [
            _chunk("c-s1-a", EmbeddingStatus.FAILED, _at(10), sid="s1"),
            _chunk("c-s1-b", EmbeddingStatus.FAILED, _at(11), sid="s1"),
            _chunk("c-s2-a", EmbeddingStatus.FAILED, _at(12), sid="s2"),
        ]
    )
    return store


def test_retry_success_persists_records_and_flips_status() -> None:
    store = _seeded_mock_store()
    report = ReconciliationService(store, MockEmbeddingClient(dimension=64)).retry_failed_chunks(
        "fam-A"
    )

    assert isinstance(report, RetryOutcomeReport)
    assert report.attempted_chunks == 2
    assert report.succeeded_chunks == 2
    assert report.failed_chunks == 0
    assert report.groups_succeeded == 1
    for cid in ("c-old", "c-new"):
        chunk = store.get_event_chunk(cid, community_id="fam-A")
        assert chunk is not None
        assert chunk.embedding_status is EmbeddingStatus.READY
    assert store.len_embeddings() == 2
    # Honest provenance: records carry the mock's identity (D-024).
    for record in store._embeddings.values():
        assert record.model_name == "mock"
        assert record.dimension == 64


def test_retry_exhausted_failure_leaves_chunks_failed() -> None:
    store = _seeded_mock_store()
    report = ReconciliationService(
        store, _RaisingEmbeddingClient(dimension=64)
    ).retry_failed_chunks("fam-A")

    assert report.succeeded_chunks == 0
    assert report.failed_chunks == 2
    assert report.groups_failed == 1
    assert report.groups[0].succeeded is False
    assert report.groups[0].error_class == "RuntimeError"
    for cid in ("c-old", "c-new"):
        chunk = store.get_event_chunk(cid, community_id="fam-A")
        assert chunk is not None
        assert chunk.embedding_status is EmbeddingStatus.FAILED
    assert store.len_embeddings() == 0


def test_retry_groups_by_source_message_id() -> None:
    store = _two_source_store()
    report = ReconciliationService(store, MockEmbeddingClient(dimension=64)).retry_failed_chunks(
        "fam-A"
    )

    assert [g.source_message_id for g in report.groups] == ["s1", "s2"]
    assert report.groups[0].chunk_ids == ("c-s1-a", "c-s1-b")
    assert report.groups[1].chunk_ids == ("c-s2-a",)
    assert report.attempted_chunks == 3
    assert report.succeeded_chunks == 3


def test_retry_mixed_group_outcomes() -> None:
    store = MockDomainStore()
    store.save_event_chunks(
        [
            _chunk("c-s1", EmbeddingStatus.FAILED, _at(10), sid="s1"),
            _chunk("c-s2", EmbeddingStatus.FAILED, _at(11), sid="s2", text="BOOM"),
        ]
    )
    report = ReconciliationService(store, _FlakyEmbeddingClient(dimension=64)).retry_failed_chunks(
        "fam-A"
    )

    by_sid = {g.source_message_id: g for g in report.groups}
    assert by_sid["s1"].succeeded is True
    assert by_sid["s2"].succeeded is False
    assert by_sid["s2"].error_class == "RuntimeError"
    s1_chunk = store.get_event_chunk("c-s1", community_id="fam-A")
    s2_chunk = store.get_event_chunk("c-s2", community_id="fam-A")
    assert s1_chunk is not None and s1_chunk.embedding_status is EmbeddingStatus.READY
    assert s2_chunk is not None and s2_chunk.embedding_status is EmbeddingStatus.FAILED
    assert store.len_embeddings() == 1


def test_retry_empty_failed_set_is_noop() -> None:
    store = _seeded_mock_store()
    client = _CountingEmbeddingClient(dimension=64)
    report = ReconciliationService(store, client).retry_failed_chunks("fam-none")

    assert report.groups == ()
    assert report.attempted_chunks == 0
    assert client.embed_calls == 0


def test_retry_respects_limit() -> None:
    store = _seeded_mock_store()
    report = ReconciliationService(store, MockEmbeddingClient(dimension=64)).retry_failed_chunks(
        "fam-A", limit=1
    )

    assert report.attempted_chunks == 1
    # Oldest failure first: c-old is retried, c-new is left untouched.
    assert report.groups[0].chunk_ids == ("c-old",)
    old = store.get_event_chunk("c-old", community_id="fam-A")
    new = store.get_event_chunk("c-new", community_id="fam-A")
    assert old is not None and old.embedding_status is EmbeddingStatus.READY
    assert new is not None and new.embedding_status is EmbeddingStatus.FAILED


def test_retry_records_before_status_ordering() -> None:
    """A status-flip failure still leaves the EmbeddingRecord persisted and
    reports the group failed — records are written before the transition."""
    store = _StatusFailingStore()
    store.save_event_chunks([_chunk("c-old", EmbeddingStatus.FAILED, _at(10))])
    report = ReconciliationService(store, MockEmbeddingClient(dimension=64)).retry_failed_chunks(
        "fam-A"
    )

    assert report.groups[0].succeeded is False
    assert report.groups[0].error_class == "KeyError"
    assert store.len_embeddings() == 1
    chunk = store.get_event_chunk("c-old", community_id="fam-A")
    assert chunk is not None
    assert chunk.embedding_status is EmbeddingStatus.FAILED


def test_retry_unique_collision_reports_group_failed() -> None:
    store = MockDomainStore()
    store.save_event_chunks([_chunk("c-old", EmbeddingStatus.FAILED, _at(10))])
    # Pre-seed a record so the retry write collides on the storage
    # UNIQUE (chunk_id, model_name) guard.
    store.save_embedding_records(
        [
            EmbeddingRecord(
                embedding_record_id="pre-1",
                chunk_id="c-old",
                source_message_id="s1",
                community_id="fam-A",
                model_name="mock",
                dimension=64,
                embedding=[0.0] * 64,
                created_at=_at(9),
            )
        ]
    )
    report = ReconciliationService(store, MockEmbeddingClient(dimension=64)).retry_failed_chunks(
        "fam-A"
    )

    assert report.groups[0].succeeded is False
    assert report.groups[0].error_class == "ValueError"
    chunk = store.get_event_chunk("c-old", community_id="fam-A")
    assert chunk is not None
    assert chunk.embedding_status is EmbeddingStatus.FAILED
    assert store.len_embeddings() == 1


def test_retry_without_embedding_client_raises() -> None:
    store = _seeded_mock_store()
    with pytest.raises(RuntimeError, match="requires an EmbeddingClient"):
        ReconciliationService(store).retry_failed_chunks("fam-A")


# ---------------------------------------------------------------------------
# retry_failed_chunks dead-letter routing (OP-3.2b)
# ---------------------------------------------------------------------------


class _DeadLetterWriteFailsStore(MockDomainStore):
    """MockDomainStore whose dead-letter write always raises, as if the
    ``indexing_dead_letters`` sink were unavailable."""

    def save_indexing_dead_letter(self, record: IndexingDeadLetter) -> None:
        raise RuntimeError("dead-letter sink down")


def test_retry_exhausted_group_writes_one_dead_letter() -> None:
    """An exhausted retry routes the failed group to ``indexing_dead_letters``."""
    store = _seeded_mock_store()
    report = ReconciliationService(
        store, _RaisingEmbeddingClient(dimension=64)
    ).retry_failed_chunks("fam-A")

    group = report.groups[0]
    assert group.succeeded is False
    assert group.dead_letter_id is not None

    rows = store.list_indexing_dead_letters("fam-A")
    assert len(rows) == 1
    row = rows[0]
    assert row.dead_letter_id == group.dead_letter_id
    assert row.source_message_id == "s1"
    assert row.community_id == "fam-A"
    assert set(row.chunk_ids) == {"c-old", "c-new"}
    # Honest provenance: the mock client reports its own identity (D-024).
    assert row.model_name == "mock"
    assert row.error_class == "RuntimeError"


def test_retry_dead_letter_write_failure_is_swallowed() -> None:
    """A failing dead-letter write never regresses the failed outcome."""
    store = _DeadLetterWriteFailsStore()
    store.save_event_chunks([_chunk("c-old", EmbeddingStatus.FAILED, _at(10))])

    # retry_failed_chunks must not raise despite the dead-letter sink failing.
    report = ReconciliationService(
        store, _RaisingEmbeddingClient(dimension=64)
    ).retry_failed_chunks("fam-A")

    group = report.groups[0]
    assert group.succeeded is False
    assert group.error_class == "RuntimeError"
    # The write failed, so no dead-letter identity is carried.
    assert group.dead_letter_id is None
    assert store.len_indexing_dead_letters() == 0
    # No state regression: the chunk stays failed.
    chunk = store.get_event_chunk("c-old", community_id="fam-A")
    assert chunk is not None
    assert chunk.embedding_status is EmbeddingStatus.FAILED


def test_retry_dead_letter_write_failure_logs_write_failed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _DeadLetterWriteFailsStore()
    store.save_event_chunks([_chunk("c-old", EmbeddingStatus.FAILED, _at(10))])

    with caplog.at_level("WARNING"):
        ReconciliationService(store, _RaisingEmbeddingClient(dimension=64)).retry_failed_chunks(
            "fam-A"
        )

    assert "dead_letter.write_failed" in caplog.text


def test_retry_success_writes_no_dead_letter() -> None:
    """A fully succeeding retry routes nothing to the dead-letter surface."""
    store = _seeded_mock_store()
    report = ReconciliationService(store, MockEmbeddingClient(dimension=64)).retry_failed_chunks(
        "fam-A"
    )

    assert store.len_indexing_dead_letters() == 0
    assert all(g.dead_letter_id is None for g in report.groups)


# ---------------------------------------------------------------------------
# render_retry_report
# ---------------------------------------------------------------------------


def test_render_retry_report_lists_each_group() -> None:
    store = MockDomainStore()
    store.save_event_chunks(
        [
            _chunk("c-s1", EmbeddingStatus.FAILED, _at(10), sid="s1"),
            _chunk("c-s2", EmbeddingStatus.FAILED, _at(11), sid="s2", text="BOOM"),
        ]
    )
    report = ReconciliationService(store, _FlakyEmbeddingClient(dimension=64)).retry_failed_chunks(
        "fam-A"
    )
    text = render_retry_report(report)

    assert "community_id=fam-A retried_chunks=2 succeeded=1 failed=1 groups=2" in text
    assert "source_message_id=s1 chunks=1 outcome=ready" in text
    assert "source_message_id=s2 chunks=1 outcome=failed error_class=RuntimeError" in text
    # error_class is rendered only for the failed group.
    assert text.count("error_class=") == 1


def test_render_retry_report_empty() -> None:
    text = render_retry_report(RetryOutcomeReport(community_id="fam-A", groups=()))
    assert "retried_chunks=0 succeeded=0 failed=0 groups=0" in text
    assert "No failed-embedding chunks to retry." in text


def test_render_retry_report_shows_dead_letter_id_for_routed_group() -> None:
    """A failed group whose dead-letter write succeeded renders its id."""
    store = _seeded_mock_store()
    report = ReconciliationService(
        store, _RaisingEmbeddingClient(dimension=64)
    ).retry_failed_chunks("fam-A")
    text = render_retry_report(report)

    dead_letter_id = report.groups[0].dead_letter_id
    assert dead_letter_id is not None
    assert f"dead_letter_id={dead_letter_id}" in text


def test_render_retry_report_omits_dead_letter_id_when_unwritten() -> None:
    """No ``dead_letter_id`` token when the write failed (id is None)."""
    report = RetryOutcomeReport(
        community_id="fam-A",
        groups=(
            RetryGroupOutcome(
                source_message_id="s1",
                chunk_ids=("c-old",),
                succeeded=False,
                error_class="RuntimeError",
                dead_letter_id=None,
            ),
        ),
    )
    text = render_retry_report(report)
    assert "outcome=failed error_class=RuntimeError" in text
    assert "dead_letter_id=" not in text


# ---------------------------------------------------------------------------
# _main --retry operator entrypoint
# ---------------------------------------------------------------------------


def test_main_retry_mode_wires_offline(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`_main --retry` wires parse -> build client -> retry -> render -> print."""
    store = _ClosableMockStore()
    store.save_event_chunks([_chunk("c-old", EmbeddingStatus.FAILED, _at(10))])

    class _FakeSettings:
        def postgres_dsn(self) -> str:
            return "postgresql://unused/in-this-test"

    monkeypatch.setattr("memory_rag.config.Settings", _FakeSettings)
    monkeypatch.setattr("memory_rag.storage.postgres.PostgresDomainStore", lambda _dsn: store)
    monkeypatch.setattr(
        "memory_rag.adapters.embeddings.factory.build_embedding_client",
        lambda _settings: MockEmbeddingClient(dimension=64),
    )

    exit_code = _main(["--community", "fam-A", "--retry"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "community_id=fam-A retried_chunks=1 succeeded=1 failed=0" in out
    chunk = store.get_event_chunk("c-old", community_id="fam-A")
    assert chunk is not None
    assert chunk.embedding_status is EmbeddingStatus.READY


# ---------------------------------------------------------------------------
# PostgresDomainStore (gated)
# ---------------------------------------------------------------------------


pgmark = pytest.mark.skipif(
    PG_DSN is None,
    reason="MEMORY_RAG_PG_TEST_DSN not set; Postgres integration tests skipped.",
)


if PG_DSN is not None:
    import psycopg

    from memory_rag.storage.postgres import PostgresDomainStore


def _truncate(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE indexing_dead_letters, retrieval_hits, queries, "
            "embedding_records, event_chunks, notes, source_messages "
            "RESTART IDENTITY CASCADE"
        )


@pytest.fixture
def pg_store() -> Iterator[PostgresDomainStore]:
    assert PG_DSN is not None
    s = PostgresDomainStore(PG_DSN)
    try:
        _truncate(PG_DSN)
        yield s
    finally:
        s.close()


@pgmark
def test_pg_discover_failed_chunks(pg_store: PostgresDomainStore) -> None:
    pg_store.save_source_message(_source("s1", "fam-A"))
    pg_store.save_note(_note("n1", "s1", "fam-A"))
    pg_store.save_event_chunks(
        [
            _chunk("c-new", EmbeddingStatus.FAILED, _at(12)),
            _chunk("c-old", EmbeddingStatus.FAILED, _at(10)),
            _chunk("c-ready", EmbeddingStatus.READY, _at(11)),
        ]
    )
    report = ReconciliationService(pg_store).discover_failed_chunks("fam-A")
    assert [c.chunk_id for c in report.chunks] == ["c-old", "c-new"]
    assert report.count == 2
    assert "chunk_id=c-old" in render_report(report)


@pgmark
def test_pg_retry_failed_chunks(pg_store: PostgresDomainStore) -> None:
    pg_store.save_source_message(_source("s1", "fam-A"))
    pg_store.save_note(_note("n1", "s1", "fam-A"))
    pg_store.save_event_chunks(
        [
            _chunk("c-old", EmbeddingStatus.FAILED, _at(10)),
            _chunk("c-new", EmbeddingStatus.FAILED, _at(12)),
        ]
    )
    # MockEmbeddingClient at the canonical 3072 dimension to match the
    # pgvector column; no live OpenAI call in the gated suite.
    report = ReconciliationService(pg_store, MockEmbeddingClient()).retry_failed_chunks("fam-A")

    assert report.succeeded_chunks == 2
    assert report.failed_chunks == 0
    for cid in ("c-old", "c-new"):
        chunk = pg_store.get_event_chunk(cid, community_id="fam-A")
        assert chunk is not None
        assert chunk.embedding_status is EmbeddingStatus.READY
    assert pg_store.count_embedding_records_for_source("s1") == 2


@pgmark
def test_pg_retry_exhausted_writes_dead_letter(pg_store: PostgresDomainStore) -> None:
    """An exhausted retry against Postgres leaves an inspectable dead-letter row."""
    pg_store.save_source_message(_source("s1", "fam-A"))
    pg_store.save_note(_note("n1", "s1", "fam-A"))
    pg_store.save_event_chunks([_chunk("c-old", EmbeddingStatus.FAILED, _at(10))])

    report = ReconciliationService(pg_store, _RaisingEmbeddingClient()).retry_failed_chunks("fam-A")

    group = report.groups[0]
    assert group.succeeded is False
    assert group.dead_letter_id is not None

    rows = pg_store.list_indexing_dead_letters("fam-A")
    assert len(rows) == 1
    assert rows[0].dead_letter_id == group.dead_letter_id
    assert rows[0].source_message_id == "s1"
    assert set(rows[0].chunk_ids) == {"c-old"}
    assert rows[0].error_class == "RuntimeError"
    # No state regression: the chunk stays failed.
    chunk = pg_store.get_event_chunk("c-old", community_id="fam-A")
    assert chunk is not None
    assert chunk.embedding_status is EmbeddingStatus.FAILED
