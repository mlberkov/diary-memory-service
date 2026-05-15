"""Pure unit tests for the versioned answer prompt contract (Slice 4.2).

The prompt builder is a deterministic mapping from ``AnswerContext`` to a
versioned ``AnswerPrompt``. Tests cover determinism, version pinning,
chunk_id propagation, the R-8 single-family assertion, and the empty
``ordered_chunks`` placeholder.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from diary_rag.core.domain import (
    PROMPT_VERSION,
    AnswerContext,
    AnswerPrompt,
    CrossFamilyContextError,
    EventChunk,
    build_answer_prompt,
)
from diary_rag.core.embeddings.models import EmbeddingStatus


def _chunk(
    chunk_id: str,
    *,
    family_id: str = "fam-A",
    text: str = "event text",
    event_index: int = 0,
    note_date: date = date(2026, 5, 9),
) -> EventChunk:
    return EventChunk(
        chunk_id=chunk_id,
        note_id=f"note-{chunk_id}",
        source_message_id=f"src-{chunk_id}",
        family_id=family_id,
        author_user_id="user-1",
        note_date=note_date,
        event_index=event_index,
        chunk_text=text,
        created_at=datetime(2026, 5, 9, 8, 0, tzinfo=UTC),
        embedding_status=EmbeddingStatus.READY,
    )


def _context(*chunks: EventChunk, query_text: str = "what did I read?") -> AnswerContext:
    return AnswerContext(
        query_id="q-1",
        query_text=query_text,
        ordered_chunks=tuple(chunks),
        model_name="mock",
        created_at=datetime(2026, 5, 12, 12, 0, tzinfo=UTC),
    )


def test_build_prompt_is_deterministic() -> None:
    chunks = (_chunk("c-0", text="read book A"), _chunk("c-1", text="read book B"))
    context_a = _context(*chunks)
    context_b = _context(*chunks)

    prompt_a = build_answer_prompt(context_a)
    prompt_b = build_answer_prompt(context_b)

    assert prompt_a == prompt_b


def test_prompt_carries_version_constant() -> None:
    prompt = build_answer_prompt(_context(_chunk("c-0")))

    assert isinstance(prompt, AnswerPrompt)
    assert prompt.prompt_version == PROMPT_VERSION
    assert prompt.prompt_version == "v1"


def test_every_chunk_appears_in_user_text_and_cited_ids_in_order() -> None:
    chunks = (
        _chunk("c-7", text="ate apples", event_index=0),
        _chunk("c-2", text="walked dog", event_index=1),
        _chunk("c-9", text="read book", event_index=2),
    )
    context = _context(*chunks)

    prompt = build_answer_prompt(context)

    assert prompt.cited_chunk_ids == ("c-7", "c-2", "c-9")
    for chunk in chunks:
        assert f"chunk_id={chunk.chunk_id}" in prompt.user_text
        assert chunk.chunk_text in prompt.user_text
        assert chunk.note_date.isoformat() in prompt.user_text


def test_prompt_includes_query_text_in_user_section() -> None:
    context = _context(_chunk("c-0"), query_text="когда я читал?")

    prompt = build_answer_prompt(context)

    assert "когда я читал?" in prompt.user_text


def test_cross_family_context_raises() -> None:
    chunks = (
        _chunk("c-0", family_id="fam-A"),
        _chunk("c-1", family_id="fam-B"),
    )
    context = _context(*chunks)

    with pytest.raises(CrossFamilyContextError) as excinfo:
        build_answer_prompt(context)

    assert "fam-A" in str(excinfo.value)
    assert "fam-B" in str(excinfo.value)


def test_empty_context_renders_no_evidence_placeholder() -> None:
    context = _context(query_text="anything?")

    prompt = build_answer_prompt(context)

    assert prompt.cited_chunk_ids == ()
    assert "no diary chunks were retrieved" in prompt.user_text
    assert prompt.prompt_version == PROMPT_VERSION


def test_system_text_instructs_structured_output_shape() -> None:
    prompt = build_answer_prompt(_context(_chunk("c-0")))

    for field_name in ("answer_text", "cited_chunk_ids", "uncertainty"):
        assert field_name in prompt.system_text
    for marker in ("confident", "uncertain", "no_evidence"):
        assert marker in prompt.system_text
