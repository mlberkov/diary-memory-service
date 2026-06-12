"""Pure unit tests for the notes-plus-model prompt contract (RC-3, D-108).

The builder is a deterministic mapping from ``AnswerContext`` to the
versioned ``notes-plus-model-v1`` prompt; the parser enforces the
segmented-provenance shape — required fields, fabricated-citation
rejection (I-9), and the consistency triple — while ignoring extra keys
(the RC-2 lenient-parse precedent). The escalation clause is byte-pinned
here: it is the D-108 medical-amendment invariant made live.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from memory_rag.core.chat import (
    ESCALATION_CLAUSE,
    NOTES_PLUS_MODEL_PROMPT_VERSION,
    NotesPlusModelAnswerError,
    build_notes_plus_model_prompt,
    parse_notes_plus_model_answer,
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


def _payload(
    *,
    notes_text: str = "He likes books.",
    cited: list[str] | None = None,
    model_text: str = "Stacking games suit this age.",
    uncertainty: str = "confident",
) -> dict[str, object]:
    return {
        "notes_text": notes_text,
        "cited_chunk_ids": cited if cited is not None else ["c-0"],
        "model_text": model_text,
        "notes_uncertainty": uncertainty,
    }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def test_build_prompt_pins_the_version_and_is_deterministic() -> None:
    context = _context(_chunk("c-0"))
    prompt_a = build_notes_plus_model_prompt(context)
    prompt_b = build_notes_plus_model_prompt(context)
    assert prompt_a.prompt_version == NOTES_PLUS_MODEL_PROMPT_VERSION == "notes-plus-model-v1"
    assert prompt_a == prompt_b


def test_every_chunk_appears_in_user_text_and_cited_ids_in_order() -> None:
    chunks = (
        _chunk("c-7", text="ate apples", event_index=0),
        _chunk("c-2", text="walked dog", event_index=1),
    )
    prompt = build_notes_plus_model_prompt(_context(*chunks))
    assert prompt.cited_chunk_ids == ("c-7", "c-2")
    assert "chunk_id=c-7" in prompt.user_text
    assert "chunk_id=c-2" in prompt.user_text
    assert "ate apples" in prompt.user_text
    assert prompt.user_text.index("c-7") < prompt.user_text.index("c-2")


def test_user_text_carries_the_original_question() -> None:
    prompt = build_notes_plus_model_prompt(_context(_chunk("c-0"), query_text="original q"))
    assert "Question: original q" in prompt.user_text


def test_empty_chunks_render_the_placeholder() -> None:
    prompt = build_notes_plus_model_prompt(_context())
    assert "(no note chunks were retrieved for this question)" in prompt.user_text
    assert prompt.cited_chunk_ids == ()


def test_system_text_demands_a_json_object() -> None:
    # The OpenAI chat adapter hardwires response_format=json_object (D-109).
    prompt = build_notes_plus_model_prompt(_context(_chunk("c-0")))
    assert "JSON object" in prompt.system_text


def test_cross_community_context_is_rejected() -> None:
    with pytest.raises(CrossCommunityContextError):
        build_notes_plus_model_prompt(
            _context(_chunk("c-0", community_id="fam-A"), _chunk("c-1", community_id="fam-B"))
        )


def test_escalation_clause_is_byte_pinned_and_present_verbatim() -> None:
    """The D-108 medical amendment + escalation prompt invariant, live for
    this route from RC-3. The clause is a shared constant so the RC-4
    knowledge-source route reuses it verbatim."""
    assert ESCALATION_CLAUSE == (
        "You may give general developmental information and activity "
        "suggestions. You must never give a diagnosis or interpret symptoms. "
        "If the question or the provided notes suggest a potential "
        "developmental or medical red flag, your answer must recommend "
        "consulting a qualified specialist."
    )
    prompt = build_notes_plus_model_prompt(_context(_chunk("c-0")))
    assert ESCALATION_CLAUSE in prompt.system_text


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parse_happy_path() -> None:
    context = _context(_chunk("c-0"))
    parsed = parse_notes_plus_model_answer(json.dumps(_payload()), context=context)
    assert parsed.notes_text == "He likes books."
    assert parsed.cited_chunk_ids == ("c-0",)
    assert parsed.model_text == "Stacking games suit this age."
    assert parsed.notes_uncertainty == "confident"


def test_parse_empty_notes_plane() -> None:
    context = _context()
    parsed = parse_notes_plus_model_answer(
        json.dumps(_payload(notes_text="", cited=[], uncertainty="no_evidence")),
        context=context,
    )
    assert parsed.notes_text == ""
    assert parsed.cited_chunk_ids == ()
    assert parsed.notes_uncertainty == "no_evidence"


def test_parse_ignores_extra_keys() -> None:
    payload = _payload()
    payload["confidence"] = 0.9
    parsed = parse_notes_plus_model_answer(json.dumps(payload), context=_context(_chunk("c-0")))
    assert parsed.notes_text == "He likes books."


def test_parse_rejects_invalid_json_and_non_objects() -> None:
    context = _context(_chunk("c-0"))
    with pytest.raises(NotesPlusModelAnswerError):
        parse_notes_plus_model_answer("{not json", context=context)
    with pytest.raises(NotesPlusModelAnswerError):
        parse_notes_plus_model_answer('["a list"]', context=context)


def test_parse_rejects_missing_fields_and_wrong_types() -> None:
    context = _context(_chunk("c-0"))
    incomplete = _payload()
    del incomplete["model_text"]
    with pytest.raises(NotesPlusModelAnswerError, match="missing"):
        parse_notes_plus_model_answer(json.dumps(incomplete), context=context)
    with pytest.raises(NotesPlusModelAnswerError, match="notes_text"):
        parse_notes_plus_model_answer(json.dumps(_payload() | {"notes_text": 7}), context=context)
    with pytest.raises(NotesPlusModelAnswerError, match="cited_chunk_ids"):
        parse_notes_plus_model_answer(
            json.dumps(_payload() | {"cited_chunk_ids": "c-0"}), context=context
        )
    with pytest.raises(NotesPlusModelAnswerError, match="model_text"):
        parse_notes_plus_model_answer(
            json.dumps(_payload() | {"model_text": None}), context=context
        )
    with pytest.raises(NotesPlusModelAnswerError, match="notes_uncertainty"):
        parse_notes_plus_model_answer(
            json.dumps(_payload(uncertainty="ambiguous")), context=context
        )


def test_parse_rejects_fabricated_citations() -> None:
    """I-9 at the contract boundary: a cited chunk must exist in the context."""
    context = _context(_chunk("c-0"))
    with pytest.raises(NotesPlusModelAnswerError, match="not present"):
        parse_notes_plus_model_answer(
            json.dumps(_payload(cited=["c-0", "c-fabricated"])), context=context
        )


def test_consistency_triple_no_evidence_requires_an_empty_notes_plane() -> None:
    context = _context(_chunk("c-0"))
    with pytest.raises(NotesPlusModelAnswerError, match="no_evidence"):
        parse_notes_plus_model_answer(
            json.dumps(_payload(uncertainty="no_evidence")), context=context
        )
    with pytest.raises(NotesPlusModelAnswerError, match="no_evidence"):
        parse_notes_plus_model_answer(
            json.dumps(_payload(notes_text="", cited=["c-0"], uncertainty="no_evidence")),
            context=context,
        )


def test_consistency_triple_a_nonempty_notes_plane_requires_citations_and_text() -> None:
    """A notes claim without a citation must never render as note-grounded."""
    context = _context(_chunk("c-0"))
    with pytest.raises(NotesPlusModelAnswerError, match="notes plane"):
        parse_notes_plus_model_answer(
            json.dumps(_payload(cited=[], uncertainty="confident")), context=context
        )
    with pytest.raises(NotesPlusModelAnswerError, match="notes plane"):
        parse_notes_plus_model_answer(
            json.dumps(_payload(notes_text="", uncertainty="uncertain")), context=context
        )
