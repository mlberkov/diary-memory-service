"""Offline tests for the adapter-side retry/timeout primitive (Slice 6.1 / D-047).

Covers the bounded-retry loop mechanics with a trivial classifier and scripted
operations, plus the OpenAI-specific error classification. No live API call.
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


def _run(op: _ScriptedOperation, *, max_attempts: int) -> object:
    return run_with_retries(
        op,
        policy=RetryPolicy(timeout_seconds=5.0, max_attempts=max_attempts),
        classify=_classify,
        label="test",
        logger=_LOG,
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
