"""In-memory mock store for the diary domain.

Holds raw source messages, parsed notes, per-event chunks, and
per-chunk embedding records in process-local dicts.

``get_or_create_source_message`` enforces R-2 (D-023) by keying on the
``(external_chat_id, external_message_id, edit_seq)`` triple in a side
index; replays return the originally-persisted row.

Phase 3.1+3.2 (D-024): chunks carry an ``embedding_status`` field and
the store keeps ``EmbeddingRecord`` rows keyed on
``(chunk_id, model_name)``; ``EventChunk`` instances are reconstituted
on read with their current status so callers see the same shape as the
durable backends.

Slice 3.3 (D-025): baseline hybrid retrieval (``dense_candidates`` +
``sparse_candidates``) is implemented in process-local terms so unit
tests can exercise the hybrid path without a database. Dense ranks by
cosine distance over the deterministic mock embeddings; sparse ranks by
lowercased whitespace token-overlap count. Both legs are community-scoped
and restricted to chunks in ``ready`` state.

Not thread-safe. State lives only as long as the process.
"""

from __future__ import annotations

import math
import re
from dataclasses import replace

from memory_rag.core.chat.models import ChatKnowledgeSearch, ChatQueryRewrite, ChatRouteDecision
from memory_rag.core.domain.models import (
    AnswerTrace,
    DateRange,
    EventChunk,
    IndexingDeadLetter,
    LifecycleState,
    Note,
    Query,
    RetrievalHit,
    SourceMessage,
)
from memory_rag.core.embeddings.models import EmbeddingRecord, EmbeddingStatus
from memory_rag.core.routing import RouteKind

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_MOCK_DENSE_THRESHOLD = 0.5


def _tokenize(text: str) -> list[str]:
    return [m.group(0) for m in _TOKEN_RE.finditer(text.lower())]


def _chunk_in_date_range(chunk: EventChunk, date_range: DateRange | None) -> bool:
    """Inclusive ``note_date`` filter mirroring the Postgres predicate.

    ``None`` (and a both-bounds-``None`` range) imposes no constraint, so
    the leg output is identical to the pre-3.4 shape (Slice 3.4, D-040).
    """
    if date_range is None:
        return True
    if date_range.start is not None and chunk.note_date < date_range.start:
        return False
    return not (date_range.end is not None and chunk.note_date > date_range.end)


def _chunk_in_subject_scope(chunk: EventChunk, subject_scope: str | None) -> bool:
    """Strict ``subject_id`` filter mirroring the Postgres predicate.

    ``None`` imposes no constraint. A non-``None`` scope matches only
    chunks whose ``subject_id`` equals it: community-wide chunks
    (``subject_id is None``) are excluded (H-3, D-107).
    """
    return subject_scope is None or chunk.subject_id == subject_scope


