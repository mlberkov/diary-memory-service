"""Pure unit tests for the notes-plus-knowledge prompt contract (RC-4, D-108).

The builder is a deterministic mapping from ``AnswerContext`` plus
knowledge excerpts to the versioned ``notes-plus-knowledge-v1`` prompt;
the parser enforces the segmented-provenance shape — required fields,
fabricated chunk-citation rejection (I-9), fabricated knowledge-ref
rejection, the RC-3 notes consistency triple, and the knowledge
consistency pair — while ignoring extra keys (the RC-2 lenient-parse
precedent). The escalation clause is pinned both by identity (imported,
not copied, from the RC-3 module) and by bytes.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

import memory_rag.core.chat.enriched_prompt as enriched_prompt
from memory_rag.core.chat import (
    ESCALATION_CLAUSE,
    NOTES_PLUS_KNOWLEDGE_PROMPT_VERSION,
    KnowledgeExcerpt,
    NotesPlusKnowledgeAnswerError,
    build_notes_plus_knowledge_prompt,
    parse_notes_plus_knowledge_answer,
)
from memory_rag.core.domain import AnswerContext, CrossCommunityContextError, EventChunk
from memory_rag.core.embeddings.models import EmbeddingStatus


def _chunk(
    chunk_id: str,
    *,
    community_id: str = "fam-A",
    text: str = "event text",
    event_index: int = 0,
    note_date: date = date(2026, 5, 9),
) -> EventChunk:
    return EventChunk(
        chunk_id=chunk_id,
        note_id=f"note-{chunk_id}",
        source_message_id=f"src-{chunk_id}",
        community_id=community_id,
        author_user_id="user-1",
        note_date=note_date,
        event_index=event_index,
        chunk_text=text,
        created_at=datetime(2026, 5, 9, 8, 0, tzinfo=UTC),
        embedding_status=EmbeddingStatus.READY,
    )


def _context(*chunks: EventChunk, query_text: str = "what games suit him?") -> AnswerContext:
    return AnswerContext(
        query_id="q-1",
        query_text=query_text,
        ordered_chunks=tuple(chunks),
        model_name="mock",
        created_at=datetime(2026, 5, 12, 12, 0, tzinfo=UTC),
    )


_EXCERPTS = (
    KnowledgeExcerpt(ref="https://example.org/a", title="A", text="alpha facts"),
    KnowledgeExcerpt(ref="https://example.org/b", title="B", text="beta facts"),
)


def _payload(
    *,
    notes_text: str = "He likes books.",
    cited: list[str] | None = None,
    knowledge_text: str = "Experts suggest stacking games.",
    refs: list[str] | None = None,
    model_text: str = "General guidance.",
    uncertainty: str = "confident",
) -> dict[str, object]:
    return {
        "notes_text": notes_text,
        "cited_chunk_ids": cited if cited is not None else ["c-0"],
        "knowledge_text": knowledge_text,
        "cited_knowledge_refs": refs if refs is not None else ["https://example.org/a"],
        "model_text": model_text,
        "notes_uncertainty": uncertainty,
    }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def test_build_prompt_pins_the_version_and_is_deterministic() -> None:
    context = _context(_chunk("c-0"))
    prompt_a = build_notes_plus_knowledge_prompt(context, _EXCERPTS)
    prompt_b = build_notes_plus_knowledge_prompt(context, _EXCERPTS)
    assert (
        prompt_a.prompt_version == NOTES_PLUS_KNOWLEDGE_PROMPT_VERSION == "notes-plus-knowledge-v1"
    )
    assert prompt_a == prompt_b


def test_chunks_and_excerpts_render_with_their_ids_and_refs() -> None:
    chunks = (_chunk("c-7", text="ate apples"), _chunk("c-2", text="walked dog", event_index=1))
    prompt = build_notes_plus_knowledge_prompt(_context(*chunks), _EXCERPTS)
    assert prompt.cited_chunk_ids == ("c-7", "c-2")
    assert prompt.knowledge_refs == ("https://example.org/a", "https://example.org/b")
    assert "chunk_id=c-7" in prompt.user_text
    assert "ref=https://example.org/a" in prompt.user_text
    assert "title=A" in prompt.user_text
    assert "alpha facts" in prompt.user_text


def test_user_text_carries_the_original_question() -> None:
    prompt = build_notes_plus_knowledge_prompt(
        _context(_chunk("c-0"), query_text="original q"), _EXCERPTS
    )
    assert "Question: original q" in prompt.user_text


def test_empty_chunks_and_empty_excerpts_render_both_placeholders() -> None:
    prompt = build_notes_plus_knowledge_prompt(_context(), ())
    assert "(no note chunks were retrieved for this question)" in prompt.user_text
    assert "(no knowledge excerpts were retrieved for this question)" in prompt.user_text
    assert prompt.cited_chunk_ids == ()
    assert prompt.knowledge_refs == ()


def test_cross_community_context_is_rejected() -> None:
    context = _context(_chunk("c-0", community_id="fam-A"), _chunk("c-1", community_id="fam-B"))
    with pytest.raises(CrossCommunityContextError):
        build_notes_plus_knowledge_prompt(context, _EXCERPTS)


def test_system_text_names_json_and_all_six_fields() -> None:
    prompt = build_notes_plus_knowledge_prompt(_context(_chunk("c-0")), _EXCERPTS)
    assert "JSON" in prompt.system_text
    for fieldname in (
        "notes_text",
        "cited_chunk_ids",
        "knowledge_text",
        "cited_knowledge_refs",
        "model_text",
        "notes_uncertainty",
    ):
        assert fieldname in prompt.system_text


def test_escalation_clause_is_the_shared_constant_and_byte_pinned() -> None:
    """RC-4 reuses the RC-3 clause verbatim — imported, not copied (D-110);
    the built system text embeds the exact RC-3 constant object's bytes."""
    assert ESCALATION_CLAUSE is enriched_prompt.ESCALATION_CLAUSE
    assert ESCALATION_CLAUSE == (
        "You may give general developmental information and activity "
        "suggestions. You must never give a diagnosis or interpret symptoms. "
        "If the question or the provided notes suggest a potential "
        "developmental or medical red flag, your answer must recommend "
        "consulting a qualified specialist."
    )
    prompt = build_notes_plus_knowledge_prompt(_context(_chunk("c-0")), _EXCERPTS)
    assert enriched_prompt.ESCALATION_CLAUSE in prompt.system_text


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _parse(payload: dict[str, object], *chunks: EventChunk, refs: tuple[str, ...] = ()) -> object:
    context = _context(*chunks)
    offered = refs if refs else tuple(e.ref for e in _EXCERPTS)
    return parse_notes_plus_knowledge_answer(
        json.dumps(payload), context=context, knowledge_refs=offered
    )


