"""Notes-plus-model prompt contract and parser (RC-3, D-108).

Renders an :class:`AnswerContext` of enrichment-retrieved chunks plus
the user's question into the versioned ``notes-plus-model-v1`` prompt,
and parses the provider's segmented response. The response shape carries
one segment per provenance plane (generalized I-9): ``notes_text`` may
contain only claims grounded in the listed chunks, each backed by
``cited_chunk_ids``; ``model_text`` is general model knowledge,
explicitly labeled by the reply layer and never attributed to the
notes. No provider SDK and no LLM call live here.

The response is a JSON object because the OpenAI chat adapter hardwires
``response_format={"type": "json_object"}`` (D-109).

Parsing is strict where honesty is at stake — required fields and
types, fabricated citations rejected against the context (I-9), and the
consistency triple ``notes_uncertainty == "no_evidence"`` ⇔
``cited_chunk_ids == ()`` ⇔ ``notes_text == ""`` enforced in both
directions (a notes claim without a citation must never render as
note-grounded) — and lenient on extra keys (the RC-2
``parse_model_only_answer`` precedent: a provider that volunteers
extras degrades by labeling, not brittleness).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final, Literal, cast

from memory_rag.core.domain.answer_prompt import AnswerPrompt, CrossCommunityContextError
from memory_rag.core.domain.models import AnswerContext

NOTES_PLUS_MODEL_PROMPT_VERSION: Final[str] = "notes-plus-model-v1"

# D-108 medical amendment + escalation prompt invariant, live for this
# route from RC-3; RC-4's knowledge-source route reuses it verbatim.
ESCALATION_CLAUSE: Final[str] = (
    "You may give general developmental information and activity "
    "suggestions. You must never give a diagnosis or interpret symptoms. "
    "If the question or the provided notes suggest a potential "
    "developmental or medical red flag, your answer must recommend "
    "consulting a qualified specialist."
)

NotesUncertainty = Literal["confident", "uncertain", "no_evidence"]

_VALID_NOTES_UNCERTAINTY: Final[frozenset[str]] = frozenset(
    {"confident", "uncertain", "no_evidence"}
)
_REQUIRED_FIELDS: Final[frozenset[str]] = frozenset(
    {"notes_text", "cited_chunk_ids", "model_text", "notes_uncertainty"}
)

_SYSTEM_TEXT: Final[str] = (
    "You answer the user's question by combining two planes: their "
    "saved notes (provided below as chunks) and your own general "
    "knowledge. Return a single JSON object with these fields: "
    '"notes_text" (string — only claims grounded in the provided '
    "chunks; every factual claim must cite at least one chunk_id), "
    '"cited_chunk_ids" (array of chunk_id strings drawn from the list), '
    '"model_text" (string — your general knowledge; never attribute it '
    "to the notes), "
    '"notes_uncertainty" (one of "confident", "uncertain", '
    '"no_evidence"). '
    "If the chunks do not contain anything relevant, return "
    'notes_uncertainty="no_evidence" with an empty notes_text and an '
    "empty cited_chunk_ids array, and answer from general knowledge in "
    "model_text alone. " + ESCALATION_CLAUSE
)

_NO_CHUNKS_PLACEHOLDER: Final[str] = "(no note chunks were retrieved for this question)"


@dataclass(frozen=True, slots=True)
class NotesPlusModelAnswer:
    """The parsed, citation-validated segmented response."""

    notes_text: str
    cited_chunk_ids: tuple[str, ...]
    model_text: str
    notes_uncertainty: NotesUncertainty


class NotesPlusModelAnswerError(ValueError):
    """The raw response is not a usable notes-plus-model answer."""


def build_notes_plus_model_prompt(context: AnswerContext) -> AnswerPrompt:
    """Render the channel-neutral notes-plus-model prompt (RC-3).

    Asserts R-8 (single ``community_id`` across ``ordered_chunks``) and
    raises :class:`CrossCommunityContextError` on violation.
    ``context.query_text`` is the original user question — the
    retrieval-side rewrite never reaches the generation prompt. Output
    is fully deterministic given input.
    """
    communities = {chunk.community_id for chunk in context.ordered_chunks}
    if len(communities) > 1:
        raise CrossCommunityContextError(
            "AnswerContext.ordered_chunks span multiple communities: " f"{sorted(communities)}"
        )

    cited_chunk_ids = tuple(chunk.chunk_id for chunk in context.ordered_chunks)

    if not context.ordered_chunks:
        chunks_block = _NO_CHUNKS_PLACEHOLDER
    else:
        chunks_block = "\n".join(
            f"- chunk_id={chunk.chunk_id} "
            f"date={chunk.note_date.isoformat()} "
            f"event_index={chunk.event_index} "
            f"text={chunk.chunk_text}"
            for chunk in context.ordered_chunks
        )

    user_text = (
        f"Question: {context.query_text}\n\n"
        f"Note chunks (in retrieval rank order):\n{chunks_block}"
    )

    return AnswerPrompt(
        prompt_version=NOTES_PLUS_MODEL_PROMPT_VERSION,
        system_text=_SYSTEM_TEXT,
        user_text=user_text,
        cited_chunk_ids=cited_chunk_ids,
    )


def parse_notes_plus_model_answer(raw: str, *, context: AnswerContext) -> NotesPlusModelAnswer:
    """Parse ``raw`` JSON, validate the segmented shape, enforce I-9 grounding.

    ``cited_chunk_ids`` must be a subset of the chunk_ids in
    ``context.ordered_chunks``. The consistency triple is enforced in
    both directions: ``no_evidence`` requires an empty ``notes_text``
    and empty citations, and an empty citation set (or empty
    ``notes_text``) requires ``no_evidence``. Extra keys are ignored.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NotesPlusModelAnswerError(f"raw response is not valid JSON: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise NotesPlusModelAnswerError("expected a JSON object at the top level")

    missing = _REQUIRED_FIELDS - set(payload.keys())
    if missing:
        raise NotesPlusModelAnswerError(f"missing required fields: {sorted(missing)}")

    notes_text = payload["notes_text"]
    if not isinstance(notes_text, str):
        raise NotesPlusModelAnswerError("notes_text must be a string")

    raw_citations = payload["cited_chunk_ids"]
    if not isinstance(raw_citations, list) or not all(
        isinstance(item, str) for item in raw_citations
    ):
        raise NotesPlusModelAnswerError("cited_chunk_ids must be a list of strings")
    cited_chunk_ids = tuple(raw_citations)

    model_text = payload["model_text"]
    if not isinstance(model_text, str):
        raise NotesPlusModelAnswerError("model_text must be a string")

    uncertainty_raw = payload["notes_uncertainty"]
    if uncertainty_raw not in _VALID_NOTES_UNCERTAINTY:
        raise NotesPlusModelAnswerError(
            f"notes_uncertainty must be one of {sorted(_VALID_NOTES_UNCERTAINTY)}, "
            f"got {uncertainty_raw!r}"
        )
    notes_uncertainty = cast(NotesUncertainty, uncertainty_raw)

    context_chunk_ids = {chunk.chunk_id for chunk in context.ordered_chunks}
    fabricated = [cid for cid in cited_chunk_ids if cid not in context_chunk_ids]
    if fabricated:
        raise NotesPlusModelAnswerError(
            f"cited_chunk_ids not present in AnswerContext: {fabricated}"
        )

    notes_plane_empty = not cited_chunk_ids and not notes_text
    if notes_uncertainty == "no_evidence" and not notes_plane_empty:
        raise NotesPlusModelAnswerError(
            'notes_uncertainty="no_evidence" requires empty notes_text and cited_chunk_ids'
        )
    if notes_uncertainty != "no_evidence" and (not cited_chunk_ids or not notes_text):
        raise NotesPlusModelAnswerError(
            "a non-empty notes plane requires both notes_text and cited_chunk_ids; "
            'an empty notes plane requires notes_uncertainty="no_evidence"'
        )

    return NotesPlusModelAnswer(
        notes_text=notes_text,
        cited_chunk_ids=cited_chunk_ids,
        model_text=model_text,
        notes_uncertainty=notes_uncertainty,
    )