class MockDomainStore:
    """Process-local store for ``SourceMessage``, ``Note``, ``EventChunk``."""

    def __init__(self) -> None:
        self._sources: dict[str, SourceMessage] = {}
        self._idempotency: dict[tuple[str, str, int], str] = {}
        self._notes: dict[str, Note] = {}
        self._chunks: dict[str, EventChunk] = {}
        self._embeddings: dict[tuple[str, str], EmbeddingRecord] = {}
        self._queries: dict[str, Query] = {}
        self._retrieval_hits: dict[str, RetrievalHit] = {}
        self._answer_traces: dict[str, AnswerTrace] = {}
        self._chat_route_decisions: dict[str, ChatRouteDecision] = {}
        # Rewrite traces keyed by decision_id — at most one per decision (RC-3).
        self._chat_query_rewrites: dict[str, ChatQueryRewrite] = {}
        # Knowledge-search traces keyed by decision_id — at most one per
        # decision (RC-4).
        self._chat_knowledge_searches: dict[str, ChatKnowledgeSearch] = {}
        self._dead_letters: dict[str, IndexingDeadLetter] = {}
        # Adapter-owned author display-input snapshots (D-084), keyed by the
        # message idempotency tuple, holding the raw (username, first_name).
        self._author_display_inputs: dict[tuple[str, str, int], tuple[str | None, str | None]] = {}

    def save_source_message(self, source: SourceMessage) -> None:
        key = (source.external_chat_id, source.external_message_id, source.edit_seq)
        if key in self._idempotency:
            raise ValueError(
                "duplicate source message for "
                f"(chat={source.external_chat_id}, msg={source.external_message_id}, "
                f"edit_seq={source.edit_seq}); use get_or_create_source_message"
            )
        self._sources[source.source_message_id] = source
        self._idempotency[key] = source.source_message_id

    def get_or_create_source_message(self, source: SourceMessage) -> tuple[SourceMessage, bool]:
        key = (source.external_chat_id, source.external_message_id, source.edit_seq)
        existing_id = self._idempotency.get(key)
        if existing_id is not None:
            return self._sources[existing_id], True
        self._sources[source.source_message_id] = source
        self._idempotency[key] = source.source_message_id
        return source, False

    def save_note(self, note: Note) -> None:
        self._notes[note.note_id] = note

    def save_event_chunks(self, chunks: list[EventChunk]) -> None:
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk

    def get_source_message(
        self, source_message_id: str, *, community_id: str
    ) -> SourceMessage | None:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        source = self._sources.get(source_message_id)
        if source is None or source.community_id != community_id:
            return None
        return source

    def list_source_messages(
        self, community_id: str, *, limit: int | None = None
    ) -> list[SourceMessage]:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        rows = [s for s in self._sources.values() if s.community_id == community_id]
        rows.sort(key=lambda s: (s.created_at, s.source_message_id))
        if limit is None:
            return rows
        if limit < 0:
            raise ValueError("limit must be non-negative")
        return rows[:limit]

    def list_recent_drafts(self, community_id: str, *, limit: int) -> list[SourceMessage]:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        if limit < 1:
            raise ValueError("limit must be >= 1")
        rows = [
            s
            for s in self._sources.values()
            if s.community_id == community_id and s.detected_route is RouteKind.DRAFT
        ]
        rows.sort(key=lambda s: (s.created_at, s.source_message_id), reverse=True)
        return rows[:limit]

    def get_note_by_source_message_id(self, source_message_id: str) -> Note | None:
        for note in self._notes.values():
            if note.source_message_id == source_message_id:
                return note
        return None

    def count_event_chunks_for_source(self, source_message_id: str) -> int:
        return sum(
            1 for chunk in self._chunks.values() if chunk.source_message_id == source_message_id
        )

    def get_event_chunk(self, chunk_id: str, *, community_id: str) -> EventChunk | None:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        chunk = self._chunks.get(chunk_id)
        if chunk is None or chunk.community_id != community_id:
            return None
        return chunk

    def dense_candidates(
        self,
        community_id: str,
        query_embedding: list[float],
        model_name: str,
        limit: int,
        *,
        date_range: DateRange | None = None,
        subject_scope: str | None = None,
    ) -> list[EventChunk]:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        if limit <= 0:
            return []

        # ``MockEmbeddingClient`` derives each vector from a SHA-256 of the
        # text, so the cosine distance between two unrelated texts at
        # dim=3072 clusters tightly around 1.0 (orthogonal) while identical
        # text gives 0.0. A distance threshold of 0.5 keeps the mock leg
        # honest: only chunks whose text is effectively identical to the
        # query qualify, matching what a real semantic retriever would do
        # while refusing to fabricate relevance from random vectors.
        ranked: list[tuple[float, int, EventChunk]] = []
        for index, chunk in enumerate(self._chunks.values()):
            if chunk.community_id != community_id:
                continue
            if chunk.lifecycle_state is not LifecycleState.ACTIVE:
                continue
            if not _chunk_in_date_range(chunk, date_range):
                continue
            if not _chunk_in_subject_scope(chunk, subject_scope):
                continue
            if chunk.embedding_status is not EmbeddingStatus.READY:
                continue
            record = self._embeddings.get((chunk.chunk_id, model_name))
            if record is None:
                continue
            distance = _cosine_distance(query_embedding, record.embedding)
            if distance >= _MOCK_DENSE_THRESHOLD:
                continue
            ranked.append((distance, index, chunk))
        ranked.sort(key=lambda triple: (triple[0], triple[1]))
        return [chunk for _, _, chunk in ranked[:limit]]

    def sparse_candidates(
        self,
        community_id: str,
        query_text: str,
        limit: int,
        *,
        date_range: DateRange | None = None,
        subject_scope: str | None = None,
    ) -> list[EventChunk]:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        if limit <= 0:
            return []
        query_tokens = set(_tokenize(query_text))
        if not query_tokens:
            return []

        ranked: list[tuple[int, int, EventChunk]] = []
        for index, chunk in enumerate(self._chunks.values()):
            if chunk.community_id != community_id:
                continue
            if chunk.lifecycle_state is not LifecycleState.ACTIVE:
                continue
            if not _chunk_in_date_range(chunk, date_range):
                continue
            if not _chunk_in_subject_scope(chunk, subject_scope):
                continue
            chunk_tokens = set(_tokenize(chunk.chunk_text))
            overlap = len(query_tokens & chunk_tokens)
            if overlap == 0:
                continue
            ranked.append((-overlap, index, chunk))
        ranked.sort(key=lambda triple: (triple[0], triple[1]))
        return [chunk for _, _, chunk in ranked[:limit]]

    def save_embedding_records(self, records: list[EmbeddingRecord]) -> None:
        for record in records:
            key = (record.chunk_id, record.model_name)
            if key in self._embeddings:
                raise ValueError(
                    f"duplicate embedding for chunk_id={record.chunk_id} "
                    f"model={record.model_name}"
                )
            self._embeddings[key] = record

    def count_embedding_records_for_source(self, source_message_id: str) -> int:
        return sum(
            1
            for record in self._embeddings.values()
            if record.source_message_id == source_message_id
        )

    def set_chunk_embedding_status(self, chunk_id: str, status: EmbeddingStatus) -> None:
        existing = self._chunks.get(chunk_id)
        if existing is None:
            raise KeyError(f"unknown chunk_id={chunk_id}")
        self._chunks[chunk_id] = replace(existing, embedding_status=status)

    def list_failed_event_chunks(
        self, community_id: str, *, limit: int | None = None
    ) -> list[EventChunk]:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        rows = [
            c
            for c in self._chunks.values()
            if c.community_id == community_id and c.embedding_status is EmbeddingStatus.FAILED
        ]
        rows.sort(key=lambda c: (c.created_at, c.chunk_id))
        if limit is None:
            return rows
        return rows[:limit]

    def save_query(self, query: Query) -> None:
        if query.query_id in self._queries:
            raise ValueError(f"duplicate query_id={query.query_id}")
        self._queries[query.query_id] = query

    def save_retrieval_hits(self, hits: list[RetrievalHit]) -> None:
        for hit in hits:
            if hit.retrieval_hit_id in self._retrieval_hits:
                raise ValueError(f"duplicate retrieval_hit_id={hit.retrieval_hit_id}")
            self._retrieval_hits[hit.retrieval_hit_id] = hit

    def get_query(self, query_id: str, *, community_id: str) -> Query | None:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        query = self._queries.get(query_id)
        if query is None or query.community_id != community_id:
            return None
        return query

    def get_retrieval_hits_for_query(
        self, query_id: str, *, community_id: str
    ) -> list[RetrievalHit]:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        # Scope via the parent query's community (the query_id -> queries join):
        # a RetrievalHit carries no community_id of its own. Fail closed when the
        # parent query is absent or owned by another community.
        parent = self._queries.get(query_id)
        if parent is None or parent.community_id != community_id:
            return []
        rows = [h for h in self._retrieval_hits.values() if h.query_id == query_id]
        rows.sort(key=lambda h: (h.leg.value, h.rank))
        return rows

    def save_answer_trace(self, trace: AnswerTrace) -> None:
        if trace.query_id in self._answer_traces:
            raise ValueError(f"duplicate answer_trace for query_id={trace.query_id}")
        self._answer_traces[trace.query_id] = trace

    def get_answer_trace_for_query(self, query_id: str, *, community_id: str) -> AnswerTrace | None:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        # Scope via the parent query's community (the query_id -> queries join):
        # answer_traces carries no community_id column. Fail closed when the
        # parent query is absent or owned by another community.
        parent = self._queries.get(query_id)
        if parent is None or parent.community_id != community_id:
            return None
        return self._answer_traces.get(query_id)

    def save_chat_route_decision(self, decision: ChatRouteDecision) -> None:
        if decision.decision_id in self._chat_route_decisions:
            raise ValueError(f"duplicate decision_id={decision.decision_id}")
        self._chat_route_decisions[decision.decision_id] = decision

    def get_chat_route_decision(
        self, decision_id: str, *, community_id: str
    ) -> ChatRouteDecision | None:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        decision = self._chat_route_decisions.get(decision_id)
        if decision is None or decision.community_id != community_id:
            return None
        return decision

    def save_chat_query_rewrite(self, rewrite: ChatQueryRewrite) -> None:
        if rewrite.decision_id in self._chat_query_rewrites:
            raise ValueError(f"duplicate rewrite for decision_id={rewrite.decision_id}")
        if rewrite.decision_id not in self._chat_route_decisions:
            raise ValueError(f"unknown decision_id={rewrite.decision_id}")
        self._chat_query_rewrites[rewrite.decision_id] = rewrite

    def get_chat_query_rewrite_for_decision(
        self, decision_id: str, *, community_id: str
    ) -> ChatQueryRewrite | None:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        rewrite = self._chat_query_rewrites.get(decision_id)
        if rewrite is None or rewrite.community_id != community_id:
            return None
        return rewrite

    def save_chat_knowledge_search(self, search: ChatKnowledgeSearch) -> None:
        if search.decision_id in self._chat_knowledge_searches:
            raise ValueError(f"duplicate knowledge search for decision_id={search.decision_id}")
        if search.decision_id not in self._chat_route_decisions:
            raise ValueError(f"unknown decision_id={search.decision_id}")
        self._chat_knowledge_searches[search.decision_id] = search

    def get_chat_knowledge_search_for_decision(
        self, decision_id: str, *, community_id: str
    ) -> ChatKnowledgeSearch | None:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        search = self._chat_knowledge_searches.get(decision_id)
        if search is None or search.community_id != community_id:
            return None
        return search

    def save_indexing_dead_letter(self, record: IndexingDeadLetter) -> None:
        if record.dead_letter_id in self._dead_letters:
            raise ValueError(f"duplicate dead_letter_id={record.dead_letter_id}")
        self._dead_letters[record.dead_letter_id] = record

    def list_indexing_dead_letters(
        self, community_id: str, *, limit: int | None = None
    ) -> list[IndexingDeadLetter]:
        if not community_id:
            raise ValueError("community_id is required (Runtime invariant R-3)")
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        rows = [d for d in self._dead_letters.values() if d.community_id == community_id]
        rows.sort(key=lambda d: (d.created_at, d.dead_letter_id), reverse=True)
        if limit is None:
            return rows
        return rows[:limit]

    def get_indexing_dead_letter(self, dead_letter_id: str) -> IndexingDeadLetter | None:
        return self._dead_letters.get(dead_letter_id)

    def save_author_display_input(
        self,
        *,
        external_chat_id: str,
        external_message_id: str,
        edit_seq: int,
        username: str | None,
        first_name: str | None,
    ) -> None:
        # Idempotent on the message tuple (R-2): an existing snapshot is left
        # untouched, never duplicated or silently mutated (D-084).
        key = (external_chat_id, external_message_id, edit_seq)
        if key in self._author_display_inputs:
            return
        self._author_display_inputs[key] = (username, first_name)

    def get_author_display_input(
        self,
        *,
        external_chat_id: str,
        external_message_id: str,
        edit_seq: int,
    ) -> tuple[str | None, str | None] | None:
        return self._author_display_inputs.get((external_chat_id, external_message_id, edit_seq))

    def len_sources(self) -> int:
        return len(self._sources)

    def len_notes(self) -> int:
        return len(self._notes)

    def len_chunks(self) -> int:
        return len(self._chunks)

    def len_embeddings(self) -> int:
        return len(self._embeddings)

    def len_queries(self) -> int:
        return len(self._queries)

    def len_retrieval_hits(self) -> int:
        return len(self._retrieval_hits)

    def len_answer_traces(self) -> int:
        return len(self._answer_traces)

    def len_chat_route_decisions(self) -> int:
        return len(self._chat_route_decisions)

    def len_chat_query_rewrites(self) -> int:
        return len(self._chat_query_rewrites)

    def len_chat_knowledge_searches(self) -> int:
        return len(self._chat_knowledge_searches)

    def len_indexing_dead_letters(self) -> int:
        return len(self._dead_letters)

    def clear(self) -> None:
        self._sources.clear()
        self._idempotency.clear()
        self._notes.clear()
        self._chunks.clear()
        self._embeddings.clear()
        self._queries.clear()
        self._retrieval_hits.clear()
        self._answer_traces.clear()
        self._chat_route_decisions.clear()
        self._chat_query_rewrites.clear()
        self._chat_knowledge_searches.clear()
        self._dead_letters.clear()
        self._author_display_inputs.clear()


def _cosine_distance(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"vector length mismatch: {len(a)} vs {len(b)}")
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 1.0
    return 1.0 - dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
