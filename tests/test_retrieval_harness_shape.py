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

import dataclasses
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from memory_rag.adapters.answers.mock import MockChatClient
from memory_rag.adapters.embeddings.mock import MockEmbeddingClient
from memory_rag.core.domain import FallbackMode
from memory_rag.core.domain.models import EventChunk
from memory_rag.core.embeddings.models import EmbeddingStatus
from memory_rag.core.routing import InboundMessage, RouteKind
from memory_rag.eval.retrieval.harness import (
    AggregateMetrics,
    CorpusMessage,
    CostLatencyMetrics,
    CostMetrics,
    GoldQuery,
    GoldSet,
    GroundednessMetrics,
    GroundednessReport,
    HarnessReport,
    LatencyMetrics,
    PerAnswerResult,
    PerLegRecall,
    PerQueryResult,
    RecordingChatClient,
    cost_metrics,
    first_relevant_rank,
    ingest_fixture_corpus,
    is_grounded,
    latency_metrics,
    load_corpus,
    load_gold,
    mrr_at_k,
    recall_at_k,
    run_answer_harness,
    run_harness,
)
from memory_rag.services.domain_service import DomainService
from memory_rag.services.query_service import QueryService
from memory_rag.storage.mock.store import MockDomainStore

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLD_PATH = REPO_ROOT / "eval" / "retrieval" / "gold.json"
CORPUS_PATH = REPO_ROOT / "eval" / "retrieval" / "corpus.jsonl"
OBS_GOLD_PATH = REPO_ROOT / "eval" / "retrieval" / "observability" / "gold.json"
OBS_CORPUS_PATH = REPO_ROOT / "eval" / "retrieval" / "observability" / "corpus.jsonl"

# The two fixture pairs the harness ships: the frozen D-038 baseline set and
# the OP-5 observability set (D-056). Mock-mode shape coverage runs over both —
# the end-to-end run also resolves every gold handle, so a bad handle fails here.
FIXTURE_PAIRS = [
    pytest.param(GOLD_PATH, CORPUS_PATH, id="d038-baseline"),
    pytest.param(OBS_GOLD_PATH, OBS_CORPUS_PATH, id="op5-observability"),
]
CORPUS_PATHS = [
    pytest.param(CORPUS_PATH, id="d038-baseline"),
    pytest.param(OBS_CORPUS_PATH, id="op5-observability"),
]


def _build_chunks_for_source(
    store: MockDomainStore,
) -> Callable[[str], list[EventChunk]]:
    def chunks_for_source(source_message_id: str) -> list[EventChunk]:
        return [
            c
            for c in store._chunks.values()
            if c.source_message_id == source_message_id
            and c.embedding_status is EmbeddingStatus.READY
        ]

    return chunks_for_source


def _run_mock_end_to_end(
    gold_path: Path = GOLD_PATH, corpus_path: Path = CORPUS_PATH
) -> HarnessReport:
    gold = load_gold(gold_path)
    corpus = load_corpus(corpus_path)
    store = MockDomainStore()
    embedding_client = MockEmbeddingClient()
    chunks_for_source = _build_chunks_for_source(store)
    handles = ingest_fixture_corpus(store, chunks_for_source, embedding_client, corpus)

    def lookup(query: str) -> list[float]:
        return embedding_client.embed([query])[0]

    report = run_harness(
        mode="mock",
        store=store,
        gold=gold,
        handles_to_chunk_ids=handles,
        embedding_model_name=embedding_client.model_name,
        query_embedding_lookup=lookup,
        corpus_size=len(corpus),
    )
    # OP-5.2b: drive ``QueryService.answer`` over the same ingested store
    # with the deterministic mock chat provider so the end-to-end shape
    # test also covers the groundedness-proxy plumbing.
    # OP-5.3: wrap the chat client in a ``RecordingChatClient`` so the
    # cost/latency shape can be asserted end-to-end alongside groundedness.
    recorder = RecordingChatClient(MockChatClient())
    query_service = QueryService(store, store, embedding_client, recorder)
    groundedness = run_answer_harness(
        query_service=query_service, gold=gold, chat_recorder=recorder
    )
    cost_latency = CostLatencyMetrics(
        cost=cost_metrics(groundedness.per_answer),
        latency=latency_metrics(report.per_query, groundedness.per_answer),
    )
    return dataclasses.replace(report, groundedness=groundedness, cost_latency=cost_latency)


# --------------------------------------------------------------- shape tests


