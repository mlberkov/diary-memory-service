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

from diary_rag.core.embeddings.models import EmbeddingStatus
from diary_rag.core.routing import RouteKind


class FallbackMode(StrEnum):
    """Why a service result took the path it did.

    ``NONE`` means the requested path produced a real result. Anything
    else is an explicit fallback that the reply layer must surface
    (Runtime invariant R-6).

    Ingest-side: ``INVALID_INPUT`` for a non-ISO first line.

    Answer-side (Slice 4.3b, D-035):

    - ``NO_EVIDENCE`` — retrieval returned no chunks (empty query or
      empty retrieval), or retrieval returned chunks but the LLM emitted
      ``uncertainty="no_evidence"`` declaring them not-evidence.
    - ``WEAK_EVIDENCE`` — LLM emitted ``uncertainty="uncertain"`` over a
      non-empty context.
    - ``AMBIGUOUS`` — LLM emitted ``uncertainty="ambiguous"`` indicating
      the question itself was unclear.
    - ``PROVIDER_UNAVAILABLE`` — chat client raised
      :class:`~diary_rag.core.answers.ChatProviderUnavailableError`;
      no LLM output was produced.
    - ``PARSE_FAILURE`` — chat client returned text that
      :func:`~diary_rag.core.diary.answer_schema.parse_structured_answer`
      rejected with a :class:`StructuredAnswerError`.
    """

    NONE = "none"
    NO_EVIDENCE = "no_evidence"
    INVALID_INPUT = "invalid_input"
    WEAK_EVIDENCE = "weak_evidence"
    AMBIGUOUS = "ambiguous"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PARSE_FAILURE = "parse_failure"


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
    """One event line; chunk → entry → source lineage preserved (I-4, I-5).

    ``embedding_status`` records the per-chunk progress of the Phase-3
    embedding step (D-024). A freshly-saved chunk is ``pending`` until
    the embedding provider call returns; it flips to ``ready`` once an
    ``EmbeddingRecord`` is persisted or to ``failed`` if the provider
    call raised. The chunk row itself is always intact (I-3, R-1).
    """

    chunk_id: str
    diary_entry_id: str
    source_message_id: str
    family_id: str
    author_user_id: str
    entry_date: date
    event_index: int
    chunk_text: str
    created_at: datetime
    embedding_status: EmbeddingStatus = EmbeddingStatus.PENDING


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
class AnswerContext:
    """Channel-neutral input to the answer-prompt step (Slice 4.1).

    The assembled view of one ``/ask`` call: the persisted ``Query``
    identity plus the chunks that survived RRF fusion in retrieval rank
    order. Mutable presentation shapes (date grouping, prompt rendering,
    citation layout) belong to consumers — this stays the minimal
    canonical payload every Phase-4 consumer can rely on.
    """

    query_id: str
    query_text: str
    ordered_chunks: tuple[EventChunk, ...]
    model_name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AnswerResult:
    """Outcome of ``QueryService.answer`` (I-9, R-5).

    ``context`` carries the assembled :class:`AnswerContext` for the
    successful retrieval, no-evidence, and empty-query paths so the
    follow-on chat-client / answer-trace packets can consume it without
    a further refactor. It is ``None`` only when no retrieval call ran
    at all — the dispatcher uses that branch for backends that raise
    ``NotImplementedError`` from the search seam.

    ``answer_text`` carries the LLM-produced answer on the success path
    (Slice 4.3a, D-034). It is ``None`` on no-evidence / empty-query
    contours where no chat call ran, and on the no-retrieval-call branch.
    The Telegram reply layer still renders the evidence-bullets shape in
    this packet; Slice 4.4 will switch it to consume ``answer_text``.
    """

    fallback: FallbackMode
    query_text: str
    evidence: list[Evidence] = field(default_factory=list)
    context: AnswerContext | None = None
    answer_text: str | None = None

    @property
    def context_chunk_ids(self) -> list[str]:
        return [e.chunk_id for e in self.evidence]


