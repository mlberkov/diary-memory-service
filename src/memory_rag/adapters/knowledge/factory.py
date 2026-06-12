"""Single factory for the configured knowledge source (RC-4, D-108).

Boot gate (R-10) and request-path wiring (``get_dispatcher``) both go
through this function so they cannot disagree on backend or provider.
``knowledge_backend="tavily"`` requires ``TAVILY_API_KEY``; ``mock`` is
the test/dev default and has no external dependencies. The retry policy
reuses the shared ``provider_*`` knobs (R-9); ``knowledge_max_results``
caps how many excerpts one search may return (see
``docs/assumptions.md``).
"""

from __future__ import annotations

from memory_rag.adapters.knowledge.mock import MockKnowledgeSource
from memory_rag.adapters.resilience import RetryPolicy
from memory_rag.config import Settings
from memory_rag.core.chat.knowledge import KnowledgeSource


def build_knowledge_source(settings: Settings) -> KnowledgeSource:
    if settings.knowledge_backend == "tavily":
        from memory_rag.adapters.knowledge.tavily import TavilyKnowledgeSource

        return TavilyKnowledgeSource(
            api_key=settings.tavily_api_key,
            retry_policy=RetryPolicy(
                timeout_seconds=settings.provider_timeout_seconds,
                max_attempts=settings.provider_max_attempts,
                backoff_base_seconds=settings.provider_backoff_base_seconds,
                backoff_cap_seconds=settings.provider_backoff_cap_seconds,
            ),
            max_results=settings.knowledge_max_results,
        )
    return MockKnowledgeSource()
