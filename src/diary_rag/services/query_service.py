"""Channel-neutral query service — baseline hybrid retrieval (D-025).

Embeds the query, runs the dense leg (vector similarity, family-scoped,
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
writes the ``Query`` row with zero hits. Answer-side ``AnswerTrace``
persistence remains deferred to Phase 4.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from diary_rag.core.diary import (
    AnswerResult,
    Evidence,
    FallbackMode,
    Query,
    RetrievalHit,
    RetrievalLeg,
)
from diary_rag.core.diary.models import EventChunk
from diary_rag.core.embeddings import EmbeddingClient
from diary_rag.core.routing import InboundMessage
from diary_rag.logging import get_logger
from diary_rag.services.retrieval import DEFAULT_RRF_K, FusedHit, reciprocal_rank_fusion
from diary_rag.storage.repository import DiaryRepository
from diary_rag.storage.search_repository import SearchRepository

log = get_logger(__name__)

DEFAULT_TOP_K = 5
DEFAULT_CANDIDATE_K = 20

_TRAILING_QUERY_PUNCT = "?.!,;:"
_SPARSE_MODEL_NAME = "simple"


def _normalize_query(payload: str) -> str:
    """Trim whitespace and terminal punctuation so plain questions match cleanly."""
    return payload.strip().rstrip(_TRAILING_QUERY_PUNCT).strip()


def _per_leg_score(rank: int, k: int = DEFAULT_RRF_K) -> float:
    """RRF contribution at a 1-based ``rank``."""
    return 1.0 / (k + rank)


class QueryService:
    """Answers an ``InboundMessage`` carrying an ``/ask`` payload."""

    def __init__(
        self,
        repo: DiaryRepository,
        search_repo: SearchRepository,
        embedding_client: EmbeddingClient,
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
        self._top_k = top_k
        self._candidate_k = candidate_k

    def answer(self, message: InboundMessage) -> AnswerResult:
        family_id = message.external_chat_id
        if not family_id:
            raise ValueError("InboundMessage.external_chat_id is required (R-3)")

        query_text = _normalize_query(message.payload)
        now = datetime.now(tz=UTC)
        query_id = str(uuid4())
        model_name = self._embed.model_name

        if not query_text:
            self._persist_trace(
                query_id=query_id,
                family_id=family_id,
                query_text=query_text,
                model_name=model_name,
                fallback=FallbackMode.NO_EVIDENCE,
                created_at=now,
                dense_hits=[],
                sparse_hits=[],
                merged=[],
            )
            log.info(
                "retrieval.hybrid query_id=%s family_id=%s model=%s "
                "dense_n=0 sparse_n=0 merged_n=0 fallback=no_evidence",
                query_id,
                family_id,
                model_name,
            )
            return AnswerResult(fallback=FallbackMode.NO_EVIDENCE, query_text=query_text)

        query_embedding = self._embed.embed([query_text])[0]

        dense_hits = self._search.dense_candidates(
            family_id, query_embedding, model_name, self._candidate_k
        )
        sparse_hits = self._search.sparse_candidates(family_id, query_text, self._candidate_k)
        merged = reciprocal_rank_fusion([dense_hits, sparse_hits], top_k=self._top_k)

        fallback = FallbackMode.NONE if merged else FallbackMode.NO_EVIDENCE
        self._persist_trace(
            query_id=query_id,
            family_id=family_id,
            query_text=query_text,
            model_name=model_name,
            fallback=fallback,
            created_at=now,
            dense_hits=dense_hits,
            sparse_hits=sparse_hits,
            merged=merged,
        )

        log.info(
            "retrieval.hybrid query_id=%s family_id=%s model=%s "
            "dense_n=%d sparse_n=%d merged_n=%d fallback=%s",
            query_id,
            family_id,
            model_name,
            len(dense_hits),
            len(sparse_hits),
            len(merged),
            fallback.value,
        )

        if not merged:
            return AnswerResult(fallback=FallbackMode.NO_EVIDENCE, query_text=query_text)

        evidence = [
            Evidence(
                chunk_id=h.chunk.chunk_id,
                entry_date=h.chunk.entry_date,
                chunk_text=h.chunk.chunk_text,
            )
            for h in merged
        ]
        return AnswerResult(fallback=FallbackMode.NONE, query_text=query_text, evidence=evidence)

    def _persist_trace(
        self,
        *,
        query_id: str,
        family_id: str,
        query_text: str,
        model_name: str,
        fallback: FallbackMode,
        created_at: datetime,
        dense_hits: list[EventChunk],
        sparse_hits: list[EventChunk],
        merged: list[FusedHit],
    ) -> None:
        query = Query(
            query_id=query_id,
            family_id=family_id,
            query_text=query_text,
            model_name=model_name,
            fallback=fallback,
            created_at=created_at,
        )
        self._repo.save_query(query)

        hits: list[RetrievalHit] = []
        for rank, chunk in enumerate(dense_hits, start=1):
            hits.append(
                RetrievalHit(
                    retrieval_hit_id=str(uuid4()),
                    query_id=query_id,
                    chunk_id=chunk.chunk_id,
                    leg=RetrievalLeg.DENSE,
                    rank=rank,
                    score=_per_leg_score(rank),
                    model_name=model_name,
                    created_at=created_at,
                )
            )
        for rank, chunk in enumerate(sparse_hits, start=1):
            hits.append(
                RetrievalHit(
                    retrieval_hit_id=str(uuid4()),
                    query_id=query_id,
                    chunk_id=chunk.chunk_id,
                    leg=RetrievalLeg.SPARSE,
                    rank=rank,
                    score=_per_leg_score(rank),
                    model_name=_SPARSE_MODEL_NAME,
                    created_at=created_at,
                )
            )
        for rank, fused in enumerate(merged, start=1):
            hits.append(
                RetrievalHit(
                    retrieval_hit_id=str(uuid4()),
                    query_id=query_id,
                    chunk_id=fused.chunk.chunk_id,
                    leg=RetrievalLeg.MERGED,
                    rank=rank,
                    score=fused.score,
                    model_name=model_name,
                    created_at=created_at,
                )
            )
        if hits:
            self._repo.save_retrieval_hits(hits)
