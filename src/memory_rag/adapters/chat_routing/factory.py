"""Single factories for the configured classifier and rewriter.

Boot gate (R-10) and request-path wiring (``get_dispatcher``) both go
through these functions so they cannot disagree on backend or model
name. ``classifier_backend="openai"`` requires ``OPENAI_API_KEY`` and
the canonical ``CLASSIFIER_MODEL`` (RC-2, D-108); ``mock`` is the
test/dev default and has no external dependencies. The retry policy
reuses the shared ``provider_*`` knobs (R-9). The query rewriter (RC-3)
rides the classifier contour — same backend knob, same model pin — so
no third knob set exists.
"""

from __future__ import annotations

from memory_rag.adapters.chat_routing.mock import MockRouteClassifier
from memory_rag.adapters.chat_routing.rewrite_mock import MockQueryRewriter
from memory_rag.adapters.resilience import RetryPolicy
from memory_rag.config import Settings
from memory_rag.core.chat import ChatRouteClassifier, QueryRewriter


def _retry_policy(settings: Settings) -> RetryPolicy:
    return RetryPolicy(
        timeout_seconds=settings.provider_timeout_seconds,
        max_attempts=settings.provider_max_attempts,
        backoff_base_seconds=settings.provider_backoff_base_seconds,
        backoff_cap_seconds=settings.provider_backoff_cap_seconds,
    )


def build_route_classifier(settings: Settings) -> ChatRouteClassifier:
    if settings.classifier_backend == "openai":
        from memory_rag.adapters.chat_routing.openai_client import OpenAIRouteClassifier

        return OpenAIRouteClassifier(
            api_key=settings.openai_api_key,
            model_name=settings.classifier_model,
            retry_policy=_retry_policy(settings),
        )
    return MockRouteClassifier()


def build_query_rewriter(settings: Settings) -> QueryRewriter:
    if settings.classifier_backend == "openai":
        from memory_rag.adapters.chat_routing.rewrite_openai import OpenAIQueryRewriter

        return OpenAIQueryRewriter(
            api_key=settings.openai_api_key,
            model_name=settings.classifier_model,
            retry_policy=_retry_policy(settings),
        )
    return MockQueryRewriter()
