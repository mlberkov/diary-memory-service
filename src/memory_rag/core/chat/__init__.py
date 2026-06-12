"""Routed-chat core: route taxonomy, classifier seam, model-only contract (RC-2, D-108);
rewrite seam and notes-plus-model contract (RC-3); knowledge-source seam,
outward-rewrite seam, and notes-plus-knowledge contract (RC-4)."""

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
from memory_rag.core.chat.knowledge import (
    KnowledgeExcerpt,
    KnowledgeResult,
    KnowledgeSource,
    KnowledgeSourceError,
    KnowledgeSourceOutputError,
    KnowledgeSourceUnavailableError,
)
from memory_rag.core.chat.knowledge_prompt import (
    NOTES_PLUS_KNOWLEDGE_PROMPT_VERSION,
    NotesPlusKnowledgeAnswer,
    NotesPlusKnowledgeAnswerError,
    build_notes_plus_knowledge_prompt,
    parse_notes_plus_knowledge_answer,
)
from memory_rag.core.chat.model_prompt import (
    MODEL_ONLY_PROMPT_VERSION,
    ModelOnlyAnswerError,
    build_model_only_prompt,
    parse_model_only_answer,
)
from memory_rag.core.chat.models import (
    ChatKnowledgeSearch,
    ChatQueryRewrite,
    ChatRoute,
    ChatRouteDecision,
    RouteClassification,
    RoutedChatResult,
)
from memory_rag.core.chat.outward import (
    OutwardQueryRewriter,
    OutwardRewrite,
    OutwardRewriteOutputError,
    OutwardRewriterError,
    OutwardRewriterUnavailableError,
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
    "NOTES_PLUS_KNOWLEDGE_PROMPT_VERSION",
    "NOTES_PLUS_MODEL_PROMPT_VERSION",
    "ChatKnowledgeSearch",
    "ChatQueryRewrite",
    "ChatRoute",
    "ChatRouteClassifier",
    "ChatRouteClassifierError",
    "ChatRouteClassifierUnavailableError",
    "ChatRouteDecision",
    "ChatRouteOutputError",
    "KnowledgeExcerpt",
    "KnowledgeResult",
    "KnowledgeSource",
    "KnowledgeSourceError",
    "KnowledgeSourceOutputError",
    "KnowledgeSourceUnavailableError",
    "ModelOnlyAnswerError",
    "NotesPlusKnowledgeAnswer",
    "NotesPlusKnowledgeAnswerError",
    "NotesPlusModelAnswer",
    "NotesPlusModelAnswerError",
    "OutwardQueryRewriter",
    "OutwardRewrite",
    "OutwardRewriteOutputError",
    "OutwardRewriterError",
    "OutwardRewriterUnavailableError",
    "QueryRewrite",
    "QueryRewriteOutputError",
    "QueryRewriter",
    "QueryRewriterError",
    "QueryRewriterUnavailableError",
    "RouteClassification",
    "RoutedChatResult",
    "build_model_only_prompt",
    "build_notes_plus_knowledge_prompt",
    "build_notes_plus_model_prompt",
    "parse_model_only_answer",
    "parse_notes_plus_knowledge_answer",
    "parse_notes_plus_model_answer",
]
