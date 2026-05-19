"""CLI entrypoint for the retrieval-quality harness (D-038).

Operator invocation patterns:

- Mock mode (no env needed)::

      uv run python -m memory_rag.eval.retrieval --mode mock

  Useful for a quick local smoke; the canonical mock coverage is
  ``tests/test_retrieval_harness_shape.py`` under ``make check``.

- Postgres mode (operator baseline measurement)::

      MEMORY_RAG_PG_TEST_DSN=postgresql://... \\
      EMBEDDING_BACKEND=openai \\
      OPENAI_API_KEY=... \\
      uv run python -m memory_rag.eval.retrieval --mode postgres --json

  Truncates the four ingest tables on the connected DSN, re-ingests
  ``eval/retrieval/corpus.jsonl`` through the canonical ``DomainService``
  path (so corpus chunks are embedded by the configured backend; under
  ``EMBEDDING_BACKEND=openai`` this makes live OpenAI embedding calls,
  which is acceptable because the operator chose this deliberately —
  see RUNBOOK), then runs the gold queries against
  ``SearchRepository.dense_candidates`` + ``sparse_candidates`` + service
  RRF using the pinned query embeddings from
  ``eval/retrieval/embeddings_cache.json``.

The script never gates: exit code is ``0`` on success regardless of the
observed metrics (``[[feedback_harness_is_inspection_not_gate]]``).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from memory_rag.adapters.answers.mock import MockChatClient
from memory_rag.adapters.embeddings.mock import MockEmbeddingClient
from memory_rag.core.domain.models import EventChunk
from memory_rag.core.embeddings.models import EmbeddingStatus
from memory_rag.eval.retrieval.harness import (
    DEFAULT_CANDIDATE_K,
    DEFAULT_TOP_K,
    HarnessReport,
    ingest_fixture_corpus,
    load_corpus,
    load_gold,
    load_query_embeddings_cache,
    run_answer_harness,
    run_harness,
)
from memory_rag.services.query_service import QueryService

DEFAULT_GOLD = Path("eval/retrieval/gold.json")
DEFAULT_CORPUS = Path("eval/retrieval/corpus.jsonl")
DEFAULT_CACHE = Path("eval/retrieval/embeddings_cache.json")

# Mirrors ``tests/test_search_repository_postgres.py::_truncate``. Kept in
# the harness so a single ritual covers the four ingest tables the
# fixture corpus writes to.
# Postgres-mode ritual: the answer half (``run_answer_harness``) drives
# ``QueryService.answer`` which writes ``queries`` / ``retrieval_hits`` /
# ``answer_traces`` rows, so the eval DB must start clean from those too.
# Order is irrelevant under ``CASCADE`` but is grouped by direction (ingest
# tables first, answer-path trace tables second) for readability.
_TRUNCATE_TABLES = (
    "embedding_records",
    "event_chunks",
    "notes",
    "source_messages",
    "answer_traces",
    "retrieval_hits",
    "queries",
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m memory_rag.eval.retrieval")
    p.add_argument("--mode", required=True, choices=["mock", "postgres"])
    p.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    p.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    p.add_argument("--embeddings-cache", type=Path, default=DEFAULT_CACHE)
    p.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    p.add_argument("--candidate-k", type=int, default=DEFAULT_CANDIDATE_K)
    p.add_argument(
        "--json",
        dest="emit_json",
        action="store_true",
        help="Emit the full HarnessReport as JSON to stdout.",
    )
    return p


def _run_mock(
    *,
    gold_path: Path,
    corpus_path: Path,
    top_k: int,
    candidate_k: int,
) -> HarnessReport:
    from memory_rag.storage.mock.store import MockDomainStore

    gold = load_gold(gold_path)
    corpus = load_corpus(corpus_path)
    store = MockDomainStore()
    embedding_client = MockEmbeddingClient()

    def chunks_for_source(source_message_id: str) -> list[EventChunk]:
        return [
            c
            for c in store._chunks.values()
            if c.source_message_id == source_message_id
            and c.embedding_status is EmbeddingStatus.READY
        ]

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
        top_k=top_k,
        candidate_k=candidate_k,
        corpus_size=len(corpus),
    )
    # OP-5.2b groundedness proxy: drive ``QueryService.answer`` over the
    # same ingested store with the deterministic mock chat provider. The
    # metric is a fallback-derived proxy, inspection only.
    query_service = QueryService(
        store, store, embedding_client, MockChatClient(), top_k=top_k, candidate_k=candidate_k
    )
    groundedness = run_answer_harness(query_service=query_service, gold=gold)
    return dataclasses.replace(report, groundedness=groundedness)


def _run_postgres(
    *,
    gold_path: Path,
    corpus_path: Path,
    cache_path: Path,
    top_k: int,
    candidate_k: int,
) -> HarnessReport:
    dsn = os.environ.get("MEMORY_RAG_PG_TEST_DSN")
    if not dsn:
        raise RuntimeError(
            "MEMORY_RAG_PG_TEST_DSN is required for --mode postgres; "
            "point it at a dedicated eval database (the harness truncates "
            "embedding_records, event_chunks, notes, source_messages)."
        )

    import psycopg

    from memory_rag.adapters.answers.factory import build_chat_client
    from memory_rag.adapters.embeddings.factory import build_embedding_client
    from memory_rag.config import Settings
    from memory_rag.storage.postgres import PostgresDomainStore

    settings = Settings()
    embedding_client = build_embedding_client(settings)
    chat_client = build_chat_client(settings)
    expected_model_name = embedding_client.model_name
    expected_dimension = embedding_client.dimension

    gold = load_gold(gold_path)
    corpus = load_corpus(corpus_path)
    cache = load_query_embeddings_cache(
        cache_path,
        expected_model_name=expected_model_name,
        expected_dimension=expected_dimension,
    )

    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE " + ", ".join(_TRUNCATE_TABLES) + " RESTART IDENTITY CASCADE")

    store = PostgresDomainStore(dsn)
    try:

        def chunks_for_source(source_message_id: str) -> list[EventChunk]:
            with psycopg.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT chunk_id, note_id, source_message_id, community_id, "
                    "       author_user_id, note_date, event_index, chunk_text, "
                    "       created_at, embedding_status "
                    "  FROM event_chunks "
                    " WHERE source_message_id = %s "
                    " ORDER BY event_index",
                    (source_message_id,),
                )
                rows = cur.fetchall()
            return [
                EventChunk(
                    chunk_id=row[0],
                    note_id=row[1],
                    source_message_id=row[2],
                    community_id=row[3],
                    author_user_id=row[4],
                    note_date=row[5],
                    event_index=row[6],
                    chunk_text=row[7],
                    created_at=row[8],
                    embedding_status=EmbeddingStatus(row[9]),
                )
                for row in rows
            ]

        handles = ingest_fixture_corpus(store, chunks_for_source, embedding_client, corpus)

        def lookup(query: str) -> list[float]:
            if query not in cache:
                raise KeyError(
                    f"query {query!r} is not in the embeddings cache; "
                    f"regenerate via "
                    f"`uv run python -m memory_rag.eval.retrieval.regenerate_embeddings`"
                )
            return cache[query]

        report = run_harness(
            mode="postgres",
            store=store,
            gold=gold,
            handles_to_chunk_ids=handles,
            embedding_model_name=expected_model_name,
            query_embedding_lookup=lookup,
            top_k=top_k,
            candidate_k=candidate_k,
            corpus_size=len(corpus),
        )
        # OP-5.2b groundedness proxy: drive ``QueryService.answer`` over the
        # same ingested Postgres store with the operator-selected chat client
        # (``CHAT_BACKEND`` env, defaulting to mock — no live API is forced).
        query_service = QueryService(
            store, store, embedding_client, chat_client, top_k=top_k, candidate_k=candidate_k
        )
        groundedness = run_answer_harness(query_service=query_service, gold=gold)
        return dataclasses.replace(report, groundedness=groundedness)
    finally:
        store.close()


def _format_human(report: HarnessReport) -> str:
    a = report.aggregate
    pl = a.per_leg_recall_at_20
    lines = [
        f"mode={report.mode}  queries={report.queries}  corpus_size={report.corpus_size}",
        "",
        "Aggregate (D-025 baseline contour — observed, inspection only):",
        f"  recall@5  = {a.recall_at_5:.3f}",
        f"  recall@10 = {a.recall_at_10:.3f}",
        f"  recall@20 = {a.recall_at_20:.3f}",
        f"  mrr@20    = {a.mrr_at_20:.3f}",
        f"  hit_rate   = {a.hit_rate:.3f}  (denominator: non-empty-gold queries only)",
        f"  empty_rate = {a.empty_rate:.3f}  (denominator: all queries)",
        "  per_leg_recall@20:",
        f"    dense  = {pl.dense:.3f}",
        f"    sparse = {pl.sparse:.3f}",
        f"    fused  = {pl.fused:.3f}",
    ]
    if report.groundedness is not None:
        g = report.groundedness.aggregate
        # Title carries the "proxy" and "fallback-derived" words verbatim so the
        # rate cannot be misread as a direct factuality or citation-coverage
        # score (OP-5.2b / D-058).
        lines.extend(
            [
                "",
                "Groundedness proxy (answer-path, fallback-derived, inspection only):",
                f"  groundedness_rate = {g.groundedness_rate:.3f}  "
                f"(proxy: fallback-derived; denominator: non-empty-gold queries only)",
                "  fallback_mode_counts (over all queries):",
            ]
        )
        # Sort modes alphabetically so the output is stable run-to-run.
        for mode in sorted(g.fallback_mode_counts):
            lines.append(f"    {mode:<22s} = {g.fallback_mode_counts[mode]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.mode == "mock":
        report = _run_mock(
            gold_path=args.gold,
            corpus_path=args.corpus,
            top_k=args.top_k,
            candidate_k=args.candidate_k,
        )
    else:
        report = _run_postgres(
            gold_path=args.gold,
            corpus_path=args.corpus,
            cache_path=args.embeddings_cache,
            top_k=args.top_k,
            candidate_k=args.candidate_k,
        )

    if args.emit_json:
        print(json.dumps(asdict(report), indent=2, default=str))
    else:
        print(_format_human(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
