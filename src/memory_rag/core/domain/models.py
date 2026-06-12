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

from memory_rag.core.embeddings.models import EmbeddingStatus
from memory_rag.core.routing import RouteKind


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
      :class:`~memory_rag.core.answers.ChatProviderUnavailableError`;
      no LLM output was produced.
    - ``PARSE_FAILURE`` — chat client returned text that
      :func:`~memory_rag.core.domain.answer_schema.parse_structured_answer`
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
    community_id: str
    author_user_id: str
    external_chat_id: str
    external_user_id: str
    external_message_id: str
    edit_seq: int
    raw_text: str
    detected_route: RouteKind
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Note:
    """Logical note parsed from a single source message."""

    note_id: str
    source_message_id: str
    community_id: str
    author_user_id: str
    note_date: date
    note_text: str
    created_at: datetime
    subject_id: str | None = None


@dataclass(frozen=True, slots=True)
class EventChunk:
    """One event line; chunk → note → source lineage preserved (I-4, I-5).

    ``embedding_status`` records the per-chunk progress of the Phase-3
    embedding step (D-024). A freshly-saved chunk is ``pending`` until
    the embedding provider call returns; it flips to ``ready`` once an
    ``EmbeddingRecord`` is persisted or to ``failed`` if the provider
    call raised. The chunk row itself is always intact (I-3, R-1).
    """

    chunk_id: str
    note_id: str
    source_message_id: str
    community_id: str
    author_user_id: str
    note_date: date
    event_index: int
    chunk_text: str
    created_at: datetime
    embedding_status: EmbeddingStatus = EmbeddingStatus.PENDING
    subject_id: str | None = None


@dataclass(frozen=True, slots=True)
class DateRange:
    """Inclusive ``note_date`` bound for retrieval filtering (Slice 3.4, D-040).

    Both bounds are optional and inclusive: a chunk matches when its
    ``note_date`` is ``>= start`` (when ``start`` is set) and ``<= end``
    (when ``end`` is set). Both bounds ``None`` is a valid no-constraint
    range, treated by every backend identically to passing no filter at
    all. A range with ``start > end`` is contradictory and rejected at
    construction; equal bounds (a single-day range) are valid.
    """

    start: date | None = None
    end: date | None = None

    def __post_init__(self) -> None:
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError(
                f"DateRange.start must be <= end (got start={self.start}, end={self.end})"
            )


@dataclass(frozen=True, slots=True)
class Evidence:
    """A retrieved chunk plus the metadata the reply layer needs to cite it."""

    chunk_id: str
    note_date: date
    chunk_text: str


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Outcome of ``DomainService.ingest``.

    ``replayed`` is ``True`` when the inbound message hit a previously
    persisted ``(external_chat_id, external_message_id, edit_seq)`` row
    (R-2 / D-023): no new state was created and the result was rebuilt
    from the existing source / note / chunks.
    """

    fallback: FallbackMode
    source_message_id: str
    note_date: date | None = None
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

    ``cited_chunk_ids`` carries the chunks the LLM actually used — its
    parsed ``StructuredAnswer.cited_chunk_ids`` (a subset of
    ``context.ordered_chunks`` by I-9). It is distinct from the full
    retrieved set exposed by ``context_chunk_ids`` / ``context.ordered_chunks``:
    only the graded (post-parse) contours carry a non-empty value; the
    empty-query, empty-merged ``NO_EVIDENCE``, ``PROVIDER_UNAVAILABLE``,
    and ``PARSE_FAILURE`` contours carry ``()`` because no trustworthy
    citation set exists for them (D-098). The cited-only ``/sources`` and
    contributor-footer surfaces consume this field in later packets.
    """

    fallback: FallbackMode
    query_text: str
    evidence: list[Evidence] = field(default_factory=list)
    context: AnswerContext | None = None
    answer_text: str | None = None
    cited_chunk_ids: tuple[str, ...] = ()
    # RC-3: the explicitly-model-knowledge segment of a routed mixed
    # answer (generalized I-9 — the reply layer labels it; it is never
    # attributed to the notes). ``None`` on every pre-existing contour.
    model_text: str | None = None

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
    ``model_name`` at call time on retrieval-backed rows; rows written by
    the routed ``model_only`` path (RC-2, D-108) carry the generation chat
    client's ``model_name`` since no embedding call ran. ``fallback``
    mirrors the ``AnswerResult``
    outcome — ``NO_EVIDENCE`` when the query was empty after normalization
    or when both retrieval legs returned no chunks.

    ``subject_scope`` records the optional subject filter the call was made
    with (H-3, D-107): the opaque, community-subordinate ``subject_id`` value
    both retrieval legs were restricted to, or ``None`` (the default) when no
    subject constraint was requested.
    """

    query_id: str
    community_id: str
    query_text: str
    model_name: str
    fallback: FallbackMode
    created_at: datetime
    subject_scope: str | None = None


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
      :class:`~memory_rag.core.answers.ChatResponse`.
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


@dataclass(frozen=True, slots=True)
class IndexingDeadLetter:
    """A failed indexing job recorded for operator inspection (Slice 6.2).

    One record is attempted per failed embedding call: when the embedding
    provider raises during ``DomainService.ingest``, the affected chunks
    are marked ``embedding_status='failed'`` (A-35) and the service
    additionally attempts to persist this record. The write is
    best-effort — at most one row per failed embedding call for one
    source message, and the row may be absent if its own persistence
    fails. ``event_chunks.embedding_status`` stays the authoritative
    failure signal in that case.

    ``chunk_ids`` lists every chunk the failed call covered.
    ``error_class`` is the exception class name only — the same
    provenance the ``embedding.failed`` log line carries; no free-text
    exception payload is stored. The record is append-only: it has no
    status / resolved column. A future reconciliation job (OP-3 / A-35)
    consumes this surface but does not mutate it.
    """

    dead_letter_id: str
    source_message_id: str
    community_id: str
    chunk_ids: tuple[str, ...]
    model_name: str
    error_class: str
    created_at: datetime
