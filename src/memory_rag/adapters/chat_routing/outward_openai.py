"""OpenAI outward-rewriter adapter (RC-4, D-108).

Rides the classifier contour: same backend knob, same canonical
``gpt-4.1-mini`` pin, same shared ``provider_*`` retry knobs — no new
knob set (the RC-3 retrieval-rewriter discipline). The call is
``chat.completions.create`` with forced function calling
(``tool_choice`` pinned to the ``rewrite_outward_query`` tool) and
``temperature=0``. The tool takes one required ``search_query`` string.

The retrieved note chunks condition the rewrite (the D-108 enrichment
pattern: "retrieve personal context first, rewrite the outward query
using it"): they are rendered into the user message as context lines
beneath the question, and the system text instructs the model to fold
only the relevant specifics into a self-contained external search
query — never raw note text wholesale.

Provider hardening (R-9): the SDK client is built with an explicit
per-attempt ``timeout`` and ``max_retries=0`` (the adapter's own bounded
loop is the single retry authority), and ``rewrite_outward`` runs the
API call through
:func:`~memory_rag.adapters.resilience.run_with_retries` with
rate-limit-aware backoff. ``OutwardRewrite.latency_ms`` is measured once
around the whole bounded loop.

Failure split (mirrors the D-035 chat-seam contract):
``openai.OpenAIError`` / ``TimeoutError`` after bounded retries —
:class:`OutwardRewriterUnavailableError` (no output existed); output
that exists but is not a usable rewrite — missing tool call, malformed
arguments JSON, empty ``search_query`` —
:class:`OutwardRewriteOutputError` carrying the output verbatim.

Core code only sees ``OutwardQueryRewriter``; the SDK lives behind this
adapter (Invariant I-11).
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from memory_rag.adapters.resilience import (
    RetryPolicy,
    classify_openai_error,
    extract_retry_after_seconds,
    run_with_retries,
)
from memory_rag.core.chat.outward import (
    OutwardRewrite,
    OutwardRewriteOutputError,
    OutwardRewriterUnavailableError,
)
from memory_rag.logging import get_logger

if TYPE_CHECKING:
    from openai import OpenAI
    from openai.types.chat import ChatCompletion

_log = get_logger(__name__)

_SYSTEM_TEXT = (
    "You rewrite a user's question into one self-contained query for an "
    "external web search. The user also has personal notes; relevant "
    "note excerpts are provided as context lines beneath the question. "
    "Call rewrite_outward_query with search_query — the question "
    "rephrased for a general search engine, folding in only the "
    "specific facts from the context that sharpen the search (ages, "
    "names of activities, concrete circumstances). Never copy note "
    "text wholesale, never include names of people, and never address "
    "the notes themselves — the query must stand alone."
)


class OpenAIOutwardRewriter:
    """Sync OpenAI outward rewriter (RC-4, D-108)."""

    def __init__(
        self,
        api_key: str,
        *,
        model_name: str,
        retry_policy: RetryPolicy,
        _client: Any = None,
    ) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for the OpenAI outward-rewriter backend")
        if not model_name:
            raise ValueError("model_name is required for the OpenAI outward-rewriter backend")
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

    def rewrite_outward(self, question: str, *, notes_context: tuple[str, ...]) -> OutwardRewrite:
        import openai

        if notes_context:
            context_block = "\n".join(f"- {text}" for text in notes_context)
            user_text = f"Question: {question}\n\nNote context:\n{context_block}"
        else:
            user_text = f"Question: {question}\n\nNote context:\n(none)"

        def _call() -> ChatCompletion:
            return self._client.chat.completions.create(
                model=self._model_name,
                messages=[
                    {"role": "system", "content": _SYSTEM_TEXT},
                    {"role": "user", "content": user_text},
                ],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "rewrite_outward_query",
                            "description": (
                                "Rewrite the question into one self-contained "
                                "external search query."
                            ),
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "search_query": {"type": "string"},
                                },
                                "required": ["search_query"],
                            },
                        },
                    }
                ],
                tool_choice={
                    "type": "function",
                    "function": {"name": "rewrite_outward_query"},
                },
                temperature=0,
            )

        start = time.perf_counter()
        try:
            response = run_with_retries(
                _call,
                policy=self._retry_policy,
                classify=classify_openai_error,
                retry_after=extract_retry_after_seconds,
                label="openai.outward_rewriter",
                logger=_log,
            )
        except (openai.OpenAIError, TimeoutError) as exc:
            raise OutwardRewriterUnavailableError(
                f"OpenAI outward-rewriter call failed "
                f"(bounded retry: max {self._retry_policy.max_attempts} attempts): "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        latency_ms = int((time.perf_counter() - start) * 1000)

        message = response.choices[0].message
        tool_calls = message.tool_calls or []
        if not tool_calls:
            raise OutwardRewriteOutputError(
                "outward rewriter response carries no tool call",
                raw_output=message.content or "",
            )
        # ``tool_calls`` may carry non-function variants in the SDK union;
        # only a function call has arguments to read.
        function = getattr(tool_calls[0], "function", None)
        if function is None:
            raise OutwardRewriteOutputError(
                "outward rewriter tool call carries no function payload",
                raw_output=message.content or "",
            )
        arguments = str(function.arguments or "")
        try:
            payload = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise OutwardRewriteOutputError(
                f"outward rewriter tool arguments are not valid JSON: {exc}",
                raw_output=arguments,
            ) from exc
        if not isinstance(payload, dict):
            raise OutwardRewriteOutputError(
                "outward rewriter tool arguments are not a JSON object",
                raw_output=arguments,
            )

        raw_query = payload.get("search_query")
        if not isinstance(raw_query, str) or not raw_query.strip():
            raise OutwardRewriteOutputError(
                f"outward rewriter named no usable search_query: {raw_query!r}",
                raw_output=arguments,
            )

        return OutwardRewrite(
            search_query=raw_query.strip(),
            raw_output=arguments,
            model_name=self._model_name,
            latency_ms=latency_ms,
        )