@pytest.mark.parametrize("gold_path,corpus_path", FIXTURE_PAIRS)
def test_mock_mode_returns_expected_report_shape(gold_path: Path, corpus_path: Path) -> None:
    report = _run_mock_end_to_end(gold_path, corpus_path)
    assert isinstance(report, HarnessReport)
    assert report.mode == "mock"
    assert isinstance(report.corpus_size, int) and report.corpus_size > 0

    gold = load_gold(gold_path)
    assert report.queries == len(gold.queries)

    agg = report.aggregate
    assert isinstance(agg, AggregateMetrics)
    assert isinstance(agg.recall_at_5, float)
    assert isinstance(agg.recall_at_10, float)
    assert isinstance(agg.recall_at_20, float)
    assert isinstance(agg.mrr_at_20, float)
    assert isinstance(agg.hit_rate, float)
    assert 0.0 <= agg.hit_rate <= 1.0
    assert isinstance(agg.empty_rate, float)
    assert 0.0 <= agg.empty_rate <= 1.0
    assert isinstance(agg.per_leg_recall_at_20, PerLegRecall)
    assert isinstance(agg.per_leg_recall_at_20.dense, float)
    assert isinstance(agg.per_leg_recall_at_20.sparse, float)
    assert isinstance(agg.per_leg_recall_at_20.fused, float)


@pytest.mark.parametrize("gold_path,corpus_path", FIXTURE_PAIRS)
def test_mock_mode_includes_groundedness_proxy_shape(gold_path: Path, corpus_path: Path) -> None:
    """OP-5.2b: report carries a ``GroundednessReport`` after the CLI helper
    runs the answer harness. Shape-only — no quality-value assertions
    (``[[feedback_harness_is_inspection_not_gate]]``)."""
    report = _run_mock_end_to_end(gold_path, corpus_path)
    assert isinstance(report.groundedness, GroundednessReport)

    g = report.groundedness.aggregate
    assert isinstance(g, GroundednessMetrics)
    assert isinstance(g.groundedness_rate, float)
    assert 0.0 <= g.groundedness_rate <= 1.0
    assert isinstance(g.fallback_mode_counts, dict)
    for mode_value, count in g.fallback_mode_counts.items():
        assert isinstance(mode_value, str) and mode_value
        assert isinstance(count, int) and count >= 0
    # The per-query breakdown sums to the total number of gold queries so an
    # operator can read the full distribution without arithmetic.
    assert sum(g.fallback_mode_counts.values()) == report.queries

    per_answer = report.groundedness.per_answer
    assert len(per_answer) == report.queries
    for row in per_answer:
        assert isinstance(row, PerAnswerResult)
        assert isinstance(row.query, str) and row.query
        assert isinstance(row.community_id, str) and row.community_id
        assert isinstance(row.answerable, bool)
        assert isinstance(row.fallback_mode, str) and row.fallback_mode
        assert isinstance(row.context_chunk_count, int)
        assert row.context_chunk_count >= 0
        assert isinstance(row.grounded, bool)
        # Per-row ``grounded`` is the documented projection of
        # ``fallback_mode`` via ``is_grounded`` — they must agree.
        assert row.grounded is is_grounded(FallbackMode(row.fallback_mode))


@pytest.mark.parametrize("gold_path,corpus_path", FIXTURE_PAIRS)
def test_per_query_shape_includes_diagnostic_rank_fields(
    gold_path: Path, corpus_path: Path
) -> None:
    report = _run_mock_end_to_end(gold_path, corpus_path)
    assert report.per_query, "expected at least one per-query row"
    for row in report.per_query:
        assert isinstance(row, PerQueryResult)
        assert isinstance(row.query, str)
        assert isinstance(row.community_id, str) and row.community_id
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
        # OP-5.3: per-row wall-clock retrieval latency is populated by
        # ``run_harness``. Shape-only — no upper bound; wall-clock is
        # non-deterministic and machine-dependent.
        assert isinstance(row.retrieval_latency_ms, float)
        assert row.retrieval_latency_ms >= 0.0


