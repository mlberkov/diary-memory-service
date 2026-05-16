"""Structured answer schema and citation-grounding parser (Slice 4.2).

Strict JSON parser for the LLM's structured response. Enforces I-9 at
the contract boundary: every ``cited_chunk_ids`` element must appear in
the :class:`AnswerContext` that built the prompt. No provider SDK and no
LLM call — this is the validator that sits between the chat-client
adapter (later packet) and the rest of the answer pipeline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final, Literal, cast

from memory_rag.core.domain.models import AnswerContext

UncertaintyMarker = Literal["confident", "uncertain", "no_evidence", "ambiguous"]

_VALID_UNCERTAINTY: Final[frozenset[str]] = frozenset(
    {"confident", "uncertain", "no_evidence", "ambiguous"}
)
_REQUIRED_FIELDS: Final[frozenset[str]] = frozenset(
    {"answer_text", "cited_chunk_ids", "uncertainty"}
)


class StructuredAnswerError(ValueError):
    """Base class for structured-answer parse failures."""


class MalformedAnswerJSONError(StructuredAnswerError):
    """Raw LLM response is not valid JSON."""


class AnswerSchemaMismatchError(StructuredAnswerError):
    """JSON object does not match the structured-answer shape."""


class FabricatedCitationError(StructuredAnswerError):
    """A ``cited_chunk_id`` was not present in ``AnswerContext.ordered_chunks`` (I-9)."""


@dataclass(frozen=True, slots=True)
class StructuredAnswer:
    """The parsed, citation-validated LLM response."""

    answer_text: str
    cited_chunk_ids: tuple[str, ...]
    uncertainty: UncertaintyMarker


def parse_structured_answer(raw: str, *, context: AnswerContext) -> StructuredAnswer:
    """Parse ``raw`` JSON, validate the shape, enforce I-9 grounding.

    ``cited_chunk_ids`` must be a subset of the chunk_ids in
    ``context.ordered_chunks``. Empty ``cited_chunk_ids`` is permitted
    only when ``uncertainty == "no_evidence"``; ``"uncertain"`` and
    ``"ambiguous"`` therefore require non-empty citations.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MalformedAnswerJSONError(f"raw response is not valid JSON: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise AnswerSchemaMismatchError("expected a JSON object at the top level")

    keys = set(payload.keys())
    missing = _REQUIRED_FIELDS - keys
    if missing:
        raise AnswerSchemaMismatchError(f"missing required fields: {sorted(missing)}")
    extra = keys - _REQUIRED_FIELDS
    if extra:
        raise AnswerSchemaMismatchError(f"unexpected fields: {sorted(extra)}")

    answer_text = payload["answer_text"]
    if not isinstance(answer_text, str):
        raise AnswerSchemaMismatchError("answer_text must be a string")

    raw_citations = payload["cited_chunk_ids"]
    if not isinstance(raw_citations, list) or not all(
        isinstance(item, str) for item in raw_citations
    ):
        raise AnswerSchemaMismatchError("cited_chunk_ids must be a list of strings")
    cited_chunk_ids = tuple(raw_citations)

    uncertainty_raw = payload["uncertainty"]
    if uncertainty_raw not in _VALID_UNCERTAINTY:
        raise AnswerSchemaMismatchError(
            f"uncertainty must be one of {sorted(_VALID_UNCERTAINTY)}, " f"got {uncertainty_raw!r}"
        )
    uncertainty = cast(UncertaintyMarker, uncertainty_raw)

    context_chunk_ids = {chunk.chunk_id for chunk in context.ordered_chunks}
    fabricated = [cid for cid in cited_chunk_ids if cid not in context_chunk_ids]
    if fabricated:
        raise FabricatedCitationError(f"cited_chunk_ids not present in AnswerContext: {fabricated}")

    if not cited_chunk_ids and uncertainty != "no_evidence":
        raise AnswerSchemaMismatchError(
            'empty cited_chunk_ids is only permitted with uncertainty="no_evidence"'
        )

    return StructuredAnswer(
        answer_text=answer_text,
        cited_chunk_ids=cited_chunk_ids,
        uncertainty=uncertainty,
    )
