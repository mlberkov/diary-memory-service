"""Shared adapter-side timeout / bounded-retry primitive (R-9, Slice 6.1 / D-047).

Provider calls must have an explicit timeout and a bounded number of attempts —
no unbounded wait, no unbounded retry loop (R-9). This module is the single
adapter-side place that enforces that: :class:`RetryPolicy` carries the two
knobs, :func:`classify_openai_error` splits provider failures into retryable and
non-retryable, and :func:`run_with_retries` runs the bounded loop.

The loop itself is provider-agnostic — OpenAI specifics enter only through the
injected ``classify`` callable. This is adapter code, so importing the ``openai``
SDK here is allowed (Invariant I-11); core code never sees it.

Slice 6.1 does no inter-attempt waiting: a retryable failure is retried
immediately. Rate-limit-aware backoff (exponential delay, jitter, honoring
``Retry-After``) is Slice 6.3.
"""

from __future__ import annotations

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
    """The two R-9 knobs for a provider call.

    ``timeout_seconds`` is the per-attempt wall-clock budget; ``max_attempts`` is
    the total number of attempts including the first (``1`` disables retries).
    Worst-case bounded wall time for one call is ``timeout_seconds *
    max_attempts`` — there is no inter-attempt delay in Slice 6.1.
    """

    timeout_seconds: float
    max_attempts: int


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


def run_with_retries(
    operation: Callable[[], _T],
    *,
    policy: RetryPolicy,
    classify: Callable[[Exception], OutcomeClass],
    label: str,
    logger: Logger,
) -> _T:
    """Run ``operation`` under the bounded retry policy (R-9).

    Each attempt is logged with its number, outcome class, and latency. A
    non-retryable failure is re-raised immediately; a retryable failure is
    retried until ``policy.max_attempts`` is reached, after which a distinct
    ``provider.exhausted`` line is logged — the R-6 effective-vs-requested
    signal — and the original exception is re-raised. The original exception is
    always preserved; this primitive never wraps it.
    """
    last_error: Exception | None = None
    for attempt in range(1, policy.max_attempts + 1):
        start = time.perf_counter()
        try:
            result = operation()
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            outcome = classify(exc)
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
            if outcome is OutcomeClass.NON_RETRYABLE_FAILURE:
                raise
            last_error = exc
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
