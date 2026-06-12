"""Model-only prompt + response contract (RC-2, D-108).

The prompt is deterministic and JSON-shaped (the OpenAI chat adapter
hardwires ``response_format={"type": "json_object"}``); the parser is
lenient — a top-level object with a string ``answer_text`` suffices and
extra keys are ignored, so a provider that volunteers the v1
structured-answer shape still parses.
"""

from __future__ import annotations

import json

import pytest

from memory_rag.core.chat.model_prompt import (
    MODEL_ONLY_PROMPT_VERSION,
    ModelOnlyAnswerError,
    build_model_only_prompt,
    parse_model_only_answer,
)


def test_prompt_is_deterministic_and_versioned() -> None:
    first = build_model_only_prompt("what is phonemic awareness")
    second = build_model_only_prompt("what is phonemic awareness")
    assert first == second
    assert first.prompt_version == MODEL_ONLY_PROMPT_VERSION == "model-only-v1"


def test_prompt_carries_no_citations_and_embeds_the_question() -> None:
    prompt = build_model_only_prompt("what is phonemic awareness")
    assert prompt.cited_chunk_ids == ()
    assert "what is phonemic awareness" in prompt.user_text


def test_prompt_system_text_demands_json_and_forbids_notes_attribution() -> None:
    """The system text must ask for a JSON object (json_object response
    format requires the word) and must forbid presenting the answer as
    note-grounded (generalized I-9)."""
    prompt = build_model_only_prompt("q")
    assert "JSON" in prompt.system_text
    assert "answer_text" in prompt.system_text
    assert "never" in prompt.system_text
    assert "notes" in prompt.system_text


def test_parse_accepts_minimal_object() -> None:
    assert parse_model_only_answer('{"answer_text": "hi"}') == "hi"


def test_parse_ignores_extra_keys_including_v1_shape() -> None:
    raw = json.dumps({"answer_text": "hi", "cited_chunk_ids": [], "uncertainty": "confident"})
    assert parse_model_only_answer(raw) == "hi"


def test_parse_rejects_non_json() -> None:
    with pytest.raises(ModelOnlyAnswerError):
        parse_model_only_answer("not json at all")


def test_parse_rejects_non_object() -> None:
    with pytest.raises(ModelOnlyAnswerError):
        parse_model_only_answer('["answer_text"]')


def test_parse_rejects_missing_answer_text() -> None:
    with pytest.raises(ModelOnlyAnswerError):
        parse_model_only_answer('{"text": "hi"}')


def test_parse_rejects_non_string_answer_text() -> None:
    with pytest.raises(ModelOnlyAnswerError):
        parse_model_only_answer('{"answer_text": 42}')
