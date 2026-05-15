"""Mock-mode shape sanity check for the D-038 retrieval harness.

Runs under ``make check``. Asserts only the report's metric shape and
the consistency between ``first_relevant_rank_in_fused`` and
``reciprocal_rank_in_fused``. **No quality-value assertions.**

Per ``[[feedback_harness_is_inspection_not_gate]]``: the mock mode's
purpose here is to confirm the plumbing — gold load, corpus load,
fixture ingest, handle resolution, per-leg retrieval, RRF, metric
aggregation — produces the expected shape end-to-end. Quality is
measured by the Postgres-mode operator-run baseline, not by this test.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from diary_rag.adapters.embeddings.mock import MockEmbeddingClient
from diary_rag.core.diary.models import EventChunk
from diary_rag.core.embeddings.models import EmbeddingStatus
from diary_rag.core.routing import InboundMessage, RouteKind
from diary_rag.eval.retrieval.harness import (
    AggregateMetrics,
    CorpusMessage,
    GoldQuery,
    GoldSet,
    HarnessReport,
    PerLegRecall,
    PerQueryResult,
    first_relevant_rank,
    ingest_fixture_corpus,
    load_corpus,
    load_gold,
    mrr_at_k,
    recall_at_k,
    run_harness,
)
from diary_rag.services.diary_service import DiaryService
from diary_rag.storage.mock.store import MockDiaryStore

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLD_PATH = REPO_ROOT / "eval" / "retrieval" / "gold.json"
CORPUS_PATH = REPO_ROOT / "eval" / "retrieval" / "corpus.jsonl"


def _build_chunks_for_source(
    store: MockDiaryStore,
) -> Callable[[str], list[EventChunk]]:
    def chunks_for_source(source_message_id: str) -> list[EventChunk]:
        return [
            c
            for c in store._chunks.values()
            if c.source_message_id == source_message_id
            and c.embedding_status is EmbeddingStatus.READY
        ]

    return chunks_for_source


def _run_mock_end_to_end() -> HarnessReport:
    gold = load_gold(GOLD_PATH)
    corpus = load_corpus(CORPUS_PATH)
    store = MockDiaryStore()
    embedding_client = MockEmbeddingClient()
    chunks_for_source = _build_chunks_for_source(store)
    handles = ingest_fixture_corpus(store, chunks_for_source, embedding_client, corpus)

    def lookup(query: str) -> list[float]:
        return embedding_client.embed([query])[0]

    return run_harness(
        mode="mock",
        store=store,
        gold=gold,
        handles_to_chunk_ids=handles,
        embedding_model_name=embedding_client.model_name,
        query_embedding_lookup=lookup,
        corpus_size=len(corpus),
    )


# --------------------------------------------------------------- shape tests


def test_mock_mode_returns_expected_report_shape() -> None:
    report = _run_mock_end_to_end()
    assert isinstance(report, HarnessReport)
    assert report.mode == "mock"
    assert isinstance(report.corpus_size, int) and report.corpus_size > 0

    gold = load_gold(GOLD_PATH)
    assert report.queries == len(gold.queries)

    agg = report.aggregate
    assert isinstance(agg, AggregateMetrics)
    assert isinstance(agg.recall_at_5, float)
    assert isinstance(agg.recall_at_10, float)
    assert isinstance(agg.recall_at_20, float)
    assert isinstance(agg.mrr_at_20, float)
    assert isinstance(agg.per_leg_recall_at_20, PerLegRecall)
    assert isinstance(agg.per_leg_recall_at_20.dense, float)
    assert isinstance(agg.per_leg_recall_at_20.sparse, float)
    assert isinstance(agg.per_leg_recall_at_20.fused, float)


def test_per_query_shape_includes_diagnostic_rank_fields() -> None:
    report = _run_mock_end_to_end()
    assert report.per_query, "expected at least one per-query row"
    for row in report.per_query:
        assert isinstance(row, PerQueryResult)
        assert isinstance(row.query, str)
        assert isinstance(row.family_id, str) and row.family_id
        assert isinstance(row.expected_chunk_ids, tuple)
        assert isinstance(row.dense_top_k_ids, tuple)
        assert isinstance(row.sparse_top_k_ids, tuple)
        assert isinstance(row.fused_top_k_ids, tuple)
        for rank in (
            row.first_relevant_rank_in_dense,
            row.first_relevant_rank_in_sparse,
            row.first_relevant_rank_in_fused,
        ):
            assert rank is None or isinstance(rank, int)
            if isinstance(rank, int):
                assert rank >= 1
        assert isinstance(row.reciprocal_rank_in_fused, float)
        expected_rr = (
            1.0 / row.first_relevant_rank_in_fused
            if row.first_relevant_rank_in_fused is not None
            else 0.0
        )
        assert row.reciprocal_rank_in_fused == pytest.approx(expected_rr)
        assert isinstance(row.recall_at_5, float)
        assert isinstance(row.recall_at_10, float)
        assert isinstance(row.recall_at_20, float)


# --------------------------------------------------------------- pure metric tests


def test_recall_at_k_pure() -> None:
    assert recall_at_k({"a", "b"}, ["a", "c", "b"], 3) == pytest.approx(1.0)
    assert recall_at_k({"a", "b"}, ["a", "c", "b"], 1) == pytest.approx(0.5)
    # k=10 covers the new recall@10 aggregate slot.
    assert recall_at_k({"a", "b"}, ["a", "c", "b"], 10) == pytest.approx(1.0)
    assert recall_at_k({"a", "b"}, ["c", "d", "e"], 3) == 0.0
    # Empty expected: convention is 0.0 to keep aggregation arithmetic honest.
    assert recall_at_k(set(), ["a", "b"], 3) == 0.0
    assert recall_at_k({"a"}, ["a"], 0) == 0.0


def test_mrr_at_k_pure() -> None:
    assert mrr_at_k({"a"}, ["a", "b", "c"], 3) == pytest.approx(1.0)
    assert mrr_at_k({"b"}, ["a", "b", "c"], 3) == pytest.approx(0.5)
    # Multi-hit takes the first.
    assert mrr_at_k({"a", "c"}, ["b", "a", "c"], 3) == pytest.approx(0.5)
    assert mrr_at_k({"z"}, ["a", "b", "c"], 3) == 0.0
    # Truncation: first hit lies past k.
    assert mrr_at_k({"c"}, ["a", "b", "c"], 2) == 0.0


def test_first_relevant_rank_pure() -> None:
    assert first_relevant_rank({"a"}, ["x", "y", "a", "z"], 5) == 3
    assert first_relevant_rank({"a"}, ["x", "y", "z"], 5) is None
    assert first_relevant_rank({"a"}, ["x", "y", "a"], 2) is None
    assert first_relevant_rank(set(), ["a"], 5) is None


# ------------------------------------------------------------- handle resolution


def test_ingest_fixture_corpus_resolves_handles() -> None:
    """``event_index`` is the 0-based EventChunk ordinal within the source message."""
    store = MockDiaryStore()
    embedding_client = MockEmbeddingClient()
    corpus = (
        CorpusMessage(
            external_message_id="t-1",
            family_id="fam-x",
            author_user_id="u-1",
            raw_text="2026-05-15\n- first event line\n- second event line",
        ),
    )
    chunks_for_source = _build_chunks_for_source(store)
    handles = ingest_fixture_corpus(store, chunks_for_source, embedding_client, corpus)
    assert set(handles.keys()) == {"t-1#0", "t-1#1"}
    for chunk_id in handles.values():
        assert store.get_event_chunk(chunk_id) is not None


def test_mock_corpus_embeddings_have_honest_provenance() -> None:
    store = MockDiaryStore()
    embedding_client = MockEmbeddingClient()
    corpus = load_corpus(CORPUS_PATH)
    chunks_for_source = _build_chunks_for_source(store)
    ingest_fixture_corpus(store, chunks_for_source, embedding_client, corpus)
    assert store._embeddings, "expected at least one persisted embedding"
    for record in store._embeddings.values():
        assert record.model_name == "mock"


def test_run_harness_raises_when_handle_unknown() -> None:
    store = MockDiaryStore()
    embedding_client = MockEmbeddingClient()
    corpus = (
        CorpusMessage(
            external_message_id="t-1",
            family_id="fam-x",
            author_user_id="u-1",
            raw_text="2026-05-15\n- single event",
        ),
    )
    chunks_for_source = _build_chunks_for_source(store)
    handles = ingest_fixture_corpus(store, chunks_for_source, embedding_client, corpus)
    gold = GoldSet(
        queries=(GoldQuery(family_id="fam-x", query="anything", expected_handles=("t-9#7",)),)
    )

    def lookup(query: str) -> list[float]:
        return embedding_client.embed([query])[0]

    with pytest.raises(KeyError, match="not found in ingested corpus"):
        run_harness(
            mode="mock",
            store=store,
            gold=gold,
            handles_to_chunk_ids=handles,
            embedding_model_name=embedding_client.model_name,
            query_embedding_lookup=lookup,
            corpus_size=1,
        )


# ------------------------------------------------------------ CLI gate tests


def test_postgres_mode_imports_cleanly_without_dsn() -> None:
    # Importing the CLI module must not require a DSN; only --mode postgres
    # at execution time needs it. Use a fresh subprocess so the import is
    # isolated from any DSN already set in this pytest run.
    env = {k: v for k, v in os.environ.items() if k != "DIARY_RAG_PG_TEST_DSN"}
    result = subprocess.run(
        [sys.executable, "-c", "import diary_rag.eval.retrieval.__main__"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    from diary_rag.eval.retrieval.__main__ import main

    with pytest.raises(RuntimeError, match="DIARY_RAG_PG_TEST_DSN is required"):
        main(["--mode", "postgres"])


# -------------------------------------------------------------- smoke: ingest


def test_diary_service_drives_corpus_ingestion() -> None:
    """Sanity: ``DiaryService.ingest`` succeeds on every fixture corpus message."""
    store = MockDiaryStore()
    embedding_client = MockEmbeddingClient()
    service = DiaryService(store, embedding_client=embedding_client)
    received_at = datetime.now(tz=UTC)
    corpus = load_corpus(CORPUS_PATH)
    for cm in corpus:
        inbound = InboundMessage(
            external_message_id=cm.external_message_id,
            external_chat_id=cm.family_id,
            external_user_id=cm.author_user_id,
            text=cm.raw_text,
            payload=cm.raw_text,
            route=RouteKind.ENTRY,
            received_at=received_at,
            route_source="command",
        )
        result = service.ingest(inbound)
        assert result.events_count > 0, f"{cm.external_message_id} produced no events"
