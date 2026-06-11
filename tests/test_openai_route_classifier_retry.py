"""Offline retry/wiring tests for OpenAIRouteClassifier (RC-2, D-108).

An injected fake SDK client exercises the bounded-retry loop, the
function-calling request shape, and the unusable-output split with no
live OpenAI call — mirroring test_openai_chat_retry.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
import openai
import pytest

from memory_rag.adapters.chat_routing.openai_client import OpenAIRouteClassifier
from memory_rag.adapters.resilience import RetryPolicy
from memory_rag.core.chat import (
    ChatRoute,
    ChatRouteClassifierUnavailableError,
    ChatRouteOutputError,
)

_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


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


def _ok_response(route: str = "model_only") -> _FakeChatResponse:
    return _tool_response(json.dumps({"route": route}))


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


def _classifier(
    completions: _ScriptedCompletions, *, max_attempts: int = 3
) -> OpenAIRouteClassifier:
    # Zero backoff keeps these wiring tests instant; inter-attempt backoff
    # itself is covered offline in test_provider_resilience.py.
    return OpenAIRouteClassifier(
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


def test_classify_sends_the_forced_function_calling_shape() -> None:
    completions = _ScriptedCompletions([_ok_response()])
    _classifier(completions).classify("what is phonemic awareness")
    kwargs = completions.captured_kwargs[0]
    assert kwargs["model"] == "gpt-4.1-mini"
    assert kwargs["temperature"] == 0
    assert kwargs["tool_choice"] == {"type": "function", "function": {"name": "select_route"}}
    (tool,) = kwargs["tools"]
    enum = tool["function"]["parameters"]["properties"]["route"]["enum"]
    assert enum == [r.value for r in ChatRoute]


def test_classify_returns_the_named_route_with_raw_output() -> None:
    completions = _ScriptedCompletions([_ok_response("notes_lookup")])
    classification = _classifier(completions).classify("when did he first walk")
    assert classification.route is ChatRoute.NOTES_LOOKUP
    assert json.loads(classification.raw_output) == {"route": "notes_lookup"}
    assert classification.model_name == "gpt-4.1-mini"
    assert classification.latency_ms >= 0


def test_classify_retries_a_transient_failure_then_succeeds() -> None:
    completions = _ScriptedCompletions([openai.APITimeoutError(request=_REQUEST), _ok_response()])
    classification = _classifier(completions).classify("q")
    assert classification.route is ChatRoute.MODEL_ONLY
    assert completions.calls == 2


def test_classify_raises_unavailable_after_bounded_retries() -> None:
    completions = _ScriptedCompletions(
        [
            openai.APITimeoutError(request=_REQUEST),
            openai.APITimeoutError(request=_REQUEST),
            openai.APITimeoutError(request=_REQUEST),
        ]
    )
    with pytest.raises(ChatRouteClassifierUnavailableError) as excinfo:
        _classifier(completions, max_attempts=3).classify("q")
    assert "max 3 attempts" in str(excinfo.value)
    assert completions.calls == 3


def test_classify_fails_fast_on_a_non_retryable_error() -> None:
    completions = _ScriptedCompletions(
        [
            openai.AuthenticationError(
                "bad key",
                response=httpx.Response(status_code=401, request=_REQUEST),
                body=None,
            )
        ]
    )
    with pytest.raises(ChatRouteClassifierUnavailableError):
        _classifier(completions, max_attempts=3).classify("q")
    assert completions.calls == 1


def test_missing_tool_call_raises_output_error_with_content() -> None:
    completions = _ScriptedCompletions(
        [_FakeChatResponse(choices=[_FakeChoice(_FakeMessage(content="prose instead"))])]
    )
    with pytest.raises(ChatRouteOutputError) as excinfo:
        _classifier(completions).classify("q")
    assert excinfo.value.raw_output == "prose instead"


def test_malformed_arguments_raise_output_error_with_raw_output() -> None:
    completions = _ScriptedCompletions([_tool_response("{not json")])
    with pytest.raises(ChatRouteOutputError) as excinfo:
        _classifier(completions).classify("q")
    assert excinfo.value.raw_output == "{not json"


def test_unknown_route_value_raises_output_error_with_raw_output() -> None:
    completions = _ScriptedCompletions([_ok_response("web_only")])
    with pytest.raises(ChatRouteOutputError) as excinfo:
        _classifier(completions).classify("q")
    assert json.loads(excinfo.value.raw_output) == {"route": "web_only"}


def test_empty_api_key_or_model_is_refused() -> None:
    policy = RetryPolicy(timeout_seconds=5.0, max_attempts=1)
    with pytest.raises(ValueError):
        OpenAIRouteClassifier("", model_name="gpt-4.1-mini", retry_policy=policy)
    with pytest.raises(ValueError):
        OpenAIRouteClassifier("key", model_name="", retry_policy=policy)
