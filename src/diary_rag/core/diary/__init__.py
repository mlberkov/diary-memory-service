"""Channel-neutral diary domain.

Holds the diary entity dataclasses (subset of TechSpec §5), the result
types returned by the diary and query services, and the deterministic
date-line parser used by the ingestion path.
"""

from diary_rag.core.diary.answer_prompt import (
    PROMPT_VERSION,
    AnswerPrompt,
    CrossFamilyContextError,
    build_answer_prompt,
)
from diary_rag.core.diary.answer_schema import (
    AnswerSchemaMismatchError,
    FabricatedCitationError,
    MalformedAnswerJSONError,
    StructuredAnswer,
    StructuredAnswerError,
    UncertaintyMarker,
    parse_structured_answer,
)
from diary_rag.core.diary.models import (
    AnswerContext,
    AnswerResult,
    AnswerTrace,
    DiaryEntry,
    EventChunk,
    Evidence,
    FallbackMode,
    IngestResult,
    Query,
    RetrievalHit,
    RetrievalLeg,
    SourceMessage,
)
from diary_rag.core.diary.parser import ParsedEntry, parse_diary_entry

__all__ = [
    "PROMPT_VERSION",
    "AnswerContext",
    "AnswerPrompt",
    "AnswerResult",
    "AnswerSchemaMismatchError",
    "AnswerTrace",
    "CrossFamilyContextError",
    "DiaryEntry",
    "Evidence",
    "EventChunk",
    "FabricatedCitationError",
    "FallbackMode",
    "IngestResult",
    "MalformedAnswerJSONError",
    "ParsedEntry",
    "Query",
    "RetrievalHit",
    "RetrievalLeg",
    "SourceMessage",
    "StructuredAnswer",
    "StructuredAnswerError",
    "UncertaintyMarker",
    "build_answer_prompt",
    "parse_diary_entry",
    "parse_structured_answer",
]
