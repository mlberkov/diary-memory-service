"""Channel-neutral query service.

Reads chunks from the mock store using a deterministic substring match,
scoped to the inbound message's family. Empty matches surface
``NO_EVIDENCE`` rather than fabricating an answer (Invariant I-9, runtime
R-5/R-6).
"""

from __future__ import annotations

from diary_rag.core.diary import AnswerResult, Evidence, FallbackMode
from diary_rag.core.routing import InboundMessage
from diary_rag.storage.mock import MockDiaryStore

DEFAULT_TOP_K = 5

_TRAILING_QUERY_PUNCT = "?.!,;:"


def _normalize_query(payload: str) -> str:
    """Trim whitespace and terminal punctuation so ``"recipe?"`` matches ``"recipe"``.

    The mock store does case-insensitive substring match (`MockDiaryStore.search_chunks`);
    a trailing ``?`` from a plain-text question would otherwise fail to match a chunk that
    has no punctuation. This is the smallest normalization needed for the heuristic-ASK
    smoke; semantic expansion and token ranking remain out of scope.
    """
    return payload.strip().rstrip(_TRAILING_QUERY_PUNCT).strip()


class QueryService:
    """Answers an ``InboundMessage`` carrying an ``/ask`` payload."""

    def __init__(self, store: MockDiaryStore, top_k: int = DEFAULT_TOP_K) -> None:
        self._store = store
        self._top_k = top_k

    def answer(self, message: InboundMessage) -> AnswerResult:
        family_id = message.external_chat_id
        if not family_id:
            raise ValueError("InboundMessage.external_chat_id is required (R-3)")

        query_text = _normalize_query(message.payload)

        if not query_text:
            return AnswerResult(fallback=FallbackMode.NO_EVIDENCE, query_text=query_text)

        hits = self._store.search_chunks(family_id, query_text, top_k=self._top_k)
        if not hits:
            return AnswerResult(fallback=FallbackMode.NO_EVIDENCE, query_text=query_text)

        evidence = [
            Evidence(chunk_id=c.chunk_id, entry_date=c.entry_date, chunk_text=c.chunk_text)
            for c in hits
        ]
        return AnswerResult(fallback=FallbackMode.NONE, query_text=query_text, evidence=evidence)
