"""Pure unit tests for the channel-neutral context assembler (Slice 4.1).

The assembler is intentionally a thin mapping: a persisted ``Query``
plus the RRF-merged ``FusedHit`` list collapses to a minimal
``AnswerContext`` (query identity, normalized text, ordered chunks,
embedding model name, timestamp). RRF already dedupes and tie-breaks,
so these tests only assert order preservation, identity propagation,
and the empty-input shape.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from diary_rag.core.diary import (
    AnswerContext,
    EventChunk,
    FallbackMode,
    Query,
)
from diary_rag.core.embeddings.models import EmbeddingStatus
from diary_rag.services.context_assembler import assemble_answer_context
from diary_rag.services.retrieval import FusedHit


def _chunk(chunk_id: str, *, text: str = "event", event_index: int = 0) -> EventChunk:
    return EventChunk(
        chunk_id=chunk_id,
        diary_entry_id=f"entry-{chunk_id}",
        source_message_id=f"src-{chunk_id}",
        family_id="fam-A",
        author_user_id="user-1",
        entry_date=date(2026, 5, 9),
        event_index=event_index,
        chunk_text=text,
        created_at=datetime(2026, 5, 9, 8, 0, tzinfo=UTC),
        embedding_status=EmbeddingStatus.READY,
    )


def _query(
    *,
    query_id: str = "q-1",
    query_text: str = "book",
    model_name: str = "mock",
    fallback: FallbackMode = FallbackMode.NONE,
    created_at: datetime | None = None,
) -> Query:
    return Query(
        query_id=query_id,
        family_id="fam-A",
        query_text=query_text,
        model_name=model_name,
        fallback=fallback,
        created_at=created_at or datetime(2026, 5, 12, 12, 0, tzinfo=UTC),
    )


def test_assemble_preserves_query_identity_fields() -> None:
    query = _query(
        query_id="q-42",
        query_text="recipe",
        model_name="mock",
        created_at=datetime(2026, 5, 12, 9, 30, tzinfo=UTC),
    )

    context = assemble_answer_context(query, [])

    assert isinstance(context, AnswerContext)
    assert context.query_id == "q-42"
    assert context.query_text == "recipe"
    assert context.model_name == "mock"
    assert context.created_at == datetime(2026, 5, 12, 9, 30, tzinfo=UTC)


def test_assemble_empty_merged_yields_empty_ordered_chunks() -> None:
    context = assemble_answer_context(_query(), [])

    assert context.ordered_chunks == ()


def test_assemble_preserves_merged_rank_order() -> None:
    chunks = [_chunk(f"c-{i}", event_index=i) for i in range(3)]
    merged = [
        FusedHit(chunk=chunks[2], score=0.20),
        FusedHit(chunk=chunks[0], score=0.10),
        FusedHit(chunk=chunks[1], score=0.05),
    ]

    context = assemble_answer_context(_query(), merged)

    assert [c.chunk_id for c in context.ordered_chunks] == ["c-2", "c-0", "c-1"]
    # Identity is preserved — the assembler does not rebuild EventChunk values.
    assert context.ordered_chunks[0] is chunks[2]


def test_assemble_returns_immutable_tuple_of_chunks() -> None:
    chunks = [_chunk("c-0"), _chunk("c-1")]
    merged = [FusedHit(chunk=chunks[0], score=0.1), FusedHit(chunk=chunks[1], score=0.05)]

    context = assemble_answer_context(_query(), merged)

    assert isinstance(context.ordered_chunks, tuple)
    assert len(context.ordered_chunks) == 2


def test_assemble_carries_no_evidence_fallback_unchanged() -> None:
    """``fallback`` lives on Query (and AnswerResult), not on AnswerContext.

    The assembler is a presentation-free mapping: the same chunk shape
    is returned regardless of which fallback the persisted ``Query``
    recorded. Consumers read ``fallback`` from ``AnswerResult``.
    """
    query = _query(fallback=FallbackMode.NO_EVIDENCE, query_text="")

    context = assemble_answer_context(query, [])

    assert context.query_text == ""
    assert context.ordered_chunks == ()
