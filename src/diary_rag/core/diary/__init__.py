"""Channel-neutral diary domain.

Holds the diary entity dataclasses (subset of TechSpec §5), the result
types returned by the diary and query services, and the deterministic
date-line parser used by the ingestion path.
"""

from diary_rag.core.diary.models import (
    AnswerResult,
    DiaryEntry,
    EventChunk,
    Evidence,
    FallbackMode,
    IngestResult,
    SourceMessage,
)
from diary_rag.core.diary.parser import ParsedEntry, parse_diary_entry

__all__ = [
    "AnswerResult",
    "DiaryEntry",
    "Evidence",
    "EventChunk",
    "FallbackMode",
    "IngestResult",
    "ParsedEntry",
    "SourceMessage",
    "parse_diary_entry",
]
