"""Pure unit tests for the structured-answer parser (Slice 4.2).

The parser is the contract boundary that enforces I-9: cited chunk_ids
must be a subset of ``AnswerContext.ordered_chunks``. Tests cover the
happy round-trip, malformed JSON, missing/extra/wrong-typed fields,
fabricated citations, and the no-evidence empty-citations rule.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from diary_rag.core.diary import (
    AnswerContext,
    AnswerSchemaMismatchError,
    EventChunk,
    FabricatedCitationError,
    MalformedAnswerJSONError,
    StructuredAnswer,
    parse_structured_answer,
)
from diary_rag.core.embeddings.models import EmbeddingStatus


def _chunk(chunk_id: str) -> EventChunk:
    return EventChunk(
        chunk_id=chunk_id,
        diary_entry_id=f"entry-{chunk_id}",
        source_message_id=f"src-{chunk_id}",
        family_id="fam-A",
        author_user_id="user-1",
        entry_date=date(2026, 5, 9),
        event_index=0,
        chunk_text="event",
        created_at=datetime(2026, 5, 9, 8, 0, tzinfo=UTC),
        embedding_status=EmbeddingStatus.READY,
    )


def _context(*chunks: EventChunk) -> AnswerContext:
    return AnswerContext(
        query_id="q-1",
        query_text="x",
        ordered_chunks=tuple(chunks),
        model_name="mock",
        created_at=datetime(2026, 5, 12, 12, 0, tzinfo=UTC),
    )


def _payload(
    *,
    answer_text: str = "you read book A on 2026-05-09.",
    cited_chunk_ids: list[str] | None = None,
    uncertainty: str = "confident",
) -> str:
    return json.dumps(
        {
            "answer_text": answer_text,
            "cited_chunk_ids": cited_chunk_ids if cited_chunk_ids is not None else ["c-0"],
            "uncertainty": uncertainty,
        }
    )


def test_parse_round_trip_minimal_valid() -> None:
    context = _context(_chunk("c-0"), _chunk("c-1"))
    raw = _payload(cited_chunk_ids=["c-0", "c-1"], uncertainty="confident")

    parsed = parse_structured_answer(raw, context=context)

    assert isinstance(parsed, StructuredAnswer)
    assert parsed.answer_text == "you read book A on 2026-05-09."
    assert parsed.cited_chunk_ids == ("c-0", "c-1")
    assert parsed.uncertainty == "confident"


def test_parse_rejects_fabricated_citation() -> None:
    context = _context(_chunk("c-0"))
    raw = _payload(cited_chunk_ids=["c-0", "c-fabricated"])

    with pytest.raises(FabricatedCitationError) as excinfo:
        parse_structured_answer(raw, context=context)

    assert "c-fabricated" in str(excinfo.value)


def test_parse_rejects_malformed_json() -> None:
    context = _context(_chunk("c-0"))

    with pytest.raises(MalformedAnswerJSONError):
        parse_structured_answer("not json at all {", context=context)


def test_parse_rejects_non_object_top_level() -> None:
    context = _context(_chunk("c-0"))

    with pytest.raises(AnswerSchemaMismatchError):
        parse_structured_answer("[1, 2, 3]", context=context)


def test_parse_rejects_missing_required_field() -> None:
    context = _context(_chunk("c-0"))
    raw = json.dumps({"answer_text": "x", "cited_chunk_ids": ["c-0"]})

    with pytest.raises(AnswerSchemaMismatchError) as excinfo:
        parse_structured_answer(raw, context=context)

    assert "uncertainty" in str(excinfo.value)


def test_parse_rejects_extra_field() -> None:
    context = _context(_chunk("c-0"))
    raw = json.dumps(
        {
            "answer_text": "x",
            "cited_chunk_ids": ["c-0"],
            "uncertainty": "confident",
            "secret_provider_field": "leak",
        }
    )

    with pytest.raises(AnswerSchemaMismatchError) as excinfo:
        parse_structured_answer(raw, context=context)

    assert "secret_provider_field" in str(excinfo.value)


def test_parse_rejects_wrong_type_for_answer_text() -> None:
    context = _context(_chunk("c-0"))
    raw = json.dumps({"answer_text": 42, "cited_chunk_ids": ["c-0"], "uncertainty": "confident"})

    with pytest.raises(AnswerSchemaMismatchError):
        parse_structured_answer(raw, context=context)


def test_parse_rejects_wrong_type_for_cited_chunk_ids() -> None:
    context = _context(_chunk("c-0"))
    raw = json.dumps({"answer_text": "x", "cited_chunk_ids": "c-0", "uncertainty": "confident"})

    with pytest.raises(AnswerSchemaMismatchError):
        parse_structured_answer(raw, context=context)


def test_parse_rejects_unknown_uncertainty_marker() -> None:
    context = _context(_chunk("c-0"))
    raw = _payload(uncertainty="very-confident")

    with pytest.raises(AnswerSchemaMismatchError) as excinfo:
        parse_structured_answer(raw, context=context)

    assert "very-confident" in str(excinfo.value)


def test_empty_citations_rejected_when_marker_is_confident() -> None:
    context = _context(_chunk("c-0"))
    raw = _payload(cited_chunk_ids=[], uncertainty="confident")

    with pytest.raises(AnswerSchemaMismatchError):
        parse_structured_answer(raw, context=context)


def test_empty_citations_allowed_with_no_evidence_marker() -> None:
    context = _context()
    raw = _payload(answer_text="i don't know", cited_chunk_ids=[], uncertainty="no_evidence")

    parsed = parse_structured_answer(raw, context=context)

    assert parsed.cited_chunk_ids == ()
    assert parsed.uncertainty == "no_evidence"


def test_parse_accepts_uncertain_marker_with_subset_citations() -> None:
    context = _context(_chunk("c-0"), _chunk("c-1"))
    raw = _payload(cited_chunk_ids=["c-0"], uncertainty="uncertain")

    parsed = parse_structured_answer(raw, context=context)

    assert parsed.cited_chunk_ids == ("c-0",)
    assert parsed.uncertainty == "uncertain"
