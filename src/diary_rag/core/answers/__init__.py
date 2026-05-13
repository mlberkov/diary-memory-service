"""Channel-neutral answers domain.

The :class:`ChatClient` Protocol is the seam every chat-provider adapter
(mock today; real providers later) satisfies. :class:`ChatResponse` is
the channel-neutral return shape that carries the LLM's raw output plus
the provenance the :class:`~diary_rag.core.diary.models.AnswerTrace`
persists (``model_name``, ``token_counts``, ``latency_ms``).

``ChatResponse.latency_ms`` is the single source of truth for chat-call
latency — no other layer measures it independently.
"""

from diary_rag.core.answers.client import (
    ChatClient,
    ChatProviderUnavailableError,
    ChatResponse,
)

__all__ = ["ChatClient", "ChatProviderUnavailableError", "ChatResponse"]
