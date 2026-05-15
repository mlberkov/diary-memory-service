"""Retrieval-quality inspection harness against the D-025 baseline (D-038).

Pure data + pure metric functions plus the orchestration that drives
``DiaryService.ingest`` on a fixture corpus and then calls
``SearchRepository.dense_candidates`` / ``sparse_candidates`` followed by
``reciprocal_rank_fusion`` exactly the way ``QueryService`` does. The
harness does **not** route through ``QueryService.answer`` because
measuring retrieval does not need the chat-client / ``AnswerTrace`` path
attached.

Handle contract — restated everywhere it matters: every entry in
``GoldQuery.expected_handles`` and in the returned
``handles_to_chunk_ids`` map has the form
``f"{external_message_id}#{event_index}"``, where ``event_index`` is the
**0-based ordinal of the produced ``EventChunk`` within the source
message after canonical ``parse_diary_entry`` + chunking by
``DiaryService.ingest``**. It is NOT a business event id, NOT a Telegram
message id, NOT any external domain identifier. The handle only exists
because ``chunk_id`` is uuid4 at ingest time and so cannot be pinned in
``eval/retrieval/gold.json`` directly.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from diary_rag.core.diary.models import EventChunk
from diary_rag.core.embeddings import EmbeddingClient
from diary_rag.core.routing import InboundMessage, RouteKind
from diary_rag.services.diary_service import DiaryService
from diary_rag.services.retrieval import reciprocal_rank_fusion
from diary_rag.storage.repository import DiaryRepository
from diary_rag.storage.search_repository import SearchRepository

DEFAULT_TOP_K = 5
DEFAULT_CANDIDATE_K = 20


@dataclass(frozen=True, slots=True)
class GoldQuery:
    """A single hand-curated query with its expected chunks.

    ``expected_handles`` entries are ``f"{external_message_id}#{event_index}"``
    handles — ``event_index`` is the 0-based EventChunk ordinal within the
    parsed source message (see the module docstring). The harness resolves
    each handle to a live uuid4 ``chunk_id`` after ingest.
    """

    family_id: str
    query: str
    expected_handles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GoldSet:
    queries: tuple[GoldQuery, ...]


@dataclass(frozen=True, slots=True)
class CorpusMessage:
    """A single fixture raw source message for re-ingestion.

    ``raw_text`` must be a valid diary payload — first line is an ISO
    date (``YYYY-MM-DD``), subsequent lines are events. Each event line
    becomes one ``EventChunk`` (I-5).
    """

    external_message_id: str
    family_id: str
    author_user_id: str
    raw_text: str


@dataclass(frozen=True, slots=True)
class PerLegRecall:
    dense: float
    sparse: float
    fused: float


@dataclass(frozen=True, slots=True)
class AggregateMetrics:
    recall_at_5: float
    recall_at_10: float
    recall_at_20: float
    mrr_at_20: float
    per_leg_recall_at_20: PerLegRecall


@dataclass(frozen=True, slots=True)
class PerQueryResult:
    """One row per gold query in the harness report.

    ``first_relevant_rank_in_{dense,sparse,fused}`` are diagnostic 1-based
    ranks within each leg's own top-``candidate_k`` list (``None`` when no
    expected chunk appears). ``reciprocal_rank_in_fused`` is the explicit
    ``mrr@20`` numerator at per-query granularity — equals
    ``1.0 / first_relevant_rank_in_fused`` on a hit, ``0.0`` otherwise.
    """

    query: str
    family_id: str
    expected_chunk_ids: tuple[str, ...]
    dense_top_k_ids: tuple[str, ...]
    sparse_top_k_ids: tuple[str, ...]
    fused_top_k_ids: tuple[str, ...]
    first_relevant_rank_in_dense: int | None
    first_relevant_rank_in_sparse: int | None
    first_relevant_rank_in_fused: int | None
    reciprocal_rank_in_fused: float
    recall_at_5: float
    recall_at_10: float
    recall_at_20: float


@dataclass(frozen=True, slots=True)
class HarnessReport:
    mode: str  # "mock" | "postgres"
    corpus_size: int
    queries: int
    aggregate: AggregateMetrics
    per_query: tuple[PerQueryResult, ...]


# --------------------------------------------------------------------- IO


def load_gold(path: Path) -> GoldSet:
    """Read ``gold.json``. Schema: see ``eval/retrieval/gold.json``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    default_family = data.get("family_id_default", "")
    queries: list[GoldQuery] = []
    for raw in data["queries"]:
        family_id = raw.get("family_id", default_family)
        if not family_id:
            raise ValueError(f"gold query missing family_id (no family_id_default either): {raw!r}")
        queries.append(
            GoldQuery(
                family_id=family_id,
                query=raw["query"],
                expected_handles=tuple(raw.get("expected_handles", [])),
            )
        )
    return GoldSet(queries=tuple(queries))