class RetrievalLeg(StrEnum):
    """Which retrieval pass produced a ``RetrievalHit`` row (Slice 3.5)."""

    DENSE = "dense"
    SPARSE = "sparse"
    MERGED = "merged"


@dataclass(frozen=True, slots=True)
class Query:
    """Persisted record of a single ``/ask`` call (Slice 3.5).

    ``query_text`` is the normalized payload (whitespace stripped, trailing
    ``?.!,;:`` removed). ``model_name`` is the embedding client's
    ``model_name`` at call time. ``fallback`` mirrors the ``AnswerResult``
    outcome — ``NO_EVIDENCE`` when the query was empty after normalization
    or when both retrieval legs returned no chunks.
    """

    query_id: str
    family_id: str
    query_text: str
    model_name: str
    fallback: FallbackMode
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AnswerTrace:
    """Answer-side provenance for one ``/ask`` call (R-5; D-034, D-035).

    Every reply writes one row recording ``prompt_version``,
    ``context_chunk_ids``, ``answer_text``, ``model_name``,
    ``token_counts``, ``latency_ms``, and ``fallback_mode``. The shape
    per contour (Slice 4.3b, D-035):

    - ``NONE`` (success): ``answer_text`` is the LLM-produced string;
      ``context_chunk_ids`` mirrors ``AnswerContext.ordered_chunks``;
      ``latency_ms`` / ``token_counts`` come from
      :class:`~diary_rag.core.answers.ChatResponse`.
    - ``NO_EVIDENCE`` (empty query or empty retrieval): ``answer_text``
      is ``""``; ``context_chunk_ids`` is empty; no chat call ran so
      ``latency_ms`` is ``0`` and ``token_counts`` is ``{}``.
    - ``NO_EVIDENCE`` (LLM marker — retrieval returned chunks but the
      model declared them not-evidence): ``answer_text`` is the LLM
      output; ``context_chunk_ids`` mirrors ``AnswerContext.ordered_chunks``;
      ``latency_ms`` / ``token_counts`` come from the response.
    - ``WEAK_EVIDENCE`` / ``AMBIGUOUS``: same shape as the success path —
      the LLM produced output over a non-empty context, the marker just
      grades how usable it is.
    - ``PROVIDER_UNAVAILABLE``: ``answer_text`` is ``""``;
      ``context_chunk_ids`` mirrors the context that *would* have been
      sent; no usable response, so ``latency_ms`` is ``0`` and
      ``token_counts`` is ``{}``.
    - ``PARSE_FAILURE``: ``answer_text`` is ``response.raw_text`` (the
      provider did produce output — preserving it is the truthful
      provenance); ``context_chunk_ids`` mirrors the context;
      ``latency_ms`` / ``token_counts`` come from the response.
    """

    answer_trace_id: str
    query_id: str
    prompt_version: str
    context_chunk_ids: tuple[str, ...]
    answer_text: str
    fallback_mode: FallbackMode
    model_name: str
    token_counts: dict[str, int]
    latency_ms: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    """One row per (query, chunk, leg) tuple (Slice 3.5).

    ``leg`` distinguishes which retrieval pass produced the row:
    ``DENSE`` and ``SPARSE`` carry the candidates each independent leg
    returned (up to ``candidate_k`` each); ``MERGED`` carries the chunks
    that survived service-layer RRF fusion (up to ``top_k``). ``rank`` is
    1-based within the leg. ``score`` is the RRF contribution for the
    per-leg rows (``1 / (RRF_K + rank)``) and the fused RRF score on the
    merged rows; backend-native scores (cosine distance, ``ts_rank_cd``)
    are intentionally not surfaced — D-025 noted that RRF uses ranks, not
    calibrated scores. ``model_name`` is the embedding model on dense and
    merged rows; the FTS dictionary (``"simple"``) on sparse rows.
    """

    retrieval_hit_id: str
    query_id: str
    chunk_id: str
    leg: RetrievalLeg
    rank: int
    score: float
    model_name: str
    created_at: datetime
