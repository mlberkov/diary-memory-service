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
"""

from __future__ import annotations

from diary_rag.core.diary import AnswerResult, Evidence, FallbackMode
from diary_rag.core.embeddings import EmbeddingClient
from diary_rag.core.routing import InboundMessage
from diary_rag.logging import get_logger
from diary_rag.services.retrieval import reciprocal_rank_fusion
from diary_rag.storage.search_repository import SearchRepository

log = get_logger(__name__)

DEFAULT_TOP_K = 5
DEFAULT_CANDIDATE_K = 20

_TRAILING_QUERY_PUNCT = "?.!,;:"


def _normalize_query(payload: str) -> str:
    """Trim whitespace and terminal punctuation so plain questions match cleanly."""
    return payload.strip().rstrip(_TRAILING_QUERY_PUNCT).strip()


class QueryService:
    """Answers an ``InboundMessage`` carrying an ``/ask`` payload."""

    def __init__(
        self,
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
        self._search = search_repo
        self._embed = embedding_client
        self._top_k = top_k
        self._candidate_k = candidate_k

    def answer(self, message: InboundMessage) -> AnswerResult:
        family_id = message.external_chat_id
        if not family_id:
            raise ValueError("InboundMessage.external_chat_id is required (R-3)")

        query_text = _normalize_query(message.payload)
        if not query_text:
            return AnswerResult(fallback=FallbackMode.NO_EVIDENCE, query_text=query_text)

        query_embedding = self._embed.embed([query_text])[0]
        model_name = self._embed.model_name

        dense_hits = self._search.dense_candidates(
            family_id, query_embedding, model_name, self._candidate_k
        )
        sparse_hits = self._search.sparse_candidates(family_id, query_text, self._candidate_k)
        merged = reciprocal_rank_fusion([dense_hits, sparse_hits], top_k=self._top_k)

        log.info(
            "retrieval.hybrid family_id=%s model=%s dense_n=%d sparse_n=%d merged_n=%d",
            family_id,
            model_name,
            len(dense_hits),
            len(sparse_hits),
            len(merged),
        )

        if not merged:
            return AnswerResult(fallback=FallbackMode.NO_EVIDENCE, query_text=query_text)

        evidence = [
            Evidence(chunk_id=c.chunk_id, entry_date=c.entry_date, chunk_text=c.chunk_text)
            for c in merged
        ]
        return AnswerResult(fallback=FallbackMode.NONE, query_text=query_text, evidence=evidence)
