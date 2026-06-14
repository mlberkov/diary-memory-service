"""Channel-neutral diary domain.

Holds the diary entity dataclasses (subset of TechSpec §5), the result
types returned by the diary and query services, and the deterministic
date-line parser used by the ingestion path.
"""

from memory_rag.core.domain.answer_prompt import (
    PROMPT_VERSION,
    AnswerPrompt,
    CrossCommunityContextError,
    build_answer_prompt,
)
from memory_rag.core.domain.answer_schema import (
    AnswerSchemaMismatchError,
    FabricatedCitationError,
    MalformedAnswerJSONError,
    StructuredAnswer,
    StructuredAnswerError,
    UncertaintyMarker,
    parse_structured_answer,
)
from memory_rag.core.domain.models import (
    AnswerContext,
    AnswerResult,
    AnswerTrace,
    DateRange,
    DeleteOutcome,
    EventChunk,
    Evidence,
    FallbackMode,
    HardDeleteOutcome,
    IndexingDeadLetter,
    IngestResult,
    Note,
    Query,
    RetrievalHit,
    RetrievalLeg,
    SourceMessage,
)
from memory_rag.core.domain.parser import ParsedNote, parse_note

__all__ = [
    "PROMPT_VERSION",
    "AnswerContext",
    "AnswerPrompt",
    "AnswerResult",
    "AnswerSchemaMismatchError",
    "AnswerTrace",
    "CrossCommunityContextError",
    "DateRange",
    "DeleteOutcome",
    "Note",
    "Evidence",
    "EventChunk",
    "FabricatedCitationError",
    "FallbackMode",
    "HardDeleteOutcome",
    "IndexingDeadLetter",
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
