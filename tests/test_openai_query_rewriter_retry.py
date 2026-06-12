"""Offline retry/wiring tests for OpenAIQueryRewriter (RC-3, D-108).

An injected fake SDK client exercises the bounded-retry loop, the
function-calling request shape (including the deliberate absence of any
subject parameter — see ``docs/assumptions.md``), the today-anchored
system text, and the unusable-output split with no live OpenAI call —
mirroring test_openai_route_classifier_retry.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx
import openai
import pytest

from memory_rag.adapters.chat_routing.rewrite_openai import OpenAIQueryRewriter
from memory_rag.adapters.resilience import RetryPolicy
from memory_rag.core.chat import QueryRewriteOutputError, QueryRewriterUnavailableError
from memory_rag.core.domain import DateRange

_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
_TODAY = date(2026, 6, 12)


@dataclass
class _FakeFunction:
    arguments: str


@dataclass
class _FakeToolCall:
    function: _FakeFunction


@dataclass
class _FakeMessage:
    content: str | None = None
    tool_calls: list[_FakeToolCall] | None = None


@dataclass
class _FakeChoice:
    message: _FakeMessage


@dataclass
class _FakeChatResponse:
    choices: list[_FakeChoice]


def _tool_response(arguments: str) -> _FakeChatResponse:
    return _FakeChatResponse(
        choices=[_FakeChoice(_FakeMessage(tool_calls=[_FakeToolCall(_FakeFunction(arguments))]))]
    )


def _ok_response(**payload: str) -> _FakeChatResponse:
    payload.setdefault("retrieval_query", "games for toddler")
    return _tool_response(json.dumps(payload))


@dataclass
class _ScriptedCompletions:
    """Fake ``client.chat.completions`` namespace replaying a fixed script."""

    script: list[object]
    calls: int = 0
    captured_kwargs: list[dict[str, Any]] = field(default_factory=list)

    def create(self, **kwargs: Any) -> _FakeChatResponse:
        self.calls += 1
        self.captured_kwargs.append(kwargs)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        assert isinstance(step, _FakeChatResponse)
        return step


class _FakeChat:
    def __init__(self, completions: _ScriptedCompletions) -> None:
        self.completions = completions


class _FakeOpenAI:
    def __init__(self, completions: _ScriptedCompletions) -> None:
        self.chat = _FakeChat(completions)


def _rewriter(completions: _ScriptedCompletions, *, max_attempts: int = 3) -> OpenAIQueryRewriter:
    # Zero backoff keeps these wiring tests instant; inter-attempt backoff
    # itself is covered offline in test_provider_resilience.py.
    return OpenAIQueryRewriter(
        api_key="test-key",
        model_name="gpt-4.1-mini",
        retry_policy=RetryPolicy(
            timeout_seconds=5.0,
            max_attempts=max_attempts,
            backoff_base_seconds=0.0,
            backoff_cap_seconds=0.0,
        ),
        _client=_FakeOpenAI(completions),
    )


def test_rewrite_sends_the_forced_function_calling_shape() -> None:
    completions = _ScriptedCompletions([_ok_response()])
    _rewriter(completions).rewrite("what games suit him now", today=_TODAY)
    kwargs = completions.captured_kwargs[0]
    assert kwargs["model"] == "gpt-4.1-mini"
    assert kwargs["temperature"] == 0
    assert kwargs["tool_choice"] == {"type": "function", "function": {"name": "rewrite_query"}}
    (tool,) = kwargs["tools"]
    parameters = tool["function"]["parameters"]
    assert parameters["required"] == ["retrieval_query"]
    # Deliberately no subject parameter: subject ids are opaque and no
    # subject-name vocabulary exists (docs/assumptions.md).
    assert set(parameters["properties"]) == {"retrieval_query", "date_from", "date_to"}


def test_system_text_embeds_today_for_relative_dates() -> None:
    completions = _ScriptedCompletions([_ok_response()])
    _rewriter(completions).rewrite("what did we do last month", today=_TODAY)
    system_message = completions.captured_kwargs[0]["messages"][0]
    assert system_message["role"] == "system"
    assert "2026-06-12" in system_message["content"]


def test_rewrite_returns_query_dates_and_raw_output() -> None:
    completions = _ScriptedCompletions([_ok_response(date_from="2026-05-01", date_to="2026-05-31")])
    rewrite = _rewriter(completions).rewrite("games last month?", today=_TODAY)
    assert rewrite.retrieval_query == "games for toddler"
    assert rewrite.date_range == DateRange(start=date(2026, 5, 1), end=date(2026, 5, 31))
    assert rewrite.subject_scope is None
    assert json.loads(rewrite.raw_output)["retrieval_query"] == "games for toddler"
    assert rewrite.model_name == "gpt-4.1-mini"
    assert rewrite.latency_ms >= 0


def test_rewrite_without_dates_has_no_range() -> None:
    completions = _ScriptedCompletions([_ok_response()])
    rewrite = _rewriter(completions).rewrite("what games suit him", today=_TODAY)
    assert rewrite.date_range is None


def test_rewrite_retries_a_transient_failure_then_succeeds() -> None:
    completions = _ScriptedCompletions([openai.APITimeoutError(request=_REQUEST), _ok_response()])
    rewrite = _rewriter(completions).rewrite("q", today=_TODAY)
    assert rewrite.retrieval_query == "games for toddler"
    assert completions.calls == 2


def test_rewrite_raises_unavailable_after_bounded_retries() -> None:
    completions = _ScriptedCompletions(
        [
            openai.APITimeoutError(request=_REQUEST),
            openai.APITimeoutError(request=_REQUEST),
            openai.APITimeoutError(request=_REQUEST),
        ]
    )
    with pytest.raises(QueryRewriterUnavailableError) as excinfo:
        _rewriter(completions, max_attempts=3).rewrite("q", today=_TODAY)
    assert "max 3 attempts" in str(excinfo.value)
    assert completions.calls == 3


def test_missing_tool_call_raises_output_error_with_content() -> None:
    completions = _ScriptedCompletions(
        [_FakeChatResponse(choices=[_FakeChoice(_FakeMessage(content="prose instead"))])]
    )
    with pytest.raises(QueryRewriteOutputError) as excinfo:
        _rewriter(completions).rewrite("q", today=_TODAY)
    assert excinfo.value.raw_output == "prose instead"


def test_malformed_arguments_raise_output_error_with_raw_output() -> None:
    completions = _ScriptedCompletions([_tool_response("{not json")])
    with pytest.raises(QueryRewriteOutputError) as excinfo:
        _rewriter(completions).rewrite("q", today=_TODAY)
    assert excinfo.value.raw_output == "{not json"


def test_empty_retrieval_query_raises_output_error() -> None:
    completions = _ScriptedCompletions([_tool_response(json.dumps({"retrieval_query": "   "}))])
    with pytest.raises(QueryRewriteOutputError, match="retrieval_query"):
        _rewriter(completions).rewrite("q", today=_TODAY)


def test_bad_iso_date_raises_output_error_with_raw_output() -> None:
    completions = _ScriptedCompletions([_ok_response(date_from="last month")])
    with pytest.raises(QueryRewriteOutputError, match="ISO date") as excinfo:
        _rewriter(completions).rewrite("q", today=_TODAY)
    assert "last month" in excinfo.value.raw_output


def test_contradictory_date_bounds_raise_output_error() -> None:
    completions = _ScriptedCompletions([_ok_response(date_from="2026-05-31", date_to="2026-05-01")])
    with pytest.raises(QueryRewriteOutputError, match="contradictory"):
        _rewriter(completions).rewrite("q", today=_TODAY)


def test_empty_api_key_or_model_is_refused() -> None:
    policy = RetryPolicy(timeout_seconds=5.0, max_attempts=1)
    with pytest.raises(ValueError):
        OpenAIQueryRewriter("", model_name="gpt-4.1-mini", retry_policy=policy)
    with pytest.raises(ValueError):
        OpenAIQueryRewriter("key", model_name="", retry_policy=policy)
