"""Deterministic mock chat provider (Slice 4.3a, D-034).

Used by every automated test by default and by any boot configured with
``CHAT_BACKEND=mock``. The ``model_name`` is the literal string
``"mock"`` — provider provenance in rows and logs stays honest
(D-024-style convention applied to the chat seam).

The mock emits a JSON ``raw_text`` that round-trips through
:func:`~memory_rag.core.domain.answer_schema.parse_structured_answer`:
``cited_chunk_ids`` mirrors ``prompt.cited_chunk_ids``, ``answer_text``
deterministically summarises the cited chunks (or notes their absence),
and ``uncertainty`` is ``"confident"`` whenever there are citations,
``"no_evidence"`` otherwise.

``latency_ms`` is ``0`` — a mock has no real provider latency to
attribute; reporting anything else would be dishonest provenance.
``token_counts`` is a deterministic character-count approximation, not a
real tokenizer; it exists so ``AnswerTrace.token_counts`` has a stable
non-empty shape on the success contour.

RC-2 (D-108) adds an additive branch keyed on
``prompt.prompt_version == MODEL_ONLY_PROMPT_VERSION``: model-only
prompts get a deterministic ``{"answer_text": …}`` object that
round-trips through
:func:`~memory_rag.core.chat.model_prompt.parse_model_only_answer`. The
v1 structured-answer behavior is byte-unchanged.

RC-3 adds a second additive branch keyed on
``prompt.prompt_version == NOTES_PLUS_MODEL_PROMPT_VERSION``:
notes-plus-model prompts get a deterministic segmented object that
round-trips through
:func:`~memory_rag.core.chat.enriched_prompt.parse_notes_plus_model_answer`
— a cited notes plane when the prompt carries chunks, an empty
``no_evidence`` notes plane otherwise, and a deterministic model
segment on both contours. The earlier branches are byte-unchanged.
"""

from __future__ import annotations

import json

from memory_rag.core.answers.client import ChatResponse
from memory_rag.core.chat.enriched_prompt import NOTES_PLUS_MODEL_PROMPT_VERSION
from memory_rag.core.chat.model_prompt import MODEL_ONLY_PROMPT_VERSION
from memory_rag.core.domain.answer_prompt import AnswerPrompt

_MOCK_MODEL_ONLY_ANSWER = "Mock model-knowledge answer (no notes consulted)."
_MOCK_NOTES_PLUS_MODEL_TEXT = "Mock general-knowledge segment."


class MockChatClient:
    """In-process deterministic chat stand-in (Slice 4.3a)."""

    def __init__(self, *, model_name: str = "mock") -> None:
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def complete(self, prompt: AnswerPrompt) -> ChatResponse:
        if prompt.prompt_version == MODEL_ONLY_PROMPT_VERSION:
            return self._complete_model_only(prompt)
        if prompt.prompt_version == NOTES_PLUS_MODEL_PROMPT_VERSION:
            return self._complete_notes_plus_model(prompt)
        cited = prompt.cited_chunk_ids
        if cited:
            answer_text = f"Mock answer grounded in {len(cited)} diary chunk(s): " + ", ".join(
                cited
            )
            uncertainty = "confident"
        else:
            answer_text = "No diary chunks were retrieved; cannot answer."
            uncertainty = "no_evidence"

        payload = {
            "answer_text": answer_text,
            "cited_chunk_ids": list(cited),
            "uncertainty": uncertainty,
        }
        raw_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        token_counts = {
            "prompt": len(prompt.system_text) + len(prompt.user_text),
            "completion": len(raw_text),
        }
        return ChatResponse(
            raw_text=raw_text,
            model_name=self._model_name,
            token_counts=token_counts,
            latency_ms=0,
        )

    def _complete_notes_plus_model(self, prompt: AnswerPrompt) -> ChatResponse:
        cited = prompt.cited_chunk_ids
        if cited:
            payload = {
                "notes_text": (
                    f"Mock notes segment grounded in {len(cited)} chunk(s): " + ", ".join(cited)
                ),
                "cited_chunk_ids": list(cited),
                "model_text": _MOCK_NOTES_PLUS_MODEL_TEXT,
                "notes_uncertainty": "confident",
            }
        else:
            payload = {
                "notes_text": "",
                "cited_chunk_ids": [],
                "model_text": _MOCK_NOTES_PLUS_MODEL_TEXT,
                "notes_uncertainty": "no_evidence",
            }
        raw_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        token_counts = {
            "prompt": len(prompt.system_text) + len(prompt.user_text),
            "completion": len(raw_text),
        }
        return ChatResponse(
            raw_text=raw_text,
            model_name=self._model_name,
            token_counts=token_counts,
            latency_ms=0,
        )

    def _complete_model_only(self, prompt: AnswerPrompt) -> ChatResponse:
        raw_text = json.dumps(
            {"answer_text": _MOCK_MODEL_ONLY_ANSWER}, ensure_ascii=False, sort_keys=True
        )
        token_counts = {
            "prompt": len(prompt.system_text) + len(prompt.user_text),
            "completion": len(raw_text),
        }
        return ChatResponse(
            raw_text=raw_text,
            model_name=self._model_name,
            token_counts=token_counts,
            latency_ms=0,
        )
