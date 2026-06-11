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
from datetime import datetime
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
