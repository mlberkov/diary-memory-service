"""Retrieval seam for baseline hybrid search (Slice 3.3).

``SearchRepository`` is the channel-neutral retrieval Protocol used by
``QueryService``. It exposes two independent ranked legs — dense (vector
similarity over persisted embeddings) and sparse (PostgreSQL FTS
baseline) — that the service layer fuses via Reciprocal Rank Fusion
(``services.retrieval``). Backends return chunks already ordered best-
first; the protocol does not surface backend-native scores because the
fusion code uses ranks, not calibrated scores.

Postgres (D-022) is the only canonical retrieval backend. The mock
implementation is deterministic and family-scoped so unit tests can
exercise the hybrid path end-to-end without a database. SQLite is opt-in
for ingest only (D-022); both retrieval methods raise
``NotImplementedError`` there, which ``Dispatcher`` converts to
``FallbackMode.NO_EVIDENCE``.

BM25, reranking, and dedicated vector-search systems are explicitly
deferred to the next quality-decision packet.
"""

from __future__ import annotations

from typing import Protocol

from diary_rag.core.diary.models import DateRange, EventChunk
from diary_rag.storage.repository import DiaryRepository


class SearchRepository(Protocol):
    """Per-backend dense + sparse candidate retrieval (Slice 3.3)."""

    def dense_candidates(
        self,
        family_id: str,
        query_embedding: list[float],
        model_name: str,
        limit: int,
        *,
        date_range: DateRange | None = None,
    ) -> list[EventChunk]:
        """Return up to ``limit`` chunks ranked by vector similarity.

        Family-scoped (I-7, R-3). Only chunks with
        ``embedding_status == 'ready'`` participate. The ``model_name``
        filter is what ties the query vector to the persisted vectors:
        a chunk indexed under a different model is not a candidate for
        this query.

        When ``date_range`` is given, only chunks whose ``entry_date``
        falls within its inclusive bounds participate; ``None`` (the
        default) applies no date constraint and preserves the D-025
        retrieval shape (Slice 3.4, D-040).
        """

    def sparse_candidates(
        self,
        family_id: str,
        query_text: str,
        limit: int,
        *,
        date_range: DateRange | None = None,
    ) -> list[EventChunk]:
        """Return up to ``limit`` chunks ranked by PostgreSQL FTS baseline.

        Family-scoped (I-7, R-3). Tokenization is whatever the backend
        configures — for Postgres, ``to_tsvector('simple', ...)``;
        ``websearch_to_tsquery('simple', ...)`` parses the query.

        When ``date_range`` is given, only chunks whose ``entry_date``
        falls within its inclusive bounds participate; ``None`` (the
        default) applies no date constraint and preserves the D-025
        retrieval shape (Slice 3.4, D-040).
        """


class HybridDiaryStore(DiaryRepository, SearchRepository, Protocol):
    """Combined ingest + retrieval seam.

    The three concrete stores (mock, sqlite, postgres) each satisfy both
    Protocols structurally; this combined name lets the webhook
    construct one store object and pass it to both ``DiaryService`` (as
    ``DiaryRepository``) and ``QueryService`` (as ``SearchRepository``)
    without losing the static-type guarantee at either call site.
    SQLite raises ``NotImplementedError`` from the retrieval methods —
    valid structurally; the dispatcher translates it to NO_EVIDENCE.
    """
