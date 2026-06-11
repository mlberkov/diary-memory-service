"""OpenAI route-classifier adapter (RC-2, D-108).

Canonical contour: ``gpt-4.1-mini`` via ``chat.completions.create`` with
forced function calling (``tool_choice`` pinned to the ``select_route``
tool, whose single ``route`` parameter is an enum of the four canonical
:class:`ChatRoute` values) and ``temperature=0``.

Provider hardening (R-9): the SDK client is built with an explicit
per-attempt ``timeout`` and ``max_retries=0`` (the adapter's own bounded
loop is the single retry authority), and ``classify`` runs the API call
through :func:`~memory_rag.adapters.resilience.run_with_retries` with
rate-limit-aware backoff. ``RouteClassification.latency_ms`` is measured
once around the whole bounded loop — total elapsed time across every
attempt, including inter-attempt backoff.

Failure split (mirrors the D-035 chat-seam contract):
``openai.OpenAIError`` / ``TimeoutError`` after bounded retries →
:class:`ChatRouteClassifierUnavailableError` (no output existed);
output that exists but does not name a known route — missing tool call,
malformed arguments JSON, unknown route value —
→ :class:`ChatRouteOutputError` carrying the output verbatim.

Core code only sees ``ChatRouteClassifier``; the SDK lives behind this
adapter (Invariant I-11).
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, Final

from memory_rag.adapters.resilience import (
    RetryPolicy,
    classify_openai_error,
    extract_retry_after_seconds,
    run_with_retries,
)
from memory_rag.core.chat.classifier import (
    ChatRouteClassifierUnavailableError,
    ChatRouteOutputError,
)
from memory_rag.core.chat.models import ChatRoute, RouteClassification
from memory_rag.logging import get_logger

if TYPE_CHECKING:
    from openai import OpenAI
    from openai.types.chat import ChatCompletion

_log = get_logger(__name__)

_SYSTEM_TEXT: Final[str] = (
    "You classify a user's question into exactly one answer route for a "
    "shared-notes memory service. Routes: "
    '"notes_lookup" — the answer is a fact recorded in the user\'s saved '
    "notes (who/what/when about their own records); "
    '"notes_plus_model" — the answer needs general model knowledge '
    "combined with the user's personal context from their notes "
    "(advice or suggestions tailored to their situation); "
    '"notes_plus_knowledge" — the answer needs external knowledge sources '
    "combined with the user's personal context (explanations of outside "
    "facts applied to their situation); "
    '"model_only" — the answer is general knowledge with no connection to '
    "the user's notes (definitions, general explanations). "
    "Call select_route with the single best route."
)


class OpenAIRouteClassifier:
    """Sync OpenAI route classifier (RC-2, D-108)."""

    def __init__(
        self,
        api_key: str,
        *,
        model_name: str,
        retry_policy: RetryPolicy,
        _client: Any = None,
    ) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for the OpenAI classifier backend")
        if not model_name:
            raise ValueError("model_name is required for the OpenAI classifier backend")
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

    def classify(self, question: str) -> RouteClassification:
        import openai

        def _call() -> ChatCompletion:
            return self._client.chat.completions.create(
                model=self._model_name,
                messages=[
                    {"role": "system", "content": _SYSTEM_TEXT},
                    {"role": "user", "content": question},
                ],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "select_route",
                            "description": ("Select the answer route for the user's question."),
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "route": {
                                        "type": "string",
                                        "enum": [route.value for route in ChatRoute],
                                    }
                                },
                                "required": ["route"],
                            },
                        },
                    }
                ],
                tool_choice={"type": "function", "function": {"name": "select_route"}},
                temperature=0,
            )

        start = time.perf_counter()
        try:
            response = run_with_retries(
                _call,
                policy=self._retry_policy,
                classify=classify_openai_error,
                retry_after=extract_retry_after_seconds,
                label="openai.route_classifier",
                logger=_log,
            )
        except (openai.OpenAIError, TimeoutError) as exc:
            raise ChatRouteClassifierUnavailableError(
                f"OpenAI route-classifier call failed "
                f"(bounded retry: max {self._retry_policy.max_attempts} attempts): "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        latency_ms = int((time.perf_counter() - start) * 1000)

        message = response.choices[0].message
        tool_calls = message.tool_calls or []
        if not tool_calls:
            raise ChatRouteOutputError(
                "classifier response carries no tool call",
                raw_output=message.content or "",
            )
        # ``tool_calls`` may carry non-function variants in the SDK union;
        # only a function call has arguments to read.
        function = getattr(tool_calls[0], "function", None)
        if function is None:
            raise ChatRouteOutputError(
                "classifier tool call carries no function payload",
                raw_output=message.content or "",
            )
        arguments = str(function.arguments or "")
        try:
            payload = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise ChatRouteOutputError(
                f"classifier tool arguments are not valid JSON: {exc}",
                raw_output=arguments,
            ) from exc
        raw_route = payload.get("route") if isinstance(payload, dict) else None
        if not isinstance(raw_route, str):
            raise ChatRouteOutputError(
                f"classifier named no usable route: {raw_route!r}",
                raw_output=arguments,
            )
        try:
            route = ChatRoute(raw_route)
        except ValueError as exc:
            raise ChatRouteOutputError(
                f"classifier named an unknown route: {raw_route!r}",
                raw_output=arguments,
            ) from exc

        return RouteClassification(
            route=route,
            raw_output=arguments,
            model_name=self._model_name,
            latency_ms=latency_ms,
        )
