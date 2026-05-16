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
"""

from __future__ import annotations

import json

from memory_rag.core.answers.client import ChatResponse
from memory_rag.core.domain.answer_prompt import AnswerPrompt


class MockChatClient:
    """In-process deterministic chat stand-in (Slice 4.3a)."""

    def __init__(self, *, model_name: str = "mock") -> None:
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def complete(self, prompt: AnswerPrompt) -> ChatResponse:
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
