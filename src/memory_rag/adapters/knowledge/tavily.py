"""Tavily knowledge-source adapter (RC-4, D-108).

The first real provider behind the core ``KnowledgeSource`` port. The
call is one HTTPS POST to the Tavily search endpoint via ``httpx``
(already a runtime dependency — no provider SDK is added). The API key
travels only in the ``Authorization`` header — never in the request
body, the persisted ``raw_output``, or any log line.

Provider hardening (R-9): the ``httpx`` client is built with an explicit
per-attempt ``timeout`` from the shared :class:`RetryPolicy`, and
``search`` runs the call through
:func:`~memory_rag.adapters.resilience.run_with_retries` with a
module-local error classifier (timeouts, transport errors, 5xx, and 429
are retryable; other 4xx fail fast) and a module-local 429
``Retry-After`` extractor. ``KnowledgeResult.latency_ms`` is measured
once around the whole bounded loop.

Failure split (mirrors the D-035 chat-seam contract): any ``httpx``
error or timeout after bounded retries —
:class:`KnowledgeSourceUnavailableError` (no usable output existed); a
2xx body that is not a usable result — non-JSON, wrong shape, or result
entries missing their required string fields —
:class:`KnowledgeSourceOutputError` carrying the body verbatim. An
empty ``results`` list is a valid outcome, not an error.

Core code only sees ``KnowledgeSource``; the HTTP client lives behind
this adapter (Invariant I-11).
"""

from __future__ import annotations

import json
import time

import httpx

from memory_rag.adapters.resilience import OutcomeClass, RetryPolicy, run_with_retries
from memory_rag.core.chat.knowledge import (
    KnowledgeExcerpt,
    KnowledgeResult,
    KnowledgeSourceOutputError,
    KnowledgeSourceUnavailableError,
)
from memory_rag.logging import get_logger

_log = get_logger(__name__)

_TAVILY_SEARCH_URL = "https://api.tavily.com/search"


def _classify_httpx_error(exc: Exception) -> OutcomeClass:
    """Split a Tavily call failure into retryable vs non-retryable (R-9).

    Retryable: request timeouts, transport/connection errors, 5xx, and
    rate limits (429). Everything else — auth failures, bad requests,
    other 4xx, and any unrecognized exception — is non-retryable: fail
    fast rather than retry blind.
    """
    if isinstance(exc, TimeoutError | httpx.TimeoutException):
        return OutcomeClass.RETRYABLE_FAILURE
    if isinstance(exc, httpx.TransportError):
        return OutcomeClass.RETRYABLE_FAILURE
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status >= 500 or status == 429:
            return OutcomeClass.RETRYABLE_FAILURE
    return OutcomeClass.NON_RETRYABLE_FAILURE


def _extract_retry_after_seconds(exc: Exception) -> float | None:
    """Read a numeric ``Retry-After`` (seconds) from a 429 response.

    Any other exception, a missing header, or a non-numeric/negative
    value returns ``None`` so the bounded loop falls back to computed
    backoff (the D-049 convention applied to the knowledge seam).
    """
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    if exc.response.status_code != 429:
        return None
    raw = exc.response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


class TavilyKnowledgeSource:
    """Sync Tavily search adapter behind the ``KnowledgeSource`` port (RC-4)."""

    def __init__(
        self,
        api_key: str,
        *,
        retry_policy: RetryPolicy,
        max_results: int,
        _client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("TAVILY_API_KEY is required for the tavily knowledge backend")
        if max_results < 1:
            raise ValueError("max_results must be a positive integer")
        self._retry_policy = retry_policy
        self._max_results = max_results
        if _client is not None:
            self._client = _client
        else:
            self._client = httpx.Client(
                timeout=retry_policy.timeout_seconds,
                headers={"Authorization": f"Bearer {api_key}"},
            )

    @property
    def provider_name(self) -> str:
        return "tavily"

    def search(self, query: str) -> KnowledgeResult:
        def _call() -> httpx.Response:
            response = self._client.post(
                _TAVILY_SEARCH_URL,
                json={"query": query, "max_results": self._max_results},
            )
            response.raise_for_status()
            return response

        start = time.perf_counter()
        try:
            response = run_with_retries(
                _call,
                policy=self._retry_policy,
                classify=_classify_httpx_error,
                retry_after=_extract_retry_after_seconds,
                label="tavily.search",
                logger=_log,
            )
        except (httpx.HTTPError, TimeoutError) as exc:
            raise KnowledgeSourceUnavailableError(
                f"Tavily search call failed "
                f"(bounded retry: max {self._retry_policy.max_attempts} attempts): "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        latency_ms = int((time.perf_counter() - start) * 1000)

        body = response.text
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise KnowledgeSourceOutputError(
                f"Tavily response body is not valid JSON: {exc.msg}",
                raw_output=body,
            ) from exc
        if not isinstance(payload, dict):
            raise KnowledgeSourceOutputError(
                "Tavily response is not a JSON object",
                raw_output=body,
            )
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise KnowledgeSourceOutputError(
                "Tavily response carries no results list",
                raw_output=body,
            )

        excerpts: list[KnowledgeExcerpt] = []
        for entry in raw_results[: self._max_results]:
            if not isinstance(entry, dict):
                raise KnowledgeSourceOutputError(
                    "Tavily result entry is not a JSON object",
                    raw_output=body,
                )
            url = entry.get("url")
            title = entry.get("title")
            content = entry.get("content")
            if not isinstance(url, str) or not url:
                raise KnowledgeSourceOutputError(
                    f"Tavily result entry carries no usable url: {url!r}",
                    raw_output=body,
                )
            if not isinstance(title, str):
                raise KnowledgeSourceOutputError(
                    f"Tavily result entry title is not a string: {title!r}",
                    raw_output=body,
                )
            if not isinstance(content, str):
                raise KnowledgeSourceOutputError(
                    f"Tavily result entry content is not a string: {content!r}",
                    raw_output=body,
                )
            excerpts.append(KnowledgeExcerpt(ref=url, title=title, text=content))

        return KnowledgeResult(
            excerpts=tuple(excerpts),
            raw_output=body,
            latency_ms=latency_ms,
        )
