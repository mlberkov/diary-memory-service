"""Offline tests for the adapter-side retry/timeout primitive (R-9).

Covers the bounded-retry loop mechanics with a trivial classifier and scripted
operations, the OpenAI-specific error classification, and the rate-limit
backoff (exponential delay, jitter, ``Retry-After`` honoring — D-049). The
inter-attempt wait runs through an injected ``sleep`` seam, so no test blocks
on real time. No live API call.
"""

from __future__ import annotations

import logging

import httpx
import openai
import pytest

from memory_rag.adapters.resilience import (
    OutcomeClass,
    RetryPolicy,
    classify_openai_error,
    compute_backoff,
    extract_retry_after_seconds,
    run_with_retries,
)

_LOG = logging.getLogger("test.resilience")
_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/test")


class _Retryable(Exception):
    """Stand-in for a transient provider failure."""


class _NonRetryable(Exception):
    """Stand-in for a permanent provider failure."""


def _classify(exc: Exception) -> OutcomeClass:
    if isinstance(exc, _Retryable):
        return OutcomeClass.RETRYABLE_FAILURE
    return OutcomeClass.NON_RETRYABLE_FAILURE


class _ScriptedOperation:
    """A zero-arg callable that replays a fixed script of outcomes."""

    def __init__(self, *outcomes: object) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def __call__(self) -> object:
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _RecordingSleep:
    """A ``sleep`` stand-in that records its delays instead of blocking."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def _run(
    op: _ScriptedOperation,
    *,
    max_attempts: int,
    policy: RetryPolicy | None = None,
    sleep: _RecordingSleep | None = None,
    retry_after: object = None,
) -> object:
    return run_with_retries(
        op,
        policy=policy or RetryPolicy(timeout_seconds=5.0, max_attempts=max_attempts),
        classify=_classify,
        label="test",
        logger=_LOG,
        retry_after=retry_after,  # type: ignore[arg-type]
        sleep=sleep or _RecordingSleep(),
    )


def test_retry_then_succeed_returns_result_after_bounded_attempts() -> None:
    op = _ScriptedOperation(_Retryable(), _Retryable(), "ok")
    assert _run(op, max_attempts=3) == "ok"
    assert op.calls == 3


def test_retry_then_exhaust_reraises_original_after_max_attempts() -> None:
    boom = _Retryable("still failing")
    op = _ScriptedOperation(_Retryable(), _Retryable(), boom)
    with pytest.raises(_Retryable) as excinfo:
        _run(op, max_attempts=3)
    assert excinfo.value is boom
    assert op.calls == 3


def test_non_retryable_fails_fast_without_a_second_attempt() -> None:
    op = _ScriptedOperation(_NonRetryable("bad request"), "unreached")
    with pytest.raises(_NonRetryable):
        _run(op, max_attempts=3)
    assert op.calls == 1


def test_max_attempts_one_makes_a_single_call() -> None:
    op = _ScriptedOperation(_Retryable())
    with pytest.raises(_Retryable):
        _run(op, max_attempts=1)
    assert op.calls == 1


def test_first_attempt_success_makes_one_call() -> None:
    op = _ScriptedOperation("done")
    assert _run(op, max_attempts=3) == "done"
    assert op.calls == 1


def _http_response(status: int) -> httpx.Response:
    return httpx.Response(status_code=status, request=_REQUEST)


@pytest.mark.parametrize(
    "exc",
    [
        TimeoutError("timed out"),
        openai.APITimeoutError(request=_REQUEST),
        openai.APIConnectionError(request=_REQUEST),
        openai.InternalServerError("server", response=_http_response(500), body=None),
        openai.RateLimitError("rate limited", response=_http_response(429), body=None),
    ],
)
def test_classify_marks_transient_failures_retryable(exc: Exception) -> None:
    assert classify_openai_error(exc) is OutcomeClass.RETRYABLE_FAILURE


@pytest.mark.parametrize(
    "exc",
    [
        openai.AuthenticationError("bad key", response=_http_response(401), body=None),
        openai.BadRequestError("bad request", response=_http_response(400), body=None),
        ValueError("not a provider error"),
    ],
)
def test_classify_marks_permanent_failures_non_retryable(exc: Exception) -> None:
    assert classify_openai_error(exc) is OutcomeClass.NON_RETRYABLE_FAILURE


# --- compute_backoff: exponential delay, jitter, cap (D-049) ----------------


def test_compute_backoff_grows_exponentially_per_attempt() -> None:
    policy = RetryPolicy(
        timeout_seconds=5.0,
        max_attempts=5,
        backoff_base_seconds=1.0,
        backoff_cap_seconds=100.0,
    )
    # rng=1.0 removes jitter, exposing the raw exponential term.
    assert compute_backoff(1, policy, rng=lambda: 1.0) == 1.0
    assert compute_backoff(2, policy, rng=lambda: 1.0) == 2.0
    assert compute_backoff(3, policy, rng=lambda: 1.0) == 4.0


def test_compute_backoff_is_clamped_to_the_cap() -> None:
    policy = RetryPolicy(
        timeout_seconds=5.0,
        max_attempts=10,
        backoff_base_seconds=1.0,
        backoff_cap_seconds=3.0,
    )
    assert compute_backoff(8, policy, rng=lambda: 1.0) == 3.0


def test_compute_backoff_full_jitter_scales_within_bounds() -> None:
    policy = RetryPolicy(
        timeout_seconds=5.0,
        max_attempts=5,
        backoff_base_seconds=2.0,
        backoff_cap_seconds=100.0,
    )
    # attempt 2 -> exponential term 4.0; full jitter scales it by rng() in [0, 1).
    assert compute_backoff(2, policy, rng=lambda: 0.0) == 0.0
    assert compute_backoff(2, policy, rng=lambda: 0.5) == 2.0


# --- run_with_retries: inter-attempt backoff (D-049) ------------------------


def test_backoff_sleeps_between_retries_but_not_after_the_final_attempt() -> None:
    sleep = _RecordingSleep()
    op = _ScriptedOperation(_Retryable(), _Retryable(), _Retryable())
    with pytest.raises(_Retryable):
        _run(op, max_attempts=3, sleep=sleep)
    # 3 attempts -> exactly 2 inter-attempt waits; none after the final failure.
    assert len(sleep.delays) == 2


def test_backoff_stops_once_an_attempt_succeeds() -> None:
    sleep = _RecordingSleep()
    op = _ScriptedOperation(_Retryable(), "ok")
    assert _run(op, max_attempts=3, sleep=sleep) == "ok"
    assert len(sleep.delays) == 1


def test_non_retryable_failure_never_sleeps() -> None:
    sleep = _RecordingSleep()
    op = _ScriptedOperation(_NonRetryable("bad request"))
    with pytest.raises(_NonRetryable):
        _run(op, max_attempts=3, sleep=sleep)
    assert sleep.delays == []


def test_retryable_attempt_logs_delay_fields(caplog: pytest.LogCaptureFixture) -> None:
    sleep = _RecordingSleep()
    op = _ScriptedOperation(_Retryable(), "ok")
    with caplog.at_level(logging.WARNING, logger="test.resilience"):
        _run(op, max_attempts=3, sleep=sleep)
    line = next(
        r.getMessage() for r in caplog.records if "outcome=retryable_failure" in r.getMessage()
    )
    assert "delay_ms=" in line
    assert "delay_source=computed" in line


def test_final_retryable_attempt_omits_delay_fields(caplog: pytest.LogCaptureFixture) -> None:
    sleep = _RecordingSleep()
    op = _ScriptedOperation(_Retryable(), _Retryable())
    with (
        caplog.at_level(logging.WARNING, logger="test.resilience"),
        pytest.raises(_Retryable),
    ):
        _run(op, max_attempts=2, sleep=sleep)
    attempt_lines = [r.getMessage() for r in caplog.records if "provider.attempt" in r.getMessage()]
    # attempt 1 (a wait follows) carries delay fields; attempt 2 (final) does not.
    assert any("delay_ms=" in m for m in attempt_lines)
    assert any("delay_ms=" not in m for m in attempt_lines)
    # provider.exhausted is unchanged — no delay fields added there.
    assert any("provider.exhausted" in r.getMessage() for r in caplog.records)


# --- Retry-After honoring, clamped to the cap (D-049) -----------------------


def test_retry_after_takes_precedence_over_computed_backoff() -> None:
    sleep = _RecordingSleep()
    op = _ScriptedOperation(_Retryable(), "ok")
    policy = RetryPolicy(
        timeout_seconds=5.0,
        max_attempts=3,
        backoff_base_seconds=0.5,
        backoff_cap_seconds=30.0,
    )
    _run(op, max_attempts=3, policy=policy, sleep=sleep, retry_after=lambda exc: 4.0)
    assert sleep.delays == [4.0]


def test_retry_after_is_clamped_to_the_backoff_cap() -> None:
    sleep = _RecordingSleep()
    op = _ScriptedOperation(_Retryable(), "ok")
    policy = RetryPolicy(
        timeout_seconds=5.0,
        max_attempts=3,
        backoff_base_seconds=0.5,
        backoff_cap_seconds=8.0,
    )
    _run(op, max_attempts=3, policy=policy, sleep=sleep, retry_after=lambda exc: 600.0)
    assert sleep.delays == [8.0]


def test_retry_after_attempt_logs_retry_after_as_the_delay_source(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sleep = _RecordingSleep()
    op = _ScriptedOperation(_Retryable(), "ok")
    with caplog.at_level(logging.WARNING, logger="test.resilience"):
        _run(op, max_attempts=3, sleep=sleep, retry_after=lambda exc: 2.0)
    line = next(
        r.getMessage() for r in caplog.records if "outcome=retryable_failure" in r.getMessage()
    )
    assert "delay_source=retry_after" in line


# --- extract_retry_after_seconds (D-049) ------------------------------------


def _rate_limit_error(headers: dict[str, str]) -> openai.RateLimitError:
    return openai.RateLimitError(
        "rate limited",
        response=httpx.Response(status_code=429, request=_REQUEST, headers=headers),
        body=None,
    )


def test_extract_retry_after_reads_the_seconds_header() -> None:
    assert extract_retry_after_seconds(_rate_limit_error({"retry-after": "7"})) == 7.0


def test_extract_retry_after_prefers_the_millisecond_header() -> None:
    err = _rate_limit_error({"retry-after-ms": "1500", "retry-after": "9"})
    assert extract_retry_after_seconds(err) == 1.5


def test_extract_retry_after_absent_header_returns_none() -> None:
    assert extract_retry_after_seconds(_rate_limit_error({})) is None


def test_extract_retry_after_non_numeric_value_returns_none() -> None:
    # An HTTP-date Retry-After is not parsed this slice; it is treated as absent.
    err = _rate_limit_error({"retry-after": "Wed, 21 Oct 2025 07:28:00 GMT"})
    assert extract_retry_after_seconds(err) is None


def test_extract_retry_after_negative_value_returns_none() -> None:
    assert extract_retry_after_seconds(_rate_limit_error({"retry-after": "-5"})) is None


def test_extract_retry_after_ignores_non_rate_limit_errors() -> None:
    assert extract_retry_after_seconds(openai.APITimeoutError(request=_REQUEST)) is None
    assert extract_retry_after_seconds(TimeoutError("timed out")) is None