@pytest.mark.parametrize("gold_path,corpus_path", FIXTURE_PAIRS)
def test_mock_mode_includes_cost_and_latency_shape(gold_path: Path, corpus_path: Path) -> None:
    """OP-5.3 / D-059: report carries a ``CostLatencyMetrics`` after the CLI
    helper runs the cost/latency aggregation. Shape-only — no quality-value
    or upper-bound assertions (``[[feedback_harness_is_inspection_not_gate]]``).
    """
    report = _run_mock_end_to_end(gold_path, corpus_path)
    assert isinstance(report.cost_latency, CostLatencyMetrics)

    c = report.cost_latency.cost
    assert isinstance(c, CostMetrics)
    assert isinstance(c.total_prompt_tokens, int) and c.total_prompt_tokens >= 0
    assert isinstance(c.total_completion_tokens, int) and c.total_completion_tokens >= 0
    assert isinstance(c.total_tokens, int) and c.total_tokens >= 0
    assert c.total_tokens == c.total_prompt_tokens + c.total_completion_tokens
    assert isinstance(c.answer_calls_with_tokens, int) and c.answer_calls_with_tokens >= 0
    assert c.answer_calls_with_tokens <= report.queries
    assert isinstance(c.mean_total_tokens_per_call, float)
    assert c.mean_total_tokens_per_call >= 0.0

    lat = report.cost_latency.latency
    assert isinstance(lat, LatencyMetrics)
    for value in (
        lat.mean_retrieval_ms,
        lat.p50_retrieval_ms,
        lat.max_retrieval_ms,
        lat.mean_answer_ms,
        lat.p50_answer_ms,
        lat.max_answer_ms,
    ):
        assert isinstance(value, float) and value >= 0.0
    # Distributional sanity: max ≥ mean and max ≥ p50, no upper bound.
    assert lat.max_retrieval_ms >= lat.mean_retrieval_ms
    assert lat.max_retrieval_ms >= lat.p50_retrieval_ms
    assert lat.max_answer_ms >= lat.mean_answer_ms
    assert lat.max_answer_ms >= lat.p50_answer_ms

    # Per-row answer-path measurements live on PerAnswerResult.
    assert report.groundedness is not None
    for row in report.groundedness.per_answer:
        assert isinstance(row.answer_latency_ms, float)
        assert row.answer_latency_ms >= 0.0
        assert isinstance(row.prompt_tokens, int) and row.prompt_tokens >= 0
        assert isinstance(row.completion_tokens, int) and row.completion_tokens >= 0


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
    store = MockDomainStore()
    embedding_client = MockEmbeddingClient()
    corpus = (
        CorpusMessage(
            external_message_id="t-1",
            community_id="fam-x",
            author_user_id="u-1",
            raw_text="2026-05-15\n- first event line\n- second event line",
        ),
    )
    chunks_for_source = _build_chunks_for_source(store)
    handles = ingest_fixture_corpus(store, chunks_for_source, embedding_client, corpus)
    assert set(handles.keys()) == {"t-1#0", "t-1#1"}
    for chunk_id in handles.values():
        assert store.get_event_chunk(chunk_id, community_id="fam-x") is not None


@pytest.mark.parametrize("corpus_path", CORPUS_PATHS)
def test_mock_corpus_embeddings_have_honest_provenance(corpus_path: Path) -> None:
    store = MockDomainStore()
    embedding_client = MockEmbeddingClient()
    corpus = load_corpus(corpus_path)
    chunks_for_source = _build_chunks_for_source(store)
    ingest_fixture_corpus(store, chunks_for_source, embedding_client, corpus)
    assert store._embeddings, "expected at least one persisted embedding"
    for record in store._embeddings.values():
        assert record.model_name == "mock"


def test_run_harness_raises_when_handle_unknown() -> None:
    store = MockDomainStore()
    embedding_client = MockEmbeddingClient()
    corpus = (
        CorpusMessage(
            external_message_id="t-1",
            community_id="fam-x",
            author_user_id="u-1",
            raw_text="2026-05-15\n- single event",
        ),
    )
    chunks_for_source = _build_chunks_for_source(store)
    handles = ingest_fixture_corpus(store, chunks_for_source, embedding_client, corpus)
    gold = GoldSet(
        queries=(GoldQuery(community_id="fam-x", query="anything", expected_handles=("t-9#7",)),)
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
    env = {k: v for k, v in os.environ.items() if k != "MEMORY_RAG_PG_TEST_DSN"}
    result = subprocess.run(
        [sys.executable, "-c", "import memory_rag.eval.retrieval.__main__"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    from memory_rag.eval.retrieval.__main__ import main

    with pytest.raises(RuntimeError, match="MEMORY_RAG_PG_TEST_DSN is required"):
        main(["--mode", "postgres"])


# -------------------------------------------------------------- smoke: ingest


@pytest.mark.parametrize("corpus_path", CORPUS_PATHS)
def test_domain_service_drives_corpus_ingestion(corpus_path: Path) -> None:
    """Sanity: ``DomainService.ingest`` succeeds on every fixture corpus message."""
    store = MockDomainStore()
    embedding_client = MockEmbeddingClient()
    service = DomainService(store, embedding_client=embedding_client)
    received_at = datetime.now(tz=UTC)
    corpus = load_corpus(corpus_path)
    for cm in corpus:
        inbound = InboundMessage(
            external_message_id=cm.external_message_id,
            external_chat_id=cm.community_id,
            external_user_id=cm.author_user_id,
            community_id=cm.community_id,
            text=cm.raw_text,
            payload=cm.raw_text,
            route=RouteKind.NOTE,
            received_at=received_at,
            route_source="command",
        )
        result = service.ingest(inbound)
        assert result.events_count > 0, f"{cm.external_message_id} produced no events"
