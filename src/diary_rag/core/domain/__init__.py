"""Channel-neutral diary domain.

Holds the diary entity dataclasses (subset of TechSpec §5), the result
types returned by the diary and query services, and the deterministic
date-line parser used by the ingestion path.
"""

from diary_rag.core.domain.answer_prompt import (
    PROMPT_VERSION,
    AnswerPrompt,
    CrossCommunityContextError,
    build_answer_prompt,
)
from diary_rag.core.domain.answer_schema import (
    AnswerSchemaMismatchError,
    FabricatedCitationError,
    MalformedAnswerJSONError,
    StructuredAnswer,
    StructuredAnswerError,
    UncertaintyMarker,
    parse_structured_answer,
)
from diary_rag.core.domain.models import (
    AnswerContext,
    AnswerResult,
    AnswerTrace,
    DateRange,
    EventChunk,
    Evidence,
    FallbackMode,
    IngestResult,
    Note,
    Query,
    RetrievalHit,
    RetrievalLeg,
    SourceMessage,
)
from diary_rag.core.domain.parser import ParsedNote, parse_note

__all__ = [
    "PROMPT_VERSION",
    "AnswerContext",
    "AnswerPrompt",
    "AnswerResult",
    "AnswerSchemaMismatchError",
    "AnswerTrace",
    "CrossCommunityContextError",
    "DateRange",
    "Note",
    "Evidence",
    "EventChunk",
    "FabricatedCitationError",
    "FallbackMode",
    "IngestResult",
    "MalformedAnswerJSONError",
    "ParsedNote",
    "Query",
    "RetrievalHit",
    "RetrievalLeg",
    "SourceMessage",
    "StructuredAnswer",
    "StructuredAnswerError",
    "UncertaintyMarker",
    "build_answer_prompt",
    "parse_note",
    "parse_structured_answer",
]
