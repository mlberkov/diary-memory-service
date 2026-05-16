"""OpenAI chat adapter (D-037).

Canonical Slice 4.5 contour: ``gpt-4.1`` via ``chat.completions.create``
with ``response_format={"type": "json_object"}`` and ``temperature=0``,
single attempt, no retries (Phase 6 owns hardening, R-9).

Latency is measured client-side with :func:`time.perf_counter` because
the SDK does not expose server-side timing; the measurement is the
``ChatResponse.latency_ms`` source of truth that ``QueryService``
persists into ``AnswerTrace``.

``openai.OpenAIError`` (the SDK base class) and ``TimeoutError`` are
translated to :class:`ChatProviderUnavailableError` so the existing
D-035 grading path (``FallbackMode.PROVIDER_UNAVAILABLE``) handles
provider failures without retries or repair.

Domain code only sees ``ChatClient``; the SDK lives behind this adapter
(Invariant I-11).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from memory_rag.core.answers.client import ChatProviderUnavailableError, ChatResponse
from memory_rag.core.domain.answer_prompt import AnswerPrompt

if TYPE_CHECKING:
    from openai import OpenAI


class OpenAIChatClient:
    """Sync OpenAI chat provider (D-037)."""

    def __init__(self, api_key: str, *, model_name: str) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for the OpenAI chat backend")
        if not model_name:
            raise ValueError("model_name is required for the OpenAI chat backend")
        from openai import OpenAI

        self._client: OpenAI = OpenAI(api_key=api_key)
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def complete(self, prompt: AnswerPrompt) -> ChatResponse:
        import openai

        start = time.perf_counter()
        try:
            response = self._client.chat.completions.create(
                model=self._model_name,
                messages=[
                    {"role": "system", "content": prompt.system_text},
                    {"role": "user", "content": prompt.user_text},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
        except (openai.OpenAIError, TimeoutError) as exc:
            raise ChatProviderUnavailableError(
                f"OpenAI chat call failed: {type(exc).__name__}: {exc}"
            ) from exc
        latency_ms = int((time.perf_counter() - start) * 1000)

        raw_text = response.choices[0].message.content or ""
        token_counts: dict[str, int] = {}
        usage = response.usage
        if usage is not None:
            token_counts = {
                "prompt": usage.prompt_tokens,
                "completion": usage.completion_tokens,
            }
        return ChatResponse(
            raw_text=raw_text,
            model_name=self._model_name,
            token_counts=token_counts,
            latency_ms=latency_ms,
        )
