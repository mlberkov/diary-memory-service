"""OpenAI chat adapter (D-037).

Canonical Slice 4.5 contour: ``gpt-4.1`` via ``chat.completions.create``
with ``response_format={"type": "json_object"}`` and ``temperature=0``.

Provider hardening (R-9, Slice 6.1 / D-047): the SDK client is built with an
explicit per-attempt ``timeout`` and ``max_retries=0`` (the adapter's own
bounded loop is the single retry authority), and ``complete`` runs the API call
through :func:`~memory_rag.adapters.resilience.run_with_retries`.
``ChatResponse.latency_ms`` is measured once around the whole bounded loop, so
it is the total elapsed time across every attempt and remains the single
source of truth that ``QueryService`` persists into ``AnswerTrace``.

``openai.OpenAIError`` (the SDK base class) and ``TimeoutError`` are translated
to :class:`ChatProviderUnavailableError` — now only after bounded retries are
exhausted — so the existing D-035 grading path
(``FallbackMode.PROVIDER_UNAVAILABLE``) handles provider failures without
further retry or repair.

Domain code only sees ``ChatClient``; the SDK lives behind this adapter
(Invariant I-11).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from memory_rag.adapters.resilience import RetryPolicy, classify_openai_error, run_with_retries
from memory_rag.core.answers.client import ChatProviderUnavailableError, ChatResponse
from memory_rag.core.domain.answer_prompt import AnswerPrompt
from memory_rag.logging import get_logger

if TYPE_CHECKING:
    from openai import OpenAI
    from openai.types.chat import ChatCompletion

_log = get_logger(__name__)


class OpenAIChatClient:
    """Sync OpenAI chat provider (D-037)."""

    def __init__(
        self,
        api_key: str,
        *,
        model_name: str,
        retry_policy: RetryPolicy,
        _client: Any = None,
    ) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for the OpenAI chat backend")
        if not model_name:
            raise ValueError("model_name is required for the OpenAI chat backend")
        self._model_name = model_name
        self._retry_policy = retry_policy

        self._client: OpenAI
        if _client is not None:
            self._client = _client
        else:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=api_key,
                timeout=retry_policy.timeout_seconds,
                max_retries=0,
            )

    @property
    def model_name(self) -> str:
        return self._model_name

    def complete(self, prompt: AnswerPrompt) -> ChatResponse:
        import openai

        def _call() -> ChatCompletion:
            return self._client.chat.completions.create(
                model=self._model_name,
                messages=[
                    {"role": "system", "content": prompt.system_text},
                    {"role": "user", "content": prompt.user_text},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )

        start = time.perf_counter()
        try:
            response = run_with_retries(
                _call,
                policy=self._retry_policy,
                classify=classify_openai_error,
                label="openai.chat",
                logger=_log,
            )
        except (openai.OpenAIError, TimeoutError) as exc:
            raise ChatProviderUnavailableError(
                f"OpenAI chat call failed "
                f"(bounded retry: max {self._retry_policy.max_attempts} attempts): "
                f"{type(exc).__name__}: {exc}"
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
