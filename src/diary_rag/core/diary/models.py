"""Channel-neutral diary entities and service results.

These are the smallest viable shapes that the mock ingestion and query
services need. They follow TechSpec §5 field naming where possible, but
identify the originating channel actor with ``external_chat_id`` /
``external_user_id`` (matching ``core/routing/models.InboundMessage``)
to keep the core free of channel-specific names (Invariant I-1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from diary_rag.core.routing import RouteKind


class FallbackMode(StrEnum):
    """Why a service result took the path it did.

    ``NONE`` means the requested path produced a real result. Anything
    else is an explicit fallback that the reply layer must surface
    (Runtime invariant R-6).
    """

    NONE = "none"
    NO_EVIDENCE = "no_evidence"
    INVALID_INPUT = "invalid_input"


@dataclass(frozen=True, slots=True)
class SourceMessage:
    """Raw inbound message, persisted before any enrichment (I-3, R-1).

    ``external_message_id`` and ``edit_seq`` together with ``external_chat_id``
    form the idempotency key required by Runtime invariant R-2 (D-023):
    repeated delivery of the same message-state must not create duplicate rows.
    ``edit_seq`` is ``0`` for an original message and the Telegram ``edit_date``
    epoch seconds for an edited state, so each distinct edit gets its own key.
    """

    source_message_id: str
    family_id: str
    author_user_id: str
    external_chat_id: str
    external_user_id: str
    external_message_id: str
    edit_seq: int
    raw_text: str
    detected_route: RouteKind
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DiaryEntry:
    """Logical diary entry parsed from a single source message."""

    diary_entry_id: str
    source_message_id: str
    family_id: str
    author_user_id: str
    entry_date: date
    entry_text: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EventChunk:
    """One event line; chunk → entry → source lineage preserved (I-4, I-5)."""

    chunk_id: str
    diary_entry_id: str
    source_message_id: str
    family_id: str
    author_user_id: str
    entry_date: date
    event_index: int
    chunk_text: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Evidence:
    """A retrieved chunk plus the metadata the reply layer needs to cite it."""

    chunk_id: str
    entry_date: date
    chunk_text: str


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Outcome of ``DiaryService.ingest``.

    ``replayed`` is ``True`` when the inbound message hit a previously
    persisted ``(external_chat_id, external_message_id, edit_seq)`` row
    (R-2 / D-023): no new state was created and the result was rebuilt
    from the existing source / entry / chunks.
    """

    fallback: FallbackMode
    source_message_id: str
    entry_date: date | None = None
    events_count: int = 0
    invalid_first_line: str | None = None
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class AnswerResult:
    """Outcome of ``QueryService.answer`` (I-9, R-5)."""

    fallback: FallbackMode
    query_text: str
    evidence: list[Evidence] = field(default_factory=list)

    @property
    def context_chunk_ids(self) -> list[str]:
        return [e.chunk_id for e in self.evidence]
