"""Shared adapter-side timeout / bounded-retry primitive (R-9).

Provider calls must have an explicit timeout and a bounded number of attempts —
no unbounded wait, no unbounded retry loop (R-9). This module is the single
adapter-side place that enforces that: :class:`RetryPolicy` carries the knobs,
:func:`classify_openai_error` splits provider failures into retryable and
non-retryable, :func:`compute_backoff` and :func:`extract_retry_after_seconds`
size the inter-attempt wait, and :func:`run_with_retries` runs the bounded loop.

The loop itself is provider-agnostic — OpenAI specifics enter only through the
injected ``classify`` and ``retry_after`` callables. This is adapter code, so
importing the ``openai`` SDK here is allowed (Invariant I-11); core code never
sees it.

A retryable failure is followed by an inter-attempt wait before the next
attempt: exponential backoff with full jitter, capped at
``RetryPolicy.backoff_cap_seconds``. When a rate-limit failure carries a server
``Retry-After``, that delay is honored instead — also clamped to the cap, so the
worst-case wall time stays bounded (D-049). The wait uses an injected ``sleep``
callable so tests do not block on real time.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from logging import Logger
from typing import TypeVar

_T = TypeVar("_T")


class OutcomeClass(StrEnum):
    """How one provider-call attempt ended."""

    SUCCESS = "success"
    RETRYABLE_FAILURE = "retryable_failure"
    NON_RETRYABLE_FAILURE = "non_retryable_failure"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """The R-9 knobs for a provider call.

    ``timeout_seconds`` is the per-attempt wall-clock budget; ``max_attempts`` is
    the total number of attempts including the first (``1`` disables retries).
    ``backoff_base_seconds`` and ``backoff_cap_seconds`` size the inter-attempt
    wait: exponential backoff with full jitter, clamped to the cap.

    Worst-case bounded wall time for one call is ``timeout_seconds *
    max_attempts + backoff_cap_seconds * (max_attempts - 1)``: each of the
    ``max_attempts - 1`` inter-attempt waits is exponential-with-jitter backoff
    — or a server ``Retry-After`` — clamped to ``backoff_cap_seconds``.
    """

    timeout_seconds: float
    max_attempts: int
    backoff_base_seconds: float = 0.5
    backoff_cap_seconds: float = 8.0


def classify_openai_error(exc: Exception) -> OutcomeClass:
    """Split an OpenAI provider failure into retryable vs non-retryable (R-9).

    Retryable: request timeouts, connection errors, 5xx, and rate limits (429).
    Everything else — auth failures, bad requests, other 4xx, and any
    unrecognized exception — is non-retryable: fail fast rather than retry blind.
    """
    import openai

    if isinstance(exc, TimeoutError):
        return OutcomeClass.RETRYABLE_FAILURE
    retryable = (
        openai.APITimeoutError
        | openai.APIConnectionError
        | openai.InternalServerError
        | openai.RateLimitError
    )
    if isinstance(exc, retryable):
        return OutcomeClass.RETRYABLE_FAILURE
    return OutcomeClass.NON_RETRYABLE_FAILURE


def extract_retry_after_seconds(exc: Exception) -> float | None:
    """Read a server ``Retry-After`` delay (in seconds) from a rate-limit error.

    Only ``openai.RateLimitError`` (429) carries this signal; any other
    exception returns ``None``. ``retry-after-ms`` (milliseconds) is preferred
    over ``retry-after`` (seconds) when both are present. Only the numeric form
    is parsed — an HTTP-date ``Retry-After`` or a malformed/negative value is
    treated as absent, so the call falls back to computed backoff (D-049).
    """
    import openai

    if not isinstance(exc, openai.RateLimitError):
        return None
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers is None:
        return None

    raw_ms = headers.get("retry-after-ms")
    if raw_ms is not None:
        try:
            value = float(raw_ms) / 1000.0
        except ValueError:
            return None
        return value if value >= 0 else None

    raw_seconds = headers.get("retry-after")
    if raw_seconds is not None:
        try:
            value = float(raw_seconds)
        except ValueError:
            return None
        return value if value >= 0 else None

    return None


def compute_backoff(
    attempt: int,
    policy: RetryPolicy,
    *,
    rng: Callable[[], float] = random.random,
) -> float:
    """Exponential-with-full-jitter backoff for the wait after ``attempt``.

    The exponential term is ``backoff_base_seconds * 2 ** (attempt - 1)`` for the
    1-based failed-attempt number, clamped to ``backoff_cap_seconds``. Full
    jitter then scales it by a uniform draw in ``[0, 1)`` — the AWS
    "full jitter" strategy. ``rng`` is injectable purely so tests can assert
    exact values; production uses ``random.random``.
    """
    exponential = policy.backoff_base_seconds * (2.0 ** (attempt - 1))
    capped = min(exponential, policy.backoff_cap_seconds)
    return rng() * capped


def _resolve_delay(
    exc: Exception,
    attempt: int,
    policy: RetryPolicy,
    retry_after: Callable[[Exception], float | None] | None,
) -> tuple[float, str]:
    """Pick the inter-attempt wait: a clamped ``Retry-After`` or computed backoff."""
    if retry_after is not None:
        server_delay = retry_after(exc)
        if server_delay is not None:
            return min(server_delay, policy.backoff_cap_seconds), "retry_after"
    return compute_backoff(attempt, policy), "computed"


def run_with_retries(
    operation: Callable[[], _T],
    *,
    policy: RetryPolicy,
    classify: Callable[[Exception], OutcomeClass],
    label: str,
    logger: Logger,
    retry_after: Callable[[Exception], float | None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> _T:
    """Run ``operation`` under the bounded retry policy (R-9).

    Each attempt is logged with its number, outcome class, and latency. A
    non-retryable failure is re-raised immediately. A retryable failure that is
    not the final attempt is followed by an inter-attempt wait — exponential
    backoff with jitter, or a clamped server ``Retry-After`` (see
    :func:`_resolve_delay`) — whose ``delay_ms`` and ``delay_source`` are logged
    on that attempt's line. After ``policy.max_attempts`` retryable failures a
    distinct ``provider.exhausted`` line is logged — the R-6 effective-vs-
    requested signal — and the original exception is re-raised. The original
    exception is always preserved; this primitive never wraps it.

    ``retry_after`` extracts a server-supplied delay from a failure; ``None``
    keeps the loop purely computed-backoff. ``sleep`` is the injected backoff
    clock seam so tests do not block on real time.
    """
    last_error: Exception | None = None
    for attempt in range(1, policy.max_attempts + 1):
        start = time.perf_counter()
        try:
            result = operation()
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            outcome = classify(exc)
            if outcome is OutcomeClass.NON_RETRYABLE_FAILURE:
                logger.warning(
                    "provider.attempt label=%s attempt=%d/%d outcome=%s "
                    "latency_ms=%d error_class=%s",
                    label,
                    attempt,
                    policy.max_attempts,
                    outcome.value,
                    latency_ms,
                    exc.__class__.__name__,
                )
                raise
            last_error = exc
            if attempt == policy.max_attempts:
                # Final retryable failure: no wait follows, so no delay fields.
                # The provider.exhausted line below carries the R-6 signal.
                logger.warning(
                    "provider.attempt label=%s attempt=%d/%d outcome=%s "
                    "latency_ms=%d error_class=%s",
                    label,
                    attempt,
                    policy.max_attempts,
                    outcome.value,
                    latency_ms,
                    exc.__class__.__name__,
                )
                continue
            delay, delay_source = _resolve_delay(exc, attempt, policy, retry_after)
            logger.warning(
                "provider.attempt label=%s attempt=%d/%d outcome=%s "
                "latency_ms=%d error_class=%s delay_ms=%d delay_source=%s",
                label,
                attempt,
                policy.max_attempts,
                outcome.value,
                latency_ms,
                exc.__class__.__name__,
                int(delay * 1000),
                delay_source,
            )
            sleep(delay)
            continue
        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "provider.attempt label=%s attempt=%d/%d outcome=%s latency_ms=%d",
            label,
            attempt,
            policy.max_attempts,
            OutcomeClass.SUCCESS.value,
            latency_ms,
        )
        return result

    # Every attempt raised a retryable failure: the bounded loop is exhausted.
    assert last_error is not None  # max_attempts >= 1 guarantees a binding
    logger.warning(
        "provider.exhausted label=%s attempts=%d error_class=%s",
        label,
        policy.max_attempts,
        last_error.__class__.__name__,
    )
    raise last_error
