"""``ChatClient`` Protocol and ``ChatResponse`` shape (Slice 4.3a, D-034).

Every chat provider — the deterministic test mock today, real providers
later — exposes ``model_name`` and a sync ``complete(prompt) ->
ChatResponse``. Domain code depends only on this Protocol, never on a
provider SDK (Invariant I-11).

``ChatResponse.latency_ms`` is the single source of truth for chat-call
latency; ``QueryService`` persists it directly into ``AnswerTrace`` and
does not measure latency independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from diary_rag.core.domain.answer_prompt import AnswerPrompt


@dataclass(frozen=True, slots=True)
class ChatResponse:
    """Channel-neutral return shape for one chat-client call.

    ``raw_text`` is the provider's structured-answer JSON, parsed by
    :func:`~diary_rag.core.domain.answer_schema.parse_structured_answer`.
    ``token_counts`` is a free-form provider-attributed map (e.g.
    ``{"prompt": …, "completion": …}``); empty when the backend cannot
    report tokens (the mock approximates it from character counts).
    ``latency_ms`` is the provider-attributed elapsed time and is the
    only latency value the persistence layer records.
    """

    raw_text: str
    model_name: str
    token_counts: dict[str, int]
    latency_ms: int


class ChatClient(Protocol):
    """Sync chat provider seam used by ``QueryService.answer``."""

    @property
    def model_name(self) -> str: ...

    def complete(self, prompt: AnswerPrompt) -> ChatResponse: ...


class ChatProviderUnavailableError(RuntimeError):
    """The chat provider is unreachable / unusable for this call (D-035).

    Real provider adapters raise this on timeout, HTTP failure, auth
    failure, or any other condition that prevents producing a usable
    :class:`ChatResponse`. ``QueryService.answer`` catches the exception
    once and grades the call as ``FallbackMode.PROVIDER_UNAVAILABLE`` —
    no retry, no repair (recovery workflows are Phase-6 work).
    """
