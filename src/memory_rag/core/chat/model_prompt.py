"""Model-only answer prompt and response contract (RC-2, D-108).

The ``model_only`` route answers from general model knowledge with no
retrieval. It reuses the existing :class:`ChatClient` seam — and so the
D-037 generation contour, not the classifier pin — which means the
response must be JSON-shaped (the OpenAI chat adapter hardwires
``response_format={"type": "json_object"}``). The prompt instructs the
model that it has no access to the user's notes and must never present
its answer as note-grounded (generalized I-9); the explicit
model-knowledge label on the reply is the control-surface adapter's
responsibility.

``parse_model_only_answer`` is deliberately lenient: it requires only a
top-level JSON object with a string ``answer_text`` and ignores extra
keys, so a provider that volunteers the structured-answer v1 shape still
parses.
"""

from __future__ import annotations

import json
from typing import Final

from memory_rag.core.domain.answer_prompt import AnswerPrompt

MODEL_ONLY_PROMPT_VERSION: Final[str] = "model-only-v1"

_SYSTEM_TEXT: Final[str] = (
    "You answer the user's question from your own general knowledge. "
    "You have no access to the user's saved notes, and you must never "
    "claim or imply that any part of your answer comes from their notes. "
    'Return a single JSON object with one field: "answer_text" (string).'
)


class ModelOnlyAnswerError(ValueError):
    """The provider's model-only output was not a usable answer object."""


def build_model_only_prompt(question: str) -> AnswerPrompt:
    """Render the deterministic model-only prompt for one question.

    ``cited_chunk_ids`` is always empty — no retrieval ran, so there is
    nothing to cite (I-9 generalized: the answer's provenance class is
    "model", carried by ``MODEL_ONLY_PROMPT_VERSION``).
    """
    return AnswerPrompt(
        prompt_version=MODEL_ONLY_PROMPT_VERSION,
        system_text=_SYSTEM_TEXT,
        user_text=f"Question: {question}",
        cited_chunk_ids=(),
    )


def parse_model_only_answer(raw: str) -> str:
    """Parse a model-only response into its ``answer_text``.

    Raises :class:`ModelOnlyAnswerError` when ``raw`` is not JSON, not a
    top-level object, or lacks a string ``answer_text``. Extra keys are
    ignored.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ModelOnlyAnswerError(f"model-only response is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ModelOnlyAnswerError(
            f"model-only response is not a JSON object: {type(payload).__name__}"
        )
    answer_text = payload.get("answer_text")
    if not isinstance(answer_text, str):
        raise ModelOnlyAnswerError(
            "model-only response lacks a string 'answer_text' field: "
            f"{type(answer_text).__name__}"
        )
    return answer_text
