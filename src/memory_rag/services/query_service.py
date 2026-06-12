"""Channel-neutral query service — baseline hybrid retrieval (D-025).

Embeds the query, runs the dense leg (vector similarity, community-scoped,
``embedding_status='ready'`` only) and the sparse leg (PostgreSQL FTS
baseline, ``simple`` dictionary) against ``SearchRepository``, fuses the
two ranked lists with Reciprocal Rank Fusion at the service layer, and
returns the top-k chunks as ``Evidence``. Empty merged set surfaces
``FallbackMode.NO_EVIDENCE`` rather than fabricating an answer
(Invariant I-9, runtime R-5 / R-6).

Score calibration between cosine distance and ts_rank is intentionally
out of scope: RRF merges on rank position, not on calibrated scores.
BM25, rerankers, and cross-encoders belong to the next quality-decision
packet.

Slice 3.5: every call writes a ``Query`` row and zero-or-more
``RetrievalHit`` rows so an operator can inspect what each leg saw and
what survived RRF via plain SQL. Successful retrieval writes per-leg
rows for every candidate plus merged rows for every chunk in the
returned evidence; ``NO_EVIDENCE`` (empty query or empty merged) still
writes the ``Query`` row with zero hits.

Slice 4.1: after RRF the service invokes
:func:`memory_rag.services.context_assembler.assemble_answer_context` and
attaches the resulting :class:`AnswerContext` to the returned
``AnswerResult`` so the upcoming Phase-4 answer-prompt and chat-client
packets can consume the assembled context without another refactor.

Slice 4.3a (D-034): the answer-side half of R-5 landed here on the
success and no-evidence/empty-query contours. Slice 4.3b (D-035) closes
the remaining contours: weak-evidence, ambiguous, the LLM-marker
``no_evidence`` sub-branch, provider-unavailable, and parse-failure.
``Query.fallback`` and ``AnswerTrace.fallback_mode`` are written as one
decision per call so they always agree.

Grading flow on the success branch of retrieval:

1. Build the versioned answer prompt from the assembled context.
2. Call the configured ``ChatClient``. A
   :class:`~memory_rag.core.answers.ChatProviderUnavailableError` is
   caught once and graded as ``PROVIDER_UNAVAILABLE`` (no retry, no
   repair — recovery is Phase-6 work).
3. Parse the response with ``parse_structured_answer``. Any
   :class:`~memory_rag.core.domain.answer_schema.StructuredAnswerError` is
   caught and graded as ``PARSE_FAILURE``; the trace preserves
   ``response.raw_text`` as ``answer_text`` for forensics.
4. Map the structured answer's ``uncertainty`` marker to
   ``FallbackMode``: ``confident → NONE``, ``uncertain → WEAK_EVIDENCE``,
   ``no_evidence → NO_EVIDENCE`` (LLM declared the retrieved chunks
   not-evidence), ``ambiguous → AMBIGUOUS``.

``ChatResponse.latency_ms`` is the single source of truth for chat-call
latency; this service does not measure latency independently.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from memory_rag.core.answers import ChatClient, ChatProviderUnavailableError
from memory_rag.core.domain import (
    AnswerResult,
    AnswerTrace,
    DateRange,
    Evidence,
    FallbackMode,
    Query,
    RetrievalHit,
)
from memory_rag.core.domain.answer_prompt import PROMPT_VERSION, build_answer_prompt
from memory_rag.core.domain.answer_schema import (
    StructuredAnswerError,
    UncertaintyMarker,
    parse_structured_answer,
)
from memory_rag.core.domain.models import AnswerContext, EventChunk
from memory_rag.core.embeddings import EmbeddingClient
from memory_rag.core.routing import InboundMessage
from memory_rag.logging import get_logger
from memory_rag.services.context_assembler import assemble_answer_context
from memory_rag.services.retrieval import (
    FusedHit,
    RetrievedCandidates,
    build_retrieval_hits,
    reciprocal_rank_fusion,
)
from memory_rag.storage.repository import DomainRepository
from memory_rag.storage.search_repository import SearchRepository

log = get_logger(__name__)

DEFAULT_TOP_K = 5
DEFAULT_CANDIDATE_K = 20

_TRAILING_QUERY_PUNCT = "?.!,;:"

_MARKER_TO_FALLBACK: dict[UncertaintyMarker, FallbackMode] = {
    "confident": FallbackMode.NONE,
    "uncertain": FallbackMode.WEAK_EVIDENCE,
    "no_evidence": FallbackMode.NO_EVIDENCE,
    "ambiguous": FallbackMode.AMBIGUOUS,
}


def normalize_query(payload: str) -> str:
    """Trim whitespace and terminal punctuation so plain questions match cleanly."""
    return payload.strip().rstrip(_TRAILING_QUERY_PUNCT).strip()


class QueryService:
    """Answers an ``InboundMessage`` carrying an ``/ask`` payload."""

    def __init__(
        self,
        repo: DomainRepository,
        search_repo: SearchRepository,
        embedding_client: EmbeddingClient,
        chat_client: ChatClient,
        *,
        top_k: int = DEFAULT_TOP_K,
        candidate_k: int = DEFAULT_CANDIDATE_K,
    ) -> None:
        if top_k <= 0:
            raise ValueError(f"top_k must be positive, got {top_k}")
        if candidate_k < top_k:
            raise ValueError(f"candidate_k ({candidate_k}) must be >= top_k ({top_k})")
        self._repo = repo
        self._search = search_repo
        self._embed = embedding_client
        self._chat = chat_client
        self._top_k = top_k
        self._candidate_k = candidate_k

    def retrieve(
        self,
        community_id: str,
        query_text: str,
        *,
        date_range: DateRange | None = None,
        subject_scope: str | None = None,
    ) -> RetrievedCandidates:
        """Run one pure hybrid-retrieval pass (RC-3).

        Embeds ``query_text``, runs both legs with the same community
        scoping and optional ``date_range`` / ``subject_scope`` kwargs
        (R-3 / R-8; D-040 / D-107), and fuses them with RRF. Writes no
        rows — persistence stays with the caller so ``Query.fallback``
        remains a single post-generation decision (D-035). Callers pass
        a non-empty, already-normalized ``query_text``.
        """
        if not community_id:
            raise ValueError("community_id is required (R-3)")
        query_embedding = self._embed.embed([query_text])[0]
        model_name = self._embed.model_name
        dense_hits = self._search.dense_candidates(
            community_id,
            query_embedding,
            model_name,
            self._candidate_k,
            date_range=date_range,
            subject_scope=subject_scope,
        )
        sparse_hits = self._search.sparse_candidates(
            community_id,
            query_text,
            self._candidate_k,
            date_range=date_range,
            subject_scope=subject_scope,
        )
        merged = reciprocal_rank_fusion([dense_hits, sparse_hits], top_k=self._top_k)
        return RetrievedCandidates(
            dense=dense_hits,
            sparse=sparse_hits,
            merged=merged,
            embedding_model_name=model_name,
        )

    def answer(
        self,
        message: InboundMessage,
        *,
        date_range: DateRange | None = None,
        subject_scope: str | None = None,
    ) -> AnswerResult:
        """Answer an ``/ask`` payload via baseline hybrid retrieval.

        When ``date_range`` is given, both retrieval legs are restricted
        to chunks whose ``note_date`` falls within its inclusive bounds
        (Slice 3.4, D-040); ``None`` (the default) applies no date
        constraint. There is no inbound date syntax yet — the Telegram
        webhook passes no ``date_range``.

        When ``subject_scope`` is given, both retrieval legs are
        restricted to chunks whose ``subject_id`` equals it — strict
        match, so community-wide chunks (``subject_id`` ``None``) are
        excluded (H-3, D-107); ``None`` (the default) applies no subject
        constraint. The scope composes with ``date_range`` and is
        recorded on the persisted ``Query`` row. There is no inbound
        subject syntax yet — the Telegram webhook passes no
        ``subject_scope``.
        """
        # Opaque community scope resolved by the adapter at the edge (D-093 /
        # G-1); the core never re-derives it from external_chat_id (I-1).
        community_id = message.community_id
        if not community_id:
            raise ValueError("InboundMessage.community_id is required (R-3)")

        query_text = normalize_query(message.payload)
        created_at = datetime.now(tz=UTC)
        query_id = str(uuid4())
        model_name = self._embed.model_name

        if not query_text:
            return self._finalize(
                query_id=query_id,
                community_id=community_id,
                query_text=query_text,
                model_name=model_name,
                created_at=created_at,
                fallback=FallbackMode.NO_EVIDENCE,
                subject_scope=subject_scope,
                dense_hits=[],
                sparse_hits=[],
                merged=[],
                context=AnswerContext(
                    query_id=query_id,
                    query_text=query_text,
                    ordered_chunks=(),
                    model_name=model_name,
                    created_at=created_at,
                ),
                evidence=[],
                trace_answer_text="",
                trace_model_name=self._chat.model_name,
                trace_token_counts={},
                trace_latency_ms=0,
                trace_context_chunk_ids=(),
                answer_text=None,
                cited_chunk_ids=(),
            )

        candidates = self.retrieve(
            community_id,
            query_text,
            date_range=date_range,
            subject_scope=subject_scope,
        )
        dense_hits = candidates.dense
        sparse_hits = candidates.sparse
        merged = candidates.merged

        # The persisted Query is constructed inside `_finalize` so its
        # `fallback` matches the AnswerTrace's `fallback_mode` by construction
        # (Decision 2, D-035). The provisional Query here only seeds
        # `assemble_answer_context`, which reads identity + text + timestamp
        # but not the fallback.
        provisional_query = Query(
            query_id=query_id,
            community_id=community_id,
            query_text=query_text,
            model_name=model_name,
            fallback=FallbackMode.NONE,
            created_at=created_at,
            subject_scope=subject_scope,
        )
        context = assemble_answer_context(provisional_query, merged)
        context_chunk_ids = tuple(c.chunk_id for c in context.ordered_chunks)
        evidence = [
            Evidence(
                chunk_id=h.chunk.chunk_id,
                note_date=h.chunk.note_date,
                chunk_text=h.chunk.chunk_text,
            )
            for h in merged
        ]

        if not merged:
            return self._finalize(
                query_id=query_id,
                community_id=community_id,
                query_text=query_text,
                model_name=model_name,
                created_at=created_at,
                fallback=FallbackMode.NO_EVIDENCE,
                subject_scope=subject_scope,
                dense_hits=dense_hits,
                sparse_hits=sparse_hits,
                merged=merged,
                context=context,
                evidence=evidence,
                trace_answer_text="",
                trace_model_name=self._chat.model_name,
                trace_token_counts={},
                trace_latency_ms=0,
                trace_context_chunk_ids=(),
                answer_text=None,
                cited_chunk_ids=(),
            )

        prompt = build_answer_prompt(context)

        try:
            response = self._chat.complete(prompt)
        except ChatProviderUnavailableError:
            return self._finalize(
                query_id=query_id,
                community_id=community_id,
                query_text=query_text,
                model_name=model_name,
                created_at=created_at,
                fallback=FallbackMode.PROVIDER_UNAVAILABLE,
                subject_scope=subject_scope,
                dense_hits=dense_hits,
                sparse_hits=sparse_hits,
                merged=merged,
                context=context,
                evidence=evidence,
                trace_answer_text="",
                trace_model_name=self._chat.model_name,
                trace_token_counts={},
                trace_latency_ms=0,
                trace_context_chunk_ids=context_chunk_ids,
                answer_text=None,
                cited_chunk_ids=(),
            )

        try:
            structured = parse_structured_answer(response.raw_text, context=context)
        except StructuredAnswerError:
            return self._finalize(
                query_id=query_id,
                community_id=community_id,
                query_text=query_text,
                model_name=model_name,
                created_at=created_at,
                fallback=FallbackMode.PARSE_FAILURE,
                subject_scope=subject_scope,
                dense_hits=dense_hits,
                sparse_hits=sparse_hits,
                merged=merged,
                context=context,
                evidence=evidence,
                trace_answer_text=response.raw_text,
                trace_model_name=response.model_name,
                trace_token_counts=dict(response.token_counts),
                trace_latency_ms=response.latency_ms,
                trace_context_chunk_ids=context_chunk_ids,
                answer_text=None,
                cited_chunk_ids=(),
            )

        graded = _MARKER_TO_FALLBACK[structured.uncertainty]
        return self._finalize(
            query_id=query_id,
            community_id=community_id,
            query_text=query_text,
            model_name=model_name,
            created_at=created_at,
            fallback=graded,
            subject_scope=subject_scope,
            dense_hits=dense_hits,
            sparse_hits=sparse_hits,
            merged=merged,
            context=context,
            evidence=evidence,
            trace_answer_text=structured.answer_text,
            trace_model_name=response.model_name,
            trace_token_counts=dict(response.token_counts),
            trace_latency_ms=response.latency_ms,
            trace_context_chunk_ids=context_chunk_ids,
            answer_text=structured.answer_text,
            cited_chunk_ids=structured.cited_chunk_ids,
        )

    def _finalize(
        self,
        *,
        query_id: str,
        community_id: str,
        query_text: str,
        model_name: str,
        created_at: datetime,
        fallback: FallbackMode,
        subject_scope: str | None,
        dense_hits: list[EventChunk],
        sparse_hits: list[EventChunk],
        merged: list[FusedHit],
        context: AnswerContext,
        evidence: list[Evidence],
        trace_answer_text: str,
        trace_model_name: str,
        trace_token_counts: dict[str, int],
        trace_latency_ms: int,
        trace_context_chunk_ids: tuple[str, ...],
        answer_text: str | None,
        cited_chunk_ids: tuple[str, ...],
    ) -> AnswerResult:
        """Persist Query + retrieval hits + AnswerTrace; emit the log line; build the result.

        All non-error and error branches converge here so ``Query.fallback``
        and ``AnswerTrace.fallback_mode`` are written from one decision
        (Decision 2, D-035).
        """
        query = Query(
            query_id=query_id,
            community_id=community_id,
            query_text=query_text,
            model_name=model_name,
            fallback=fallback,
            created_at=created_at,
            subject_scope=subject_scope,
        )
        self._persist_trace(
            query=query, dense_hits=dense_hits, sparse_hits=sparse_hits, merged=merged
        )
        answer_trace_id = self._persist_answer_trace(
            query_id=query_id,
            context_chunk_ids=trace_context_chunk_ids,
            answer_text=trace_answer_text,
            fallback_mode=fallback,
            model_name=trace_model_name,
            token_counts=trace_token_counts,
            latency_ms=trace_latency_ms,
        )
        self._log(
            query_id=query_id,
            community_id=community_id,
            model_name=model_name,
            dense_n=len(dense_hits),
            sparse_n=len(sparse_hits),
            merged_n=len(merged),
            fallback=fallback,
            answer_trace_id=answer_trace_id,
        )
        return AnswerResult(
            fallback=fallback,
            query_text=query_text,
            evidence=evidence,
            context=context,
            answer_text=answer_text,
            cited_chunk_ids=cited_chunk_ids,
        )

    def _persist_answer_trace(
        self,
        *,
        query_id: str,
        context_chunk_ids: tuple[str, ...],
        answer_text: str,
        fallback_mode: FallbackMode,
        model_name: str,
        token_counts: dict[str, int],
        latency_ms: int,
    ) -> str:
        """Persist one ``AnswerTrace`` row per ``/ask`` call (R-5, D-035).

        Every contour goes through this one entry point so the trace
        shape per ``FallbackMode`` matches the contract table in D-035
        by construction. ``prompt_version`` is the contract version in
        effect at the time of the call; it is recorded even on fallback
        modes where no prompt was sent because R-5 requires it.
        """
        trace = AnswerTrace(
            answer_trace_id=str(uuid4()),
            query_id=query_id,
            prompt_version=PROMPT_VERSION,
            context_chunk_ids=context_chunk_ids,
            answer_text=answer_text,
            fallback_mode=fallback_mode,
            model_name=model_name,
            token_counts=token_counts,
            latency_ms=latency_ms,
            created_at=datetime.now(tz=UTC),
        )
        self._repo.save_answer_trace(trace)
        return trace.answer_trace_id

    def _log(
        self,
        *,
        query_id: str,
        community_id: str,
        model_name: str,
        dense_n: int,
        sparse_n: int,
        merged_n: int,
        fallback: FallbackMode,
        answer_trace_id: str,
    ) -> None:
        log.info(
            "retrieval.hybrid query_id=%s community_id=%s model=%s "
            "dense_n=%d sparse_n=%d merged_n=%d fallback=%s "
            "answer_trace_id=%s",
            query_id,
            community_id,
            model_name,
            dense_n,
            sparse_n,
            merged_n,
            fallback.value,
            answer_trace_id,
        )

    def _persist_trace(
        self,
        *,
        query: Query,
        dense_hits: list[EventChunk],
        sparse_hits: list[EventChunk],
        merged: list[FusedHit],
    ) -> None:
        self._repo.save_query(query)
        hits: list[RetrievalHit] = build_retrieval_hits(
            query_id=query.query_id,
            model_name=query.model_name,
            created_at=query.created_at,
            candidates=RetrievedCandidates(
                dense=dense_hits,
                sparse=sparse_hits,
                merged=merged,
                embedding_model_name=query.model_name,
            ),
        )
        if hits:
            self._repo.save_retrieval_hits(hits)
