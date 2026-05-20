"""Retrieval-quality inspection harness against the D-025 baseline (D-038).

Pure data + pure metric functions plus the orchestration that drives
``DomainService.ingest`` on a fixture corpus and then calls
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
message after canonical ``parse_note`` + chunking by
``DomainService.ingest``**. It is NOT a business event id, NOT a Telegram
message id, NOT any external domain identifier. The handle only exists
because ``chunk_id`` is uuid4 at ingest time and so cannot be pinned in
``eval/retrieval/gold.json`` directly.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from memory_rag.core.answers import ChatClient, ChatResponse
from memory_rag.core.domain import FallbackMode
from memory_rag.core.domain.answer_prompt import AnswerPrompt
from memory_rag.core.domain.models import EventChunk
from memory_rag.core.embeddings import EmbeddingClient
from memory_rag.core.routing import InboundMessage, RouteKind
from memory_rag.services.domain_service import DomainService
from memory_rag.services.query_service import QueryService
from memory_rag.services.retrieval import reciprocal_rank_fusion
from memory_rag.storage.repository import DomainRepository
from memory_rag.storage.search_repository import SearchRepository

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

    community_id: str
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
    community_id: str
    author_user_id: str
    raw_text: str


@dataclass(frozen=True, slots=True)
class PerLegRecall:
    dense: float
    sparse: float
    fused: float


@dataclass(frozen=True, slots=True)
class AggregateMetrics:
    """Means / fractions across the gold set.

    ``hit_rate`` uses a **non-empty-gold denominator** — only queries with
    at least one ``expected_handle`` participate. Negative queries (empty
    ``expected_handles``) cannot produce a hit, so counting them would just
    dilute the rate. This is what keeps ``hit_rate`` distinct from
    ``per_leg_recall_at_20.fused``, which divides by *all* queries.
    ``empty_rate`` divides by all queries — it measures retrieval returning
    zero candidates, independent of whether the query had expected chunks.
    """

    recall_at_5: float
    recall_at_10: float
    recall_at_20: float
    mrr_at_20: float
    hit_rate: float
    empty_rate: float
    per_leg_recall_at_20: PerLegRecall


@dataclass(frozen=True, slots=True)
class PerQueryResult:
    """One row per gold query in the harness report.

    ``first_relevant_rank_in_{dense,sparse,fused}`` are diagnostic 1-based
    ranks within each leg's own top-``candidate_k`` list (``None`` when no
    expected chunk appears). ``reciprocal_rank_in_fused`` is the explicit
    ``mrr@20`` numerator at per-query granularity — equals
    ``1.0 / first_relevant_rank_in_fused`` on a hit, ``0.0`` otherwise.

    ``retrieval_latency_ms`` (OP-5.3 / D-059) is the in-harness
    ``time.perf_counter`` wall-clock around the dense + sparse + RRF block
    only. The query-embedding lookup is **intentionally excluded** from
    this boundary because mock mode obtains query embeddings via a live
    ``MockEmbeddingClient.embed`` call while Postgres mode reads from the
    pinned ``embeddings_cache.json`` — including the lookup would
    contaminate the metric with that mode-asymmetric cost. Defaults to
    ``0.0`` (unmeasured); test helpers that construct rows by keyword
    can omit it.
    """

    query: str
    community_id: str
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
    retrieval_latency_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class PerAnswerResult:
    """One row per gold query in the groundedness (answer-path) report.

    ``answerable`` is ``True`` when the source ``GoldQuery.expected_handles``
    is non-empty (the query is gold-answerable; negatives are excluded from
    the ``groundedness_rate`` denominator). ``fallback_mode`` carries the
    ``FallbackMode.value`` returned by ``QueryService.answer``.
    ``context_chunk_count`` is ``len(AnswerResult.context.ordered_chunks)`` —
    how many chunks the answer path actually saw post-RRF.
    ``grounded`` is derived from ``fallback_mode`` via ``is_grounded``
    (the documented fallback-derived proxy mapping, OP-5.2b / D-058).

    ``answer_latency_ms`` / ``prompt_tokens`` / ``completion_tokens`` (OP-5.3
    / D-059) are the eval-harness measurements around the ``QueryService.answer``
    call. ``answer_latency_ms`` is the in-harness wall-clock around the whole
    call; ``prompt_tokens`` / ``completion_tokens`` come from
    ``ChatResponse.token_counts`` (``.get("prompt", 0)`` / ``.get("completion", 0)``)
    captured by a ``RecordingChatClient`` shim. They are ``0`` whenever no
    chat call ran — the ``NO_EVIDENCE`` / empty-query / ``PROVIDER_UNAVAILABLE``
    contours short-circuit before invoking the chat client (D-035), so a row
    on one of those contours carries zero tokens by design. The
    ``answer_calls_with_tokens`` denominator in ``CostMetrics`` excludes
    those rows from the mean. Defaults exist so test helpers can omit them.
    """

    query: str
    community_id: str
    answerable: bool
    fallback_mode: str
    context_chunk_count: int
    grounded: bool
    answer_latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True, slots=True)
class GroundednessMetrics:
    """Proxy groundedness metric derived from ``AnswerResult.fallback``;
    not a factuality or citation-coverage score.

    The metric is a **fallback-derived proxy** for "answer text supported by
    retrieved evidence" (I-9 citation-subset semantics): an answer is graded
    grounded when its ``FallbackMode`` is one of the contours that, by the
    D-035 parse contract, carries a non-empty ``cited_chunk_ids`` that is a
    subset of the answer context. ``PARSE_FAILURE`` (which catches
    ``FabricatedCitationError`` — the I-9 violation contour) and
    ``PROVIDER_UNAVAILABLE`` / ``NO_EVIDENCE`` are not grounded.

    ``groundedness_rate`` uses a **non-empty-gold (answerable) denominator**
    — only queries with at least one ``expected_handle`` participate;
    negatives correctly returning ``NO_EVIDENCE`` are excluded so they do
    not dilute the rate (mirrors the OP-5.2a / D-057 ``hit_rate``
    denominator). ``fallback_mode_counts`` is a breakdown over **all**
    queries (negatives included), for inspection.
    """

    groundedness_rate: float
    fallback_mode_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class GroundednessReport:
    aggregate: GroundednessMetrics
    per_answer: tuple[PerAnswerResult, ...]


@dataclass(frozen=True, slots=True)
class CostMetrics:
    """Token totals over the answer-path rows (OP-5.3 / D-059).

    Token sums cover the whole gold set; ``answer_calls_with_tokens`` is
    the count of answer-path rows whose ``prompt_tokens + completion_tokens``
    is non-zero (the rows where a chat call actually ran). That count is
    the denominator for ``mean_total_tokens_per_call`` so empty-query /
    ``NO_EVIDENCE`` / ``PROVIDER_UNAVAILABLE`` short-circuits do not pull
    the per-call mean toward zero. Tokens are **provider-reported**: under
    a real provider they come from the API response; under the mock chat
    client they are character-count approximations (per
    ``ChatResponse`` docstring) — the metric reports whatever the chat
    client returned, no more.
    """

    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    answer_calls_with_tokens: int
    mean_total_tokens_per_call: float


@dataclass(frozen=True, slots=True)
class LatencyMetrics:
    """Wall-clock latency aggregates measured in the eval harness (OP-5.3 / D-059).

    Both pairs are ``time.perf_counter`` measurements taken inside the
    harness, around the underlying call:

    - ``retrieval_*_ms`` covers the dense + sparse + RRF block per query
      inside :func:`run_harness`. The query-embedding lookup is
      **intentionally excluded** (mode-asymmetric: live ``embed`` vs.
      cache ``get``).
    - ``answer_*_ms`` covers the per-query ``QueryService.answer(...)``
      call inside :func:`run_answer_harness` — the whole answer path
      (retrieval + chat + persistence), not just the chat call.

    Both denominators are **all queries** (every row contributes one
    sample). ``p50`` is included as a small-sample robustness check at
    the current ~20-21 query gold-set size — a single slow outlier
    pulls the mean but not the median. ``p95`` is intentionally
    **omitted** at this sample size because it would be noisy and
    misleading. The provider-attributed ``ChatResponse.latency_ms`` is
    *not* aggregated here — it remains the canonical chat-call latency
    persisted on ``AnswerTrace`` (D-034/D-035) and is **trace-level
    provenance, not an aggregate metric in this report**.
    """

    mean_retrieval_ms: float
    p50_retrieval_ms: float
    max_retrieval_ms: float
    mean_answer_ms: float
    p50_answer_ms: float
    max_answer_ms: float


@dataclass(frozen=True, slots=True)
class CostLatencyMetrics:
    """OP-5.3 / D-059 cost & latency aggregate, attached to ``HarnessReport``."""

    cost: CostMetrics
    latency: LatencyMetrics


@dataclass(frozen=True, slots=True)
class HarnessReport:
    mode: str  # "mock" | "postgres"
    corpus_size: int
    queries: int
    aggregate: AggregateMetrics
    per_query: tuple[PerQueryResult, ...]
    # ``groundedness`` is attached by the CLI after ``run_harness`` returns —
    # ``run_harness`` itself computes retrieval only (no chat client). Default
    # ``None`` keeps the JSON additive on top of the OP-5.2a / D-057 shape.
    groundedness: GroundednessReport | None = None
    # ``cost_latency`` is attached by the CLI after both halves run (OP-5.3 /
    # D-059). Default ``None`` keeps the JSON additive on top of OP-5.2b.
    cost_latency: CostLatencyMetrics | None = None


# --------------------------------------------------------------------- IO


def load_gold(path: Path) -> GoldSet:
    """Read ``gold.json``. Schema: see ``eval/retrieval/gold.json``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    default_community = data.get("community_id_default", "")
    queries: list[GoldQuery] = []
    for raw in data["queries"]:
        community_id = raw.get("community_id", default_community)
        if not community_id:
            raise ValueError(
                f"gold query missing community_id (no community_id_default either): {raw!r}"
            )
        queries.append(
            GoldQuery(
                community_id=community_id,
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
                community_id=obj["community_id"],
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
    repo: DomainRepository,
    chunks_for_source: Callable[[str], list[EventChunk]],
    embedding_client: EmbeddingClient,
    corpus: tuple[CorpusMessage, ...],
) -> dict[str, str]:
    """Drive ``DomainService.ingest`` over the corpus and build the handle map.

    ``chunks_for_source`` is a small backend-specific lookup the caller
    passes in: ``MockDomainStore`` reads its private chunks dict;
    ``PostgresDomainStore`` uses a separate psycopg query in the CLI. The
    Protocol does not surface "list chunks for source" today; adding it
    is wider than this packet's scope, so the harness wires the lookup
    explicitly.

    The function's docstring restates the handle contract: returned keys
    are ``f"{external_message_id}#{event_index}"`` where ``event_index``
    is the 0-based ordinal of the produced ``EventChunk`` within the
    parsed source message after ``DomainService.ingest`` chunked it.
    """
    service = DomainService(repo, embedding_client=embedding_client)
    handles: dict[str, str] = {}
    received_at = datetime.now(tz=UTC)
    for cm in corpus:
        inbound = InboundMessage(
            external_message_id=cm.external_message_id,
            external_chat_id=cm.community_id,
            external_user_id=cm.author_user_id,
            text=cm.raw_text,
            payload=cm.raw_text,
            route=RouteKind.NOTE,
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


def hit_rate(rows: Sequence[PerQueryResult]) -> float:
    """Fraction of **non-empty-gold** queries that surfaced a relevant chunk.

    Denominator is the set of gold queries with at least one expected
    chunk; numerator is those whose fused result list contained at least
    one of them (``first_relevant_rank_in_fused is not None``). Negative
    queries (empty ``expected_chunk_ids``) are excluded from both — they
    cannot produce a hit. Returns ``0.0`` when there is no non-empty-gold
    query, keeping aggregation honest without raising.
    """
    answerable = [r for r in rows if r.expected_chunk_ids]
    if not answerable:
        return 0.0
    hits = sum(1 for r in answerable if r.first_relevant_rank_in_fused is not None)
    return hits / len(answerable)


def empty_rate(rows: Sequence[PerQueryResult]) -> float:
    """Fraction of **all** gold queries whose fused result list was empty.

    An empty fused list means retrieval returned zero candidates (both the
    dense and sparse legs came back empty). This counts every gold query,
    answerable or negative. Returns ``0.0`` for an empty report.
    """
    if not rows:
        return 0.0
    empties = sum(1 for r in rows if not r.fused_top_k_ids)
    return empties / len(rows)


# ------------------------------------------------------ groundedness (proxy)


_GROUNDED_FALLBACKS: frozenset[FallbackMode] = frozenset(
    {FallbackMode.NONE, FallbackMode.WEAK_EVIDENCE, FallbackMode.AMBIGUOUS}
)
"""Fallback contours that, by the D-035 parse contract, carry a non-empty
``cited_chunk_ids`` that is a subset of the answer context — the proxy
"answer text supported by retrieved evidence" set used by OP-5.2b / D-058.

``NO_EVIDENCE`` (empty retrieval or LLM-declared no_evidence),
``PROVIDER_UNAVAILABLE`` (no answer produced), and ``PARSE_FAILURE`` (which
catches ``FabricatedCitationError`` — the I-9 citation-subset violation
contour) are intentionally **not** grounded.
"""


def is_grounded(fallback: FallbackMode) -> bool:
    """Documented fallback-derived proxy mapping (OP-5.2b / D-058).

    ``True`` for ``NONE`` / ``WEAK_EVIDENCE`` / ``AMBIGUOUS`` — the three
    contours that by the D-035 parse contract carry a non-empty
    ``cited_chunk_ids`` ⊆ context. ``False`` for ``NO_EVIDENCE`` /
    ``PROVIDER_UNAVAILABLE`` / ``PARSE_FAILURE`` (the I-9-violation
    contour is folded into ``PARSE_FAILURE`` and remains ungrounded).
    """
    return fallback in _GROUNDED_FALLBACKS


def groundedness_rate(rows: Sequence[PerAnswerResult]) -> float:
    """Fraction of **answerable** queries whose answer was grounded (proxy).

    Denominator is the set of gold queries with at least one
    ``expected_handle`` (``answerable=True``); numerator is those whose
    ``grounded`` flag is ``True``. Negatives are excluded — a negative
    correctly returning ``NO_EVIDENCE`` should not dilute the rate. Returns
    ``0.0`` when there is no answerable query (mirrors ``hit_rate``).
    """
    answerable = [r for r in rows if r.answerable]
    if not answerable:
        return 0.0
    grounded = sum(1 for r in answerable if r.grounded)
    return grounded / len(answerable)


def fallback_mode_counts(rows: Sequence[PerAnswerResult]) -> dict[str, int]:
    """Count per ``fallback_mode`` over **all** rows (negatives included).

    The breakdown sums to ``len(rows)`` so an operator can read the full
    distribution of answer-path outcomes at a glance.
    """
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.fallback_mode] = counts.get(row.fallback_mode, 0) + 1
    return counts


# ----------------------------------------------------------- cost & latency
#
# OP-5.3 / D-059: token + wall-clock latency aggregates for the eval harness.
# Inspection-only — no thresholds, no gating, no production behavior change.


class RecordingChatClient:
    """Eval-harness ``ChatClient`` shim that captures the most recent response.

    Single-call / single-consumer contract (OP-5.3 / D-059): each
    :meth:`complete` call **overwrites** an internal one-slot buffer; the
    harness reads via :meth:`consume_last`, which returns the recorded
    response *and clears the slot*. The clear-on-read semantics guarantee
    that a recorded response from one chat call cannot be misattributed to
    a later answer-path contour that short-circuited without invoking the
    chat client (``NO_EVIDENCE``, empty-query, ``PROVIDER_UNAVAILABLE`` — see
    D-035): in that case :meth:`consume_last` returns ``None`` and the
    harness's per-row token counters stay at zero.

    This shim lives in the eval surface and is not used by production code.
    It implements the :class:`ChatClient` Protocol structurally so the
    operator-selected chat client (mock or real) can be wrapped without any
    change to ``QueryService``.
    """

    def __init__(self, inner: ChatClient) -> None:
        self._inner = inner
        self._last: ChatResponse | None = None

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    def complete(self, prompt: AnswerPrompt) -> ChatResponse:
        response = self._inner.complete(prompt)
        # Overwrite, not append: a previous unconsumed response on a no-chat
        # contour would be a contract violation but is also harmlessly
        # superseded if a later call does run.
        self._last = response
        return response

    def consume_last(self) -> ChatResponse | None:
        """Return the most recent response and clear the slot.

        Returns ``None`` when no chat call has happened since the previous
        :meth:`consume_last` (or since construction). This is the read
        side of the single-call / single-consumer contract.
        """
        response = self._last
        self._last = None
        return response


def _latency_stats(values: Sequence[float]) -> tuple[float, float, float]:
    """Return (mean, p50, max) wall-clock latency. ``(0.0, 0.0, 0.0)`` on empty.

    ``p50`` uses :func:`statistics.median` so an even-length sample averages
    the two middle values, matching the stdlib convention. ``p95`` is
    intentionally omitted at the current ~20-query gold-set size — it would
    be too noisy to be meaningful.
    """
    if not values:
        return (0.0, 0.0, 0.0)
    total = sum(values)
    mean = total / len(values)
    return (mean, float(median(values)), float(max(values)))


def cost_metrics(rows: Sequence[PerAnswerResult]) -> CostMetrics:
    """Sum tokens across answer-path rows and compute the per-call mean.

    ``answer_calls_with_tokens`` is the count of rows whose recorded
    ``prompt_tokens + completion_tokens`` is non-zero — rows on the
    no-chat-call contours (``NO_EVIDENCE`` / empty-query /
    ``PROVIDER_UNAVAILABLE`` — D-035) stay at zero and are excluded from
    the mean denominator. Returns a zero-valued :class:`CostMetrics` on an
    empty report (the empty-report → 0 contract).
    """
    if not rows:
        return CostMetrics(
            total_prompt_tokens=0,
            total_completion_tokens=0,
            total_tokens=0,
            answer_calls_with_tokens=0,
            mean_total_tokens_per_call=0.0,
        )
    total_prompt = sum(r.prompt_tokens for r in rows)
    total_completion = sum(r.completion_tokens for r in rows)
    total = total_prompt + total_completion
    with_tokens = sum(1 for r in rows if (r.prompt_tokens + r.completion_tokens) > 0)
    mean = total / with_tokens if with_tokens else 0.0
    return CostMetrics(
        total_prompt_tokens=total_prompt,
        total_completion_tokens=total_completion,
        total_tokens=total,
        answer_calls_with_tokens=with_tokens,
        mean_total_tokens_per_call=mean,
    )


def latency_metrics(
    retrieval_rows: Sequence[PerQueryResult],
    answer_rows: Sequence[PerAnswerResult],
) -> LatencyMetrics:
    """Compute wall-clock mean / p50 / max for the retrieval and answer halves.

    Both denominators are **all rows** in the corresponding sequence — every
    query contributes one retrieval sample inside :func:`run_harness` and
    one answer-path sample inside :func:`run_answer_harness`. Returns a
    zero-valued :class:`LatencyMetrics` on empty input (the empty-report
    → 0 contract).
    """
    r_mean, r_p50, r_max = _latency_stats([r.retrieval_latency_ms for r in retrieval_rows])
    a_mean, a_p50, a_max = _latency_stats([r.answer_latency_ms for r in answer_rows])
    return LatencyMetrics(
        mean_retrieval_ms=r_mean,
        p50_retrieval_ms=r_p50,
        max_retrieval_ms=r_max,
        mean_answer_ms=a_mean,
        p50_answer_ms=a_p50,
        max_answer_ms=a_max,
    )


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

    The report's recall / MRR aggregates are means across queries;
    ``hit_rate`` is a fraction over non-empty-gold queries only and
    ``empty_rate`` a fraction over all queries (see ``AggregateMetrics``).
    Per-query rows expose the diagnostic per-leg first-hit rank fields and
    the explicit ``reciprocal_rank_in_fused`` float.
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

        # The query-embedding lookup is intentionally **outside** the
        # retrieval-latency wall-clock boundary: mock mode calls
        # ``MockEmbeddingClient.embed`` live while Postgres mode reads from
        # the pinned cache — including the lookup would contaminate the
        # metric with that mode-asymmetric cost (OP-5.3 / D-059).
        query_embedding = query_embedding_lookup(gq.query)

        t0 = time.perf_counter()
        dense_hits = store.dense_candidates(
            gq.community_id, query_embedding, embedding_model_name, candidate_k
        )
        sparse_hits = store.sparse_candidates(gq.community_id, gq.query, candidate_k)
        fused = reciprocal_rank_fusion([dense_hits, sparse_hits], top_k=candidate_k)
        retrieval_latency_ms = (time.perf_counter() - t0) * 1000.0

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
                community_id=gq.community_id,
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
                retrieval_latency_ms=retrieval_latency_ms,
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
        hit_rate=hit_rate(per_query_rows),
        empty_rate=empty_rate(per_query_rows),
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


# ----------------------------------------------------- answer-path run loop


def run_answer_harness(
    *,
    query_service: QueryService,
    gold: GoldSet,
    chat_recorder: RecordingChatClient | None = None,
) -> GroundednessReport:
    """Drive ``QueryService.answer`` over every gold query and grade groundedness.

    For each ``GoldQuery`` the harness builds an ``InboundMessage``
    (``RouteKind.ASK``, ``route_source="command"``) carrying the query text
    and the gold ``community_id``, calls ``query_service.answer(...)``, and
    records one ``PerAnswerResult``. ``grounded`` is derived from
    ``AnswerResult.fallback`` via :func:`is_grounded` — the documented
    fallback-derived proxy (OP-5.2b / D-058). No gold-handle resolution is
    needed: groundedness ("supported by *retrieved* evidence") does not
    depend on gold relevance — handles are already validated by
    :func:`run_harness` upstream.

    The aggregate ``groundedness_rate`` uses the non-empty-gold
    (answerable) denominator; ``fallback_mode_counts`` covers all rows.

    OP-5.3 / D-059 — when ``chat_recorder`` is the same
    :class:`RecordingChatClient` instance the caller wrapped around the
    chat client passed to ``query_service``, each row carries a wall-clock
    ``answer_latency_ms`` (``time.perf_counter`` around the whole
    ``query_service.answer(...)`` call) and, when a chat call ran,
    ``prompt_tokens`` / ``completion_tokens`` from
    ``ChatResponse.token_counts``. The harness reads tokens via
    :meth:`RecordingChatClient.consume_last`, whose read-and-clear
    semantics guarantee that a no-chat-call answer-path contour
    (``NO_EVIDENCE`` / empty-query / ``PROVIDER_UNAVAILABLE`` — D-035)
    cannot misattribute a previous response's tokens to its row: the
    consume returns ``None`` and the row stays at zero tokens. When
    ``chat_recorder`` is ``None``, tokens stay at zero on every row but
    latency is still measured.
    """
    received_at = datetime.now(tz=UTC)
    per_answer: list[PerAnswerResult] = []
    for gq in gold.queries:
        inbound = InboundMessage(
            external_message_id=f"eval-ask-{gq.community_id}-{len(per_answer)}",
            external_chat_id=gq.community_id,
            external_user_id="eval-user",
            text=gq.query,
            payload=gq.query,
            route=RouteKind.ASK,
            received_at=received_at,
            route_source="command",
        )
        t0 = time.perf_counter()
        result = query_service.answer(inbound)
        answer_latency_ms = (time.perf_counter() - t0) * 1000.0

        prompt_tokens = 0
        completion_tokens = 0
        if chat_recorder is not None:
            last = chat_recorder.consume_last()
            if last is not None:
                # ``ChatResponse.token_counts`` is provider-attributed and
                # free-form (per docstring); the canonical keys are
                # ``"prompt"`` / ``"completion"``. Anything else stays 0.
                prompt_tokens = int(last.token_counts.get("prompt", 0))
                completion_tokens = int(last.token_counts.get("completion", 0))

        per_answer.append(
            PerAnswerResult(
                query=gq.query,
                community_id=gq.community_id,
                answerable=bool(gq.expected_handles),
                fallback_mode=result.fallback.value,
                context_chunk_count=len(result.context.ordered_chunks)
                if result.context is not None
                else 0,
                grounded=is_grounded(result.fallback),
                answer_latency_ms=answer_latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        )

    aggregate = GroundednessMetrics(
        groundedness_rate=groundedness_rate(per_answer),
        fallback_mode_counts=fallback_mode_counts(per_answer),
    )
    return GroundednessReport(aggregate=aggregate, per_answer=tuple(per_answer))