def test_parse_valid_six_field_answer() -> None:
    parsed = parse_notes_plus_knowledge_answer(
        json.dumps(_payload()),
        context=_context(_chunk("c-0")),
        knowledge_refs=tuple(e.ref for e in _EXCERPTS),
    )
    assert parsed.notes_text == "He likes books."
    assert parsed.cited_chunk_ids == ("c-0",)
    assert parsed.knowledge_text == "Experts suggest stacking games."
    assert parsed.cited_knowledge_refs == ("https://example.org/a",)
    assert parsed.model_text == "General guidance."
    assert parsed.notes_uncertainty == "confident"


def test_parse_ignores_extra_keys() -> None:
    payload = _payload()
    payload["confidence"] = 0.9
    parsed = parse_notes_plus_knowledge_answer(
        json.dumps(payload),
        context=_context(_chunk("c-0")),
        knowledge_refs=tuple(e.ref for e in _EXCERPTS),
    )
    assert parsed.model_text == "General guidance."


@pytest.mark.parametrize(
    "missing",
    [
        "notes_text",
        "cited_chunk_ids",
        "knowledge_text",
        "cited_knowledge_refs",
        "model_text",
        "notes_uncertainty",
    ],
)
def test_parse_rejects_a_missing_required_field(missing: str) -> None:
    payload = _payload()
    del payload[missing]
    with pytest.raises(NotesPlusKnowledgeAnswerError, match="missing required fields"):
        _parse(payload, _chunk("c-0"))


def test_parse_rejects_non_json_and_non_object() -> None:
    context = _context(_chunk("c-0"))
    with pytest.raises(NotesPlusKnowledgeAnswerError, match="not valid JSON"):
        parse_notes_plus_knowledge_answer("not json", context=context, knowledge_refs=())
    with pytest.raises(NotesPlusKnowledgeAnswerError, match="JSON object"):
        parse_notes_plus_knowledge_answer("[1, 2]", context=context, knowledge_refs=())


def test_parse_rejects_a_fabricated_chunk_citation() -> None:
    with pytest.raises(NotesPlusKnowledgeAnswerError, match="cited_chunk_ids not present"):
        _parse(_payload(cited=["c-fabricated"]), _chunk("c-0"))


def test_parse_rejects_a_fabricated_knowledge_ref() -> None:
    with pytest.raises(NotesPlusKnowledgeAnswerError, match="cited_knowledge_refs not present"):
        _parse(_payload(refs=["https://fabricated.example.org"]), _chunk("c-0"))


def test_with_no_offered_excerpts_any_cited_ref_is_fabricated() -> None:
    """The failed-search contour is structurally honest: an empty excerpt
    set makes every knowledge citation fail closed."""
    with pytest.raises(NotesPlusKnowledgeAnswerError, match="cited_knowledge_refs not present"):
        _parse(_payload(), _chunk("c-0"), refs=("",))  # offered set without the cited ref


def test_notes_consistency_triple_holds_in_both_directions() -> None:
    # no_evidence requires an empty notes plane.
    with pytest.raises(NotesPlusKnowledgeAnswerError, match="no_evidence"):
        _parse(_payload(uncertainty="no_evidence"), _chunk("c-0"))
    # An empty notes plane requires no_evidence.
    with pytest.raises(NotesPlusKnowledgeAnswerError, match="notes plane"):
        _parse(_payload(notes_text="", cited=[]), _chunk("c-0"))
    # A claim without a citation never renders as note-grounded.
    with pytest.raises(NotesPlusKnowledgeAnswerError, match="notes plane"):
        _parse(_payload(cited=[]), _chunk("c-0"))


def test_knowledge_consistency_pair_holds_in_both_directions() -> None:
    # Text without refs never renders as knowledge-grounded.
    with pytest.raises(NotesPlusKnowledgeAnswerError, match="knowledge plane"):
        _parse(_payload(refs=[]), _chunk("c-0"))
    # Refs without text are unusable.
    with pytest.raises(NotesPlusKnowledgeAnswerError, match="knowledge plane"):
        _parse(_payload(knowledge_text=""), _chunk("c-0"))


def test_an_empty_knowledge_plane_with_empty_refs_is_valid() -> None:
    parsed = parse_notes_plus_knowledge_answer(
        json.dumps(_payload(knowledge_text="", refs=[])),
        context=_context(_chunk("c-0")),
        knowledge_refs=(),
    )
    assert parsed.knowledge_text == ""
    assert parsed.cited_knowledge_refs == ()


def test_parse_rejects_an_unknown_uncertainty_marker() -> None:
    with pytest.raises(NotesPlusKnowledgeAnswerError, match="notes_uncertainty"):
        _parse(_payload(uncertainty="ambiguous"), _chunk("c-0"))
