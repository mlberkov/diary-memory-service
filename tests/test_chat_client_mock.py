"""Unit tests for :class:`MockChatClient` (Slice 4.3a, D-034).

The mock is the test/dev default; it must be deterministic, must keep
its provider identity honest (``model_name == "mock"`` and
``latency_ms == 0``), and must emit a ``raw_text`` that round-trips
through :func:`parse_structured_answer` so ``QueryService`` can run the
contract end-to-end against it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from memory_rag.adapters.answers import MockChatClient
from memory_rag.core.chat import build_model_only_prompt, parse_model_only_answer
from memory_rag.core.domain import build_answer_prompt, parse_structured_answer
from memory_rag.core.domain.models import AnswerContext, EventChunk
from memory_rag.core.embeddings import EmbeddingStatus


def _make_chunk(chunk_id: str, text: str) -> EventChunk:
    return EventChunk(
        chunk_id=chunk_id,
        note_id="note-1",
        source_message_id="src-1",
        community_id="fam-1",
        author_user_id="user-1",
        note_date=date(2026, 5, 13),
        event_index=0,
        chunk_text=text,
        created_at=datetime(2026, 5, 13, tzinfo=UTC),
        embedding_status=EmbeddingStatus.READY,
    )


def _make_context(*chunks: EventChunk) -> AnswerContext:
    return AnswerContext(
        query_id="qry-1",
        query_text="what happened?",
        ordered_chunks=tuple(chunks),
        model_name="mock",
        created_at=datetime(2026, 5, 13, tzinfo=UTC),
    )


def test_mock_client_reports_mock_model_name() -> None:
    client = MockChatClient()
    assert client.model_name == "mock"


def test_mock_client_is_deterministic_for_same_prompt() -> None:
    client = MockChatClient()
    context = _make_context(_make_chunk("c1", "walked the dog"))
    prompt = build_answer_prompt(context)
    a = client.complete(prompt)
    b = client.complete(prompt)
    assert a == b


def test_mock_client_round_trips_through_structured_parser() -> None:
    client = MockChatClient()
    context = _make_context(_make_chunk("c1", "walked the dog"))
    prompt = build_answer_prompt(context)
    response = client.complete(prompt)
    structured = parse_structured_answer(response.raw_text, context=context)
    assert structured.uncertainty == "confident"
    assert structured.cited_chunk_ids == ("c1",)


def test_mock_client_preserves_cited_chunk_ids() -> None:
    client = MockChatClient()
    context = _make_context(
        _make_chunk("c1", "walked the dog"),
        _make_chunk("c2", "made pasta"),
    )
    prompt = build_answer_prompt(context)
    response = client.complete(prompt)
    structured = parse_structured_answer(response.raw_text, context=context)
    assert structured.cited_chunk_ids == ("c1", "c2")


def test_mock_client_returns_zero_latency_ms() -> None:
    client = MockChatClient()
    context = _make_context(_make_chunk("c1", "walked the dog"))
    prompt = build_answer_prompt(context)
    response = client.complete(prompt)
    assert response.latency_ms == 0
    assert response.model_name == "mock"
    assert response.token_counts.keys() == {"prompt", "completion"}


def test_mock_client_no_evidence_path_round_trips() -> None:
    client = MockChatClient()
    context = _make_context()
    prompt = build_answer_prompt(context)
    response = client.complete(prompt)
    structured = parse_structured_answer(response.raw_text, context=context)
    assert structured.uncertainty == "no_evidence"
    assert structured.cited_chunk_ids == ()


# ---------------------------------------------------------------------------
# Model-only branch (RC-2, D-108) — additive, keyed on prompt_version;
# the v1 structured-answer behavior above is byte-unchanged.
# ---------------------------------------------------------------------------


def test_mock_client_model_only_branch_round_trips() -> None:
    client = MockChatClient()
    prompt = build_model_only_prompt("what is phonemic awareness")
    response = client.complete(prompt)
    assert parse_model_only_answer(response.raw_text) == (
        "Mock model-knowledge answer (no notes consulted)."
    )
    assert response.model_name == "mock"
    assert response.latency_ms == 0
    assert response.token_counts.keys() == {"prompt", "completion"}


def test_mock_client_model_only_branch_is_deterministic() -> None:
    client = MockChatClient()
    prompt = build_model_only_prompt("q")
    assert client.complete(prompt) == client.complete(prompt)


def test_mock_client_v1_branch_unchanged_by_model_only_addition() -> None:
    """An empty-citation v1 prompt still takes the structured-answer
    branch — the model-only branch is keyed on prompt_version, not on
    citation emptiness."""
    client = MockChatClient()
    context = _make_context()
    prompt = build_answer_prompt(context)
    assert prompt.prompt_version == "v1"
    response = client.complete(prompt)
    structured = parse_structured_answer(response.raw_text, context=context)
    assert structured.uncertainty == "no_evidence"
