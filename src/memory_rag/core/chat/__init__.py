"""Routed-chat core: route taxonomy, classifier seam, model-only contract (RC-2, D-108);
rewrite seam and notes-plus-model contract (RC-3)."""

from memory_rag.core.chat.classifier import (
    ChatRouteClassifier,
    ChatRouteClassifierError,
    ChatRouteClassifierUnavailableError,
    ChatRouteOutputError,
)
from memory_rag.core.chat.enriched_prompt import (
    ESCALATION_CLAUSE,
    NOTES_PLUS_MODEL_PROMPT_VERSION,
    NotesPlusModelAnswer,
    NotesPlusModelAnswerError,
    build_notes_plus_model_prompt,
    parse_notes_plus_model_answer,
)
from memory_rag.core.chat.model_prompt import (
    MODEL_ONLY_PROMPT_VERSION,
    ModelOnlyAnswerError,
    build_model_only_prompt,
    parse_model_only_answer,
)
from memory_rag.core.chat.models import (
    ChatQueryRewrite,
    ChatRoute,
    ChatRouteDecision,
    RouteClassification,
    RoutedChatResult,
)
from memory_rag.core.chat.rewrite import (
    QueryRewrite,
    QueryRewriteOutputError,
    QueryRewriter,
    QueryRewriterError,
    QueryRewriterUnavailableError,
)

__all__ = [
    "ESCALATION_CLAUSE",
    "MODEL_ONLY_PROMPT_VERSION",
    "NOTES_PLUS_MODEL_PROMPT_VERSION",
    "ChatQueryRewrite",
    "ChatRoute",
    "ChatRouteClassifier",
    "ChatRouteClassifierError",
    "ChatRouteClassifierUnavailableError",
    "ChatRouteDecision",
    "ChatRouteOutputError",
    "ModelOnlyAnswerError",
    "NotesPlusModelAnswer",
    "NotesPlusModelAnswerError",
    "QueryRewrite",
    "QueryRewriteOutputError",
    "QueryRewriter",
    "QueryRewriterError",
    "QueryRewriterUnavailableError",
    "RouteClassification",
    "RoutedChatResult",
    "build_model_only_prompt",
    "build_notes_plus_model_prompt",
    "parse_model_only_answer",
    "parse_notes_plus_model_answer",
]
