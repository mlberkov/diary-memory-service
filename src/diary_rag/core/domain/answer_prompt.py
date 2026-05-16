"""Channel-neutral answer prompt contract (Slice 4.2).

Pure rendering of an :class:`AnswerContext` into a versioned prompt that
downstream LLM-call adapters consume. No provider SDK and no LLM call
live here — this module is the contract that the chat-client seam,
fallback grading, and Telegram citation rendering all attach to.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from diary_rag.core.domain.models import AnswerContext

PROMPT_VERSION: Final[str] = "v1"


class CrossCommunityContextError(ValueError):
    """Raised when an ``AnswerContext`` mixes chunks from more than one community.

    Enforces R-8 in code: prompt assembly never mixes chunks from more
    than one ``community_id``.
    """


@dataclass(frozen=True, slots=True)
class AnswerPrompt:
    """Versioned prompt rendered from an :class:`AnswerContext`.

    ``cited_chunk_ids`` lists the chunks the user-side prompt body
    references, in the same order they appear in ``context.ordered_chunks``.
    The future answer-trace packet records ``prompt_version`` against the
    persisted ``Query`` row.
    """

    prompt_version: str
    system_text: str
    user_text: str
    cited_chunk_ids: tuple[str, ...]


_SYSTEM_TEXT: Final[str] = (
    "You answer the user's question using only the provided diary chunks. "
    "Every factual claim must cite at least one chunk_id from the list. "
    "Return a single JSON object with these fields: "
    '"answer_text" (string), '
    '"cited_chunk_ids" (array of chunk_id strings drawn from the list), '
    '"uncertainty" (one of "confident", "uncertain", "no_evidence"). '
    'If the chunks do not contain the answer, return uncertainty="no_evidence" '
    "with an empty cited_chunk_ids array."
)


_NO_CHUNKS_PLACEHOLDER: Final[str] = "(no diary chunks were retrieved for this question)"


def build_answer_prompt(context: AnswerContext) -> AnswerPrompt:
    """Render the channel-neutral prompt for one ``AnswerContext``.

    Asserts R-8 (single ``community_id`` across ``ordered_chunks``) and
    raises :class:`CrossCommunityContextError` on violation. Output is
    fully deterministic given input.
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
        f"Diary chunks (in retrieval rank order):\n{chunks_block}"
    )

    return AnswerPrompt(
        prompt_version=PROMPT_VERSION,
        system_text=_SYSTEM_TEXT,
        user_text=user_text,
        cited_chunk_ids=cited_chunk_ids,
    )
