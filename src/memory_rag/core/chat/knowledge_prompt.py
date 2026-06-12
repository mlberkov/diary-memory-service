"""Notes-plus-knowledge prompt contract and parser (RC-4, D-108).

Renders an :class:`AnswerContext` of enrichment-retrieved chunks plus
the knowledge-source excerpts plus the user's question into the
versioned ``notes-plus-knowledge-v1`` prompt, and parses the provider's
segmented response. The response shape carries one segment per
provenance plane (generalized I-9): ``notes_text`` may contain only
claims grounded in the listed chunks, each backed by
``cited_chunk_ids``; ``knowledge_text`` may contain only claims
grounded in the listed excerpts, each backed by ``cited_knowledge_refs``
(rendered verbatim as the web-plane citations); ``model_text`` is
general model knowledge, explicitly labeled by the reply layer and
never attributed to the notes or the knowledge source. No provider SDK
and no LLM call live here.

The response is a JSON object because the OpenAI chat adapter hardwires
``response_format={"type": "json_object"}`` (D-109).

Parsing is strict where honesty is at stake — required fields and
types, fabricated chunk citations rejected against the context (I-9),
fabricated knowledge refs rejected against the offered excerpt refs,
the RC-3 notes consistency triple enforced in both directions, and the
knowledge consistency pair ``knowledge_text == "" iff
cited_knowledge_refs == ()`` enforced in both directions — and lenient
on extra keys (the RC-2 ``parse_model_only_answer`` precedent). With an
empty excerpt set any cited ref is fabricated, so the failed-search
contour is structurally honest.

The escalation clause is imported from
:mod:`memory_rag.core.chat.enriched_prompt` rather than copied — the
D-108 medical amendment stays one byte-pinned constant shared by both
mixed routes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final, cast

from memory_rag.core.chat.enriched_prompt import ESCALATION_CLAUSE, NotesUncertainty
from memory_rag.core.chat.knowledge import KnowledgeExcerpt
from memory_rag.core.domain.answer_prompt import AnswerPrompt, CrossCommunityContextError
from memory_rag.core.domain.models import AnswerContext

NOTES_PLUS_KNOWLEDGE_PROMPT_VERSION: Final[str] = "notes-plus-knowledge-v1"

_VALID_NOTES_UNCERTAINTY: Final[frozenset[str]] = frozenset(
    {"confident", "uncertain", "no_evidence"}
)
_REQUIRED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "notes_text",
        "cited_chunk_ids",
        "model_text",
        "notes_uncertainty",
        "knowledge_text",
        "cited_knowledge_refs",
    }
)

_SYSTEM_TEXT: Final[str] = (
    "You answer the user's question by combining three planes: their "
    "saved notes (provided below as chunks), retrieved knowledge "
    "excerpts (provided below with refs), and your own general "
    "knowledge. Return a single JSON object with these fields: "
    '"notes_text" (string — only claims grounded in the provided '
    "chunks; every factual claim must cite at least one chunk_id), "
    '"cited_chunk_ids" (array of chunk_id strings drawn from the list), '
    '"knowledge_text" (string — only claims grounded in the provided '
    "excerpts; every factual claim must cite at least one ref), "
    '"cited_knowledge_refs" (array of ref strings drawn from the '
    "excerpt list), "
    '"model_text" (string — your general knowledge; never attribute it '
    "to the notes or the excerpts), "
    '"notes_uncertainty" (one of "confident", "uncertain", '
    '"no_evidence"). '
    "If the chunks do not contain anything relevant, return "
    'notes_uncertainty="no_evidence" with an empty notes_text and an '
    "empty cited_chunk_ids array. If the excerpts do not contain "
    "anything relevant, return an empty knowledge_text and an empty "
    "cited_knowledge_refs array, and answer from general knowledge in "
    "model_text alone. " + ESCALATION_CLAUSE
)

_NO_CHUNKS_PLACEHOLDER: Final[str] = "(no note chunks were retrieved for this question)"
_NO_EXCERPTS_PLACEHOLDER: Final[str] = "(no knowledge excerpts were retrieved for this question)"


@dataclass(frozen=True, slots=True)
class NotesPlusKnowledgeAnswer:
    """The parsed, citation-validated segmented response."""

    notes_text: str
    cited_chunk_ids: tuple[str, ...]
    knowledge_text: str
    cited_knowledge_refs: tuple[str, ...]
    model_text: str
    notes_uncertainty: NotesUncertainty


class NotesPlusKnowledgeAnswerError(ValueError):
    """The raw response is not a usable notes-plus-knowledge answer."""


def build_notes_plus_knowledge_prompt(
    context: AnswerContext, excerpts: tuple[KnowledgeExcerpt, ...]
) -> AnswerPrompt:
    """Render the channel-neutral notes-plus-knowledge prompt (RC-4).

    Asserts R-8 (single ``community_id`` across ``ordered_chunks``) and
    raises :class:`CrossCommunityContextError` on violation.
    ``context.query_text`` is the original user question — neither the
    retrieval-side nor the outward rewrite reaches the generation
    prompt. The offered excerpt refs travel on
    ``AnswerPrompt.knowledge_refs`` so the parser and the mock provider
    see them without scraping ``user_text``. Output is fully
    deterministic given input.
    """
    communities = {chunk.community_id for chunk in context.ordered_chunks}
    if len(communities) > 1:
        raise CrossCommunityContextError(
            "AnswerContext.ordered_chunks span multiple communities: " f"{sorted(communities)}"
        )

    cited_chunk_ids = tuple(chunk.chunk_id for chunk in context.ordered_chunks)
    knowledge_refs = tuple(excerpt.ref for excerpt in excerpts)

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

    if not excerpts:
        excerpts_block = _NO_EXCERPTS_PLACEHOLDER
    else:
        excerpts_block = "\n".join(
            f"- ref={excerpt.ref} title={excerpt.title} text={excerpt.text}" for excerpt in excerpts
        )

    user_text = (
        f"Question: {context.query_text}\n\n"
        f"Note chunks (in retrieval rank order):\n{chunks_block}\n\n"
        f"Knowledge excerpts (in provider rank order):\n{excerpts_block}"
    )

    return AnswerPrompt(
        prompt_version=NOTES_PLUS_KNOWLEDGE_PROMPT_VERSION,
        system_text=_SYSTEM_TEXT,
        user_text=user_text,
        cited_chunk_ids=cited_chunk_ids,
        knowledge_refs=knowledge_refs,
    )


def parse_notes_plus_knowledge_answer(
    raw: str, *, context: AnswerContext, knowledge_refs: tuple[str, ...]
) -> NotesPlusKnowledgeAnswer:
    """Parse ``raw`` JSON, validate the segmented shape, enforce I-9 grounding.

    ``cited_chunk_ids`` must be a subset of the chunk_ids in
    ``context.ordered_chunks``; ``cited_knowledge_refs`` must be a
    subset of ``knowledge_refs``. The RC-3 notes consistency triple is
    enforced in both directions, and the knowledge consistency pair is
    enforced in both directions: a knowledge claim without a citation
    must never render as knowledge-grounded, and a citation set without
    text is unusable. Extra keys are ignored.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NotesPlusKnowledgeAnswerError(f"raw response is not valid JSON: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise NotesPlusKnowledgeAnswerError("expected a JSON object at the top level")

    missing = _REQUIRED_FIELDS - set(payload.keys())
    if missing:
        raise NotesPlusKnowledgeAnswerError(f"missing required fields: {sorted(missing)}")

    notes_text = payload["notes_text"]
    if not isinstance(notes_text, str):
        raise NotesPlusKnowledgeAnswerError("notes_text must be a string")

    raw_citations = payload["cited_chunk_ids"]
    if not isinstance(raw_citations, list) or not all(
        isinstance(item, str) for item in raw_citations
    ):
        raise NotesPlusKnowledgeAnswerError("cited_chunk_ids must be a list of strings")
    cited_chunk_ids = tuple(raw_citations)

    knowledge_text = payload["knowledge_text"]
    if not isinstance(knowledge_text, str):
        raise NotesPlusKnowledgeAnswerError("knowledge_text must be a string")

    raw_refs = payload["cited_knowledge_refs"]
    if not isinstance(raw_refs, list) or not all(isinstance(item, str) for item in raw_refs):
        raise NotesPlusKnowledgeAnswerError("cited_knowledge_refs must be a list of strings")
    cited_knowledge_refs = tuple(raw_refs)

    model_text = payload["model_text"]
    if not isinstance(model_text, str):
        raise NotesPlusKnowledgeAnswerError("model_text must be a string")

    uncertainty_raw = payload["notes_uncertainty"]
    if uncertainty_raw not in _VALID_NOTES_UNCERTAINTY:
        raise NotesPlusKnowledgeAnswerError(
            f"notes_uncertainty must be one of {sorted(_VALID_NOTES_UNCERTAINTY)}, "
            f"got {uncertainty_raw!r}"
        )
    notes_uncertainty = cast(NotesUncertainty, uncertainty_raw)

    context_chunk_ids = {chunk.chunk_id for chunk in context.ordered_chunks}
    fabricated_chunks = [cid for cid in cited_chunk_ids if cid not in context_chunk_ids]
    if fabricated_chunks:
        raise NotesPlusKnowledgeAnswerError(
            f"cited_chunk_ids not present in AnswerContext: {fabricated_chunks}"
        )

    offered_refs = set(knowledge_refs)
    fabricated_refs = [ref for ref in cited_knowledge_refs if ref not in offered_refs]
    if fabricated_refs:
        raise NotesPlusKnowledgeAnswerError(
            f"cited_knowledge_refs not present in the offered excerpts: {fabricated_refs}"
        )

    notes_plane_empty = not cited_chunk_ids and not notes_text
    if notes_uncertainty == "no_evidence" and not notes_plane_empty:
        raise NotesPlusKnowledgeAnswerError(
            'notes_uncertainty="no_evidence" requires empty notes_text and cited_chunk_ids'
        )
    if notes_uncertainty != "no_evidence" and (not cited_chunk_ids or not notes_text):
        raise NotesPlusKnowledgeAnswerError(
            "a non-empty notes plane requires both notes_text and cited_chunk_ids; "
            'an empty notes plane requires notes_uncertainty="no_evidence"'
        )

    if bool(knowledge_text) != bool(cited_knowledge_refs):
        raise NotesPlusKnowledgeAnswerError(
            "a non-empty knowledge plane requires both knowledge_text and "
            "cited_knowledge_refs; an empty knowledge plane requires both empty"
        )

    return NotesPlusKnowledgeAnswer(
        notes_text=notes_text,
        cited_chunk_ids=cited_chunk_ids,
        knowledge_text=knowledge_text,
        cited_knowledge_refs=cited_knowledge_refs,
        model_text=model_text,
        notes_uncertainty=notes_uncertainty,
    )