def load_corpus(path: Path) -> tuple[CorpusMessage, ...]:
    """Read ``corpus.jsonl`` — one raw source message per line."""
    messages: list[CorpusMessage] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        obj = json.loads(line)
        messages.append(
            CorpusMessage(
                external_message_id=obj["external_message_id"],
                family_id=obj["family_id"],
                author_user_id=obj["author_user_id"],
                raw_text=obj["raw_text"],
            )
        )
        if "external_message_id" not in obj:
            raise ValueError(f"corpus line {line_no}: missing external_message_id")
    return tuple(messages)


def load_query_embeddings_cache(
    path: Path,
    *,
    expected_model_name: str,
    expected_dimension: int,
) -> dict[str, list[float]]:
    """Read the pinned-query-embeddings cache.

    Aborts loudly when ``model_name`` or ``dimension`` disagrees with the
    embedding contour the harness will use against the store — D-025's
    dense leg filters by ``model_name``, so a silent mismatch would
    return zero hits and look like "dense found nothing" when really the
    cache is wrong.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    model_name = data.get("model_name")
    dimension = data.get("dimension")
    if model_name != expected_model_name:
        raise ValueError(
            f"embeddings cache model_name={model_name!r} does not match "
            f"expected {expected_model_name!r}; regenerate the cache"
        )
    if dimension != expected_dimension:
        raise ValueError(
            f"embeddings cache dimension={dimension} does not match "
            f"expected {expected_dimension}; regenerate the cache"
        )
    embeddings = data.get("embeddings", {})
    return {str(k): [float(x) for x in v] for k, v in embeddings.items()}


# ------------------------------------------------------------------ ingest


def ingest_fixture_corpus(
    repo: DiaryRepository,
    chunks_for_source: Callable[[str], list[EventChunk]],
    embedding_client: EmbeddingClient,
    corpus: tuple[CorpusMessage, ...],
) -> dict[str, str]:
    """Drive ``DiaryService.ingest`` over the corpus and build the handle map.

    ``chunks_for_source`` is a small backend-specific lookup the caller
    passes in: ``MockDiaryStore`` reads its private chunks dict;
    ``PostgresDiaryStore`` uses a separate psycopg query in the CLI. The
    Protocol does not surface "list chunks for source" today; adding it
    is wider than this packet's scope, so the harness wires the lookup
    explicitly.

    The function's docstring restates the handle contract: returned keys
    are ``f"{external_message_id}#{event_index}"`` where ``event_index``
    is the 0-based ordinal of the produced ``EventChunk`` within the
    parsed source message after ``DiaryService.ingest`` chunked it.
    """
    service = DiaryService(repo, embedding_client=embedding_client)
    handles: dict[str, str] = {}
    received_at = datetime.now(tz=UTC)
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
        source_message_id = result.source_message_id
        chunks = chunks_for_source(source_message_id)
        if not chunks:
            raise RuntimeError(
                f"corpus message {cm.external_message_id!r} produced no chunks — "
                f"check raw_text is a parseable diary payload (first line ISO date)"
            )
        ordered = sorted(chunks, key=lambda c: c.event_index)
        for chunk in ordered:
            handles[f"{cm.external_message_id}#{chunk.event_index}"] = chunk.chunk_id
    return handles


# ------------------------------------------------------------------ metrics


def recall_at_k(expected: set[str], returned: Sequence[str], k: int) -> float:
    """Fraction of ``expected`` chunks present in the first ``k`` of ``returned``.

    Empty ``expected`` returns ``0.0`` — there is nothing to recall; the
    metric is undefined but ``0.0`` keeps aggregation arithmetic honest
    without raising. Callers exclude empty-expected queries from the
    aggregate if they want a different convention.
    """
    if k <= 0:
        return 0.0
    if not expected:
        return 0.0
    window = list(returned)[:k]
    hits = sum(1 for cid in window if cid in expected)
    return hits / len(expected)


def first_relevant_rank(expected: set[str], returned: Sequence[str], k: int) -> int | None:
    """1-based rank of the first expected chunk within the first ``k``; else ``None``."""
    if k <= 0 or not expected:
        return None
    for rank, cid in enumerate(list(returned)[:k], start=1):
        if cid in expected:
            return rank
    return None


def mrr_at_k(expected: set[str], returned: Sequence[str], k: int) -> float:
    """Reciprocal of the first-hit rank within ``k``; ``0.0`` on no hit."""
    rank = first_relevant_rank(expected, returned, k)
    if rank is None:
        return 0.0
    return 1.0 / rank


# --------------------------------------------------------------- run loop


def run_harness(
    *,
    mode: str,
    store: SearchRepository,
    gold: GoldSet,
    handles_to_chunk_ids: dict[str, str],
    embedding_model_name: str,
    query_embedding_lookup: Callable[[str], list[float]],
    top_k: int = DEFAULT_TOP_K,
    candidate_k: int = DEFAULT_CANDIDATE_K,
    corpus_size: int,
) -> HarnessReport:
    """Execute the D-025 contour against ``gold`` and return the report.

    For each ``GoldQuery``:

    1. Look up the query embedding via ``query_embedding_lookup`` (mock
       mode passes a live ``MockEmbeddingClient.embed`` wrapper; postgres
       mode passes a ``cache.get`` wrapper backed by
       ``eval/retrieval/embeddings_cache.json``).
    2. Resolve ``expected_handles`` to live ``chunk_id``s via
       ``handles_to_chunk_ids``. A handle absent from the map raises —
       a stale gold file should fail loudly.
    3. Call ``store.dense_candidates`` and ``store.sparse_candidates``
       at ``candidate_k`` depth, then ``reciprocal_rank_fusion`` at
       ``top_k=candidate_k`` so the fused list is the same depth as the
       legs for honest recall comparison.
    4. Compute per-leg / aggregate metrics.

    The report's aggregate metrics are means across queries; per-query
    rows expose the diagnostic per-leg first-hit rank fields and the
    explicit ``reciprocal_rank_in_fused`` float.
    """
    per_query_rows: list[PerQueryResult] = []
    sum_r5 = 0.0
    sum_r10 = 0.0
    sum_r20 = 0.0
    sum_mrr = 0.0
    sum_dense_recall = 0.0
    sum_sparse_recall = 0.0
    sum_fused_recall_at_20 = 0.0

    for gq in gold.queries:
        expected_ids: list[str] = []
        for handle in gq.expected_handles:
            if handle not in handles_to_chunk_ids:
                raise KeyError(
                    f"gold expected_handle {handle!r} not found in ingested corpus — "
                    f"check eval/retrieval/{{gold.json,corpus.jsonl}} agree on "
                    f"external_message_id + event_index"
                )
            expected_ids.append(handles_to_chunk_ids[handle])
        expected_set = set(expected_ids)

        query_embedding = query_embedding_lookup(gq.query)

        dense_hits = store.dense_candidates(
            gq.family_id, query_embedding, embedding_model_name, candidate_k
        )
        sparse_hits = store.sparse_candidates(gq.family_id, gq.query, candidate_k)
        fused = reciprocal_rank_fusion([dense_hits, sparse_hits], top_k=candidate_k)

        dense_ids = tuple(c.chunk_id for c in dense_hits)
        sparse_ids = tuple(c.chunk_id for c in sparse_hits)
        fused_ids = tuple(h.chunk.chunk_id for h in fused)

        r5 = recall_at_k(expected_set, fused_ids, 5)
        r10 = recall_at_k(expected_set, fused_ids, 10)
        r20 = recall_at_k(expected_set, fused_ids, 20)
        rank_dense = first_relevant_rank(expected_set, dense_ids, candidate_k)
        rank_sparse = first_relevant_rank(expected_set, sparse_ids, candidate_k)
        rank_fused = first_relevant_rank(expected_set, fused_ids, candidate_k)
        rr_fused = 1.0 / rank_fused if rank_fused is not None else 0.0

        per_query_rows.append(
            PerQueryResult(
                query=gq.query,
                family_id=gq.family_id,
                expected_chunk_ids=tuple(expected_ids),
                dense_top_k_ids=dense_ids,
                sparse_top_k_ids=sparse_ids,
                fused_top_k_ids=fused_ids,
                first_relevant_rank_in_dense=rank_dense,
                first_relevant_rank_in_sparse=rank_sparse,
                first_relevant_rank_in_fused=rank_fused,
                reciprocal_rank_in_fused=rr_fused,
                recall_at_5=r5,
                recall_at_10=r10,
                recall_at_20=r20,
            )
        )

        sum_r5 += r5
        sum_r10 += r10
        sum_r20 += r20
        sum_mrr += rr_fused
        # Per-leg recall@20: "did this leg surface at least one expected
        # chunk in its own top-20?" → 1.0 if yes, 0.0 if no. Same shape on
        # all three legs so the report can be read at a glance.
        sum_dense_recall += 1.0 if rank_dense is not None and expected_set else 0.0
        sum_sparse_recall += 1.0 if rank_sparse is not None and expected_set else 0.0
        sum_fused_recall_at_20 += 1.0 if rank_fused is not None and expected_set else 0.0

    n = len(gold.queries) or 1
    aggregate = AggregateMetrics(
        recall_at_5=sum_r5 / n,
        recall_at_10=sum_r10 / n,
        recall_at_20=sum_r20 / n,
        mrr_at_20=sum_mrr / n,
        per_leg_recall_at_20=PerLegRecall(
            dense=sum_dense_recall / n,
            sparse=sum_sparse_recall / n,
            fused=sum_fused_recall_at_20 / n,
        ),
    )
    # ``top_k`` is part of the public surface (``recall_at_5`` is its
    # natural projection) but the report itself does not need to echo it
    # back beyond the recall fields. Reference it once so mypy / lint do
    # not flag the parameter as unused if a caller passes the default.
    _ = top_k
    return HarnessReport(
        mode=mode,
        corpus_size=corpus_size,
        queries=len(gold.queries),
        aggregate=aggregate,
        per_query=tuple(per_query_rows),
    )
