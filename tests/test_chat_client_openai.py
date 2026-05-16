"""Optional live OpenAI smoke for :class:`OpenAIChatClient` (D-037).

This test is **not part of the standard packet gate**. It hits the real
OpenAI API and is skipped unless ``DIARY_RAG_OPENAI_TEST_KEY`` is set,
which matches the gating pattern used for ``test_embedding_client_openai.py``
and ``test_postgres_store.py``.

When enabled it verifies that ``gpt-4.1`` with
``response_format={"type": "json_object"}`` returns a structured-answer
JSON that round-trips through
:func:`~diary_rag.core.domain.answer_schema.parse_structured_answer`.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

import pytest

from diary_rag.adapters.answers.openai_client import OpenAIChatClient
from diary_rag.core.domain import build_answer_prompt, parse_structured_answer
from diary_rag.core.domain.models import AnswerContext, EventChunk
from diary_rag.core.embeddings import EmbeddingStatus

OPENAI_TEST_KEY = os.environ.get("DIARY_RAG_OPENAI_TEST_KEY")

pytestmark = pytest.mark.skipif(
    OPENAI_TEST_KEY is None,
    reason="DIARY_RAG_OPENAI_TEST_KEY not set; live OpenAI smoke skipped.",
)


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
        query_text="What did we do on May 13?",
        ordered_chunks=tuple(chunks),
        model_name="gpt-4.1",
        created_at=datetime(2026, 5, 13, tzinfo=UTC),
    )


def test_openai_chat_client_round_trips_through_structured_parser() -> None:
    assert OPENAI_TEST_KEY is not None
    client = OpenAIChatClient(api_key=OPENAI_TEST_KEY, model_name="gpt-4.1")
    context = _make_context(_make_chunk("c1", "Walked the dog along the river."))
    prompt = build_answer_prompt(context)

    response = client.complete(prompt)

    assert response.model_name == "gpt-4.1"
    assert response.raw_text
    assert response.latency_ms >= 0
    assert set(response.token_counts.keys()) >= {"prompt", "completion"}

    structured = parse_structured_answer(response.raw_text, context=context)
    assert structured.cited_chunk_ids
    assert set(structured.cited_chunk_ids).issubset({"c1"})
