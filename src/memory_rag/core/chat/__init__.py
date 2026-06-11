"""Routed-chat core: route taxonomy, classifier seam, model-only contract (RC-2, D-108)."""

from memory_rag.core.chat.classifier import (
    ChatRouteClassifier,
    ChatRouteClassifierError,
    ChatRouteClassifierUnavailableError,
    ChatRouteOutputError,
)
from memory_rag.core.chat.model_prompt import (
    MODEL_ONLY_PROMPT_VERSION,
    ModelOnlyAnswerError,
    build_model_only_prompt,
    parse_model_only_answer,
)
from memory_rag.core.chat.models import (
    ChatRoute,
    ChatRouteDecision,
    RouteClassification,
    RoutedChatResult,
)

__all__ = [
    "MODEL_ONLY_PROMPT_VERSION",
    "ChatRoute",
    "ChatRouteClassifier",
    "ChatRouteClassifierError",
    "ChatRouteClassifierUnavailableError",
    "ChatRouteDecision",
    "ChatRouteOutputError",
    "ModelOnlyAnswerError",
    "RouteClassification",
    "RoutedChatResult",
    "build_model_only_prompt",
    "parse_model_only_answer",
]
