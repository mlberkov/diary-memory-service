"""Routed-chat data types (RC-2, D-108).

The chat-route taxonomy is distinct from the message-level
:class:`~memory_rag.core.routing.RouteKind` plane: ``RouteKind`` decides
which command handler serves an inbound message; :class:`ChatRoute`
decides which answer pipeline serves a ``/chat`` question once the
routed handler owns it. Core identifiers use the canonical
community/subject register (D-026 / D-041); the product-register labels
(``diary_lookup`` et al.) live in docs only — `docs/GLOSSARY.md` carries
the mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from memory_rag.core.domain.models import AnswerResult


class ChatRoute(StrEnum):
    """The four routed-chat answer routes (D-108, owner-fixed taxonomy).

    All four members exist from RC-2 so the classifier contract is
    complete; only ``NOTES_LOOKUP`` and ``MODEL_ONLY`` are dispatchable
    until RC-3 / RC-4 land the enrichment and knowledge-source routes.
    """

    NOTES_LOOKUP = "notes_lookup"
    NOTES_PLUS_MODEL = "notes_plus_model"
    NOTES_PLUS_KNOWLEDGE = "notes_plus_knowledge"
    MODEL_ONLY = "model_only"


@dataclass(frozen=True, slots=True)
class RouteClassification:
    """One successful classifier call's output.

    ``raw_output`` preserves the provider's verbatim output (the
    function-call arguments JSON for the OpenAI adapter) for the trace
    plane. There is deliberately no confidence field: function-calling
    classifiers do not return calibrated confidence and none is
    fabricated (D-108).
    """

    route: ChatRoute
    raw_output: str
    model_name: str
    latency_ms: int


@dataclass(frozen=True, slots=True)
class ChatRouteDecision:
    """Persisted routing trace for one ``/chat`` call (R-6, D-108).

    ``requested_route`` is the classifier's verdict, or ``None`` when no
    usable classification existed (provider unavailable, unusable
    output, or an empty question). ``effective_route`` is the route that
    actually answered. ``classifier_raw_output`` is ``""`` when no
    provider output existed and the verbatim output otherwise — including
    on the unusable-output contour (the D-035 truthful-provenance rule
    applied to the classifier seam). ``query_id`` links to the ``Query``
    row the dispatched route persisted; ``None`` only when the delegated
    retrieval seam raised ``NotImplementedError`` before a ``Query`` row
    existed.
    """

    decision_id: str
    community_id: str
    question_text: str
    requested_route: ChatRoute | None
    effective_route: ChatRoute
    classifier_model_name: str
    classifier_raw_output: str
    classifier_latency_ms: int
    query_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ChatQueryRewrite:
    """Persisted rewrite trace for one mixed-route execution (RC-3/RC-4).

    Written by ``notes_plus_model`` (RC-3) and ``notes_plus_knowledge``
    (RC-4) — every route that runs the retrieval-side rewrite. The 0008
    migration comment names only ``notes_plus_model`` because it predates
    RC-4; migrations are immutable history, this docstring is current.

    One row per execution of the route, written after the
    :class:`ChatRouteDecision` row it links to. ``rewritten_query`` is
    ``None`` when no usable rewrite existed (rewriter unavailable or
    unusable output — the route degraded to the original question with
    no date constraint). ``rewriter_raw_output`` is ``""`` when no
    provider output existed and the verbatim output otherwise —
    including on the unusable-output contour (the D-035
    truthful-provenance rule applied to the rewriter seam).
    ``subject_scope`` is the rewriter-emitted value — seam-ready, never
    emitted in this packet (see ``docs/assumptions.md``) — not the
    caller-provided scope the retrieval ran with (that one is recorded
    on the ``Query`` row).
    """

    rewrite_id: str
    decision_id: str
    community_id: str
    rewritten_query: str | None
    date_start: date | None
    date_end: date | None
    subject_scope: str | None
    rewriter_model_name: str
    rewriter_raw_output: str
    rewriter_latency_ms: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ChatKnowledgeSearch:
    """Persisted knowledge-search trace for one ``notes_plus_knowledge`` execution (RC-4).

    One row per execution of the route, written after the
    :class:`ChatRouteDecision` row it links to. The outward-rewrite
    provenance is folded into this row rather than a second table — the
    outward rewrite and the search are one pipeline step's trace with
    the same zero-or-one-per-decision cardinality. ``outward_query`` is
    always present: when no usable outward rewrite existed the route
    degraded to searching with the stripped original question, and that
    is what was searched. ``outward_rewriter_model_name`` is ``""`` only
    when no outward rewriter was wired at all;
    ``outward_rewriter_raw_output`` is ``""`` when no provider output
    existed and the verbatim output otherwise. ``raw_output`` is the
    knowledge provider's verbatim response body, ``""`` when the search
    failed with no output — the D-035 truthful-provenance rule applied
    to the search seam. ``result_count`` is the number of excerpts the
    route actually used (zero on the failed-search contour).
    """

    search_id: str
    decision_id: str
    community_id: str
    outward_query: str
    outward_rewriter_model_name: str
    outward_rewriter_raw_output: str
    outward_rewriter_latency_ms: int
    provider_name: str
    result_count: int
    raw_output: str
    latency_ms: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RoutedChatResult:
    """Outcome of ``RoutedChatService.chat`` (RC-2, D-108).

    ``answer`` reuses :class:`AnswerResult` so the control-surface
    adapter renders routed answers through the same fallback-graded
    formatting as ``/ask``. ``requested_route`` vs ``effective_route``
    keeps the R-6 requested/effective distinction visible to callers.
    """

    requested_route: ChatRoute | None
    effective_route: ChatRoute
    answer: AnswerResult
    decision_id: str
