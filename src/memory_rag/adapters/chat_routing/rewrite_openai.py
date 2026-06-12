"""OpenAI query-rewriter adapter (RC-3, D-108).

Rides the classifier contour: same backend knob, same canonical
``gpt-4.1-mini`` pin, same shared ``provider_*`` retry knobs — no third
knob set. The call is ``chat.completions.create`` with forced function
calling (``tool_choice`` pinned to the ``rewrite_query`` tool) and
``temperature=0``. The tool takes a required ``retrieval_query`` string
plus optional ``date_from`` / ``date_to`` ISO-date strings; there is
deliberately no subject parameter (see ``docs/assumptions.md``).

The system text embeds the caller-supplied ``today`` so relative date
expressions ("last month") resolve against an honest anchor the model
cannot invent.

Provider hardening (R-9): the SDK client is built with an explicit
per-attempt ``timeout`` and ``max_retries=0`` (the adapter's own bounded
loop is the single retry authority), and ``rewrite`` runs the API call
through :func:`~memory_rag.adapters.resilience.run_with_retries` with
rate-limit-aware backoff. ``QueryRewrite.latency_ms`` is measured once
around the whole bounded loop.

Failure split (mirrors the D-035 chat-seam contract):
``openai.OpenAIError`` / ``TimeoutError`` after bounded retries →
:class:`QueryRewriterUnavailableError` (no output existed); output that
exists but is not a usable rewrite — missing tool call, malformed
arguments JSON, empty ``retrieval_query``, unparseable date bounds, a
contradictory range — → :class:`QueryRewriteOutputError` carrying the
output verbatim.

Core code only sees ``QueryRewriter``; the SDK lives behind this
adapter (Invariant I-11).
"""

from __future__ import annotations

import json
import time
from datetime import date
from typing import TYPE_CHECKING, Any

from memory_rag.adapters.resilience import (
    RetryPolicy,
    classify_openai_error,
    extract_retry_after_seconds,
    run_with_retries,
)
from memory_rag.core.chat.rewrite import (
    QueryRewrite,
    QueryRewriteOutputError,
    QueryRewriterUnavailableError,
)
from memory_rag.core.domain.models import DateRange
from memory_rag.logging import get_logger

if TYPE_CHECKING:
    from openai import OpenAI
    from openai.types.chat import ChatCompletion

_log = get_logger(__name__)


def _system_text(today: date) -> str:
    return (
        "You rewrite a user's question into a search query over their "
        "saved notes for a shared-notes memory service. "
        "Call rewrite_query with retrieval_query — the words most likely "
        "to appear in the relevant notes (drop filler, keep names and "
        "concrete terms) — and, only when the question names or clearly "
        "implies a time period, date_from and/or date_to as inclusive "
        "ISO dates (YYYY-MM-DD). "
        f"Today is {today.isoformat()}; resolve relative expressions "
        "like 'last month' against it. Omit date_from/date_to when the "
        "question carries no time constraint."
    )


def _parse_iso_date(value: object, *, field: str, raw_output: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise QueryRewriteOutputError(
            f"rewriter {field} is not a string: {value!r}",
            raw_output=raw_output,
        )
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise QueryRewriteOutputError(
            f"rewriter {field} is not an ISO date: {value!r}",
            raw_output=raw_output,
        ) from exc


class OpenAIQueryRewriter:
    """Sync OpenAI query rewriter (RC-3, D-108)."""

    def __init__(
        self,
        api_key: str,
        *,
        model_name: str,
        retry_policy: RetryPolicy,
        _client: Any = None,
    ) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for the OpenAI rewriter backend")
        if not model_name:
            raise ValueError("model_name is required for the OpenAI rewriter backend")
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

    def rewrite(self, question: str, *, today: date) -> QueryRewrite:
        import openai

        def _call() -> ChatCompletion:
            return self._client.chat.completions.create(
                model=self._model_name,
                messages=[
                    {"role": "system", "content": _system_text(today)},
                    {"role": "user", "content": question},
                ],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "rewrite_query",
                            "description": (
                                "Rewrite the question into a retrieval query "
                                "with optional inclusive date bounds."
                            ),
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "retrieval_query": {"type": "string"},
                                    "date_from": {
                                        "type": "string",
                                        "description": "Inclusive ISO date (YYYY-MM-DD).",
                                    },
                                    "date_to": {
                                        "type": "string",
                                        "description": "Inclusive ISO date (YYYY-MM-DD).",
                                    },
                                },
                                "required": ["retrieval_query"],
                            },
                        },
                    }
                ],
                tool_choice={"type": "function", "function": {"name": "rewrite_query"}},
                temperature=0,
            )

        start = time.perf_counter()
        try:
            response = run_with_retries(
                _call,
                policy=self._retry_policy,
                classify=classify_openai_error,
                retry_after=extract_retry_after_seconds,
                label="openai.query_rewriter",
                logger=_log,
            )
        except (openai.OpenAIError, TimeoutError) as exc:
            raise QueryRewriterUnavailableError(
                f"OpenAI query-rewriter call failed "
                f"(bounded retry: max {self._retry_policy.max_attempts} attempts): "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        latency_ms = int((time.perf_counter() - start) * 1000)

        message = response.choices[0].message
        tool_calls = message.tool_calls or []
        if not tool_calls:
            raise QueryRewriteOutputError(
                "rewriter response carries no tool call",
                raw_output=message.content or "",
            )
        # ``tool_calls`` may carry non-function variants in the SDK union;
        # only a function call has arguments to read.
        function = getattr(tool_calls[0], "function", None)
        if function is None:
            raise QueryRewriteOutputError(
                "rewriter tool call carries no function payload",
                raw_output=message.content or "",
            )
        arguments = str(function.arguments or "")
        try:
            payload = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise QueryRewriteOutputError(
                f"rewriter tool arguments are not valid JSON: {exc}",
                raw_output=arguments,
            ) from exc
        if not isinstance(payload, dict):
            raise QueryRewriteOutputError(
                "rewriter tool arguments are not a JSON object",
                raw_output=arguments,
            )

        raw_query = payload.get("retrieval_query")
        if not isinstance(raw_query, str) or not raw_query.strip():
            raise QueryRewriteOutputError(
                f"rewriter named no usable retrieval_query: {raw_query!r}",
                raw_output=arguments,
            )
        retrieval_query = raw_query.strip()

        date_from = _parse_iso_date(
            payload.get("date_from"), field="date_from", raw_output=arguments
        )
        date_to = _parse_iso_date(payload.get("date_to"), field="date_to", raw_output=arguments)
        date_range: DateRange | None = None
        if date_from is not None or date_to is not None:
            try:
                date_range = DateRange(start=date_from, end=date_to)
            except ValueError as exc:
                raise QueryRewriteOutputError(
                    f"rewriter date bounds are contradictory: {exc}",
                    raw_output=arguments,
                ) from exc

        return QueryRewrite(
            retrieval_query=retrieval_query,
            date_range=date_range,
            subject_scope=None,
            raw_output=arguments,
            model_name=self._model_name,
            latency_ms=latency_ms,
        )
