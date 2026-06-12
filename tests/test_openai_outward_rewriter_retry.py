"""Offline retry/wiring tests for OpenAIOutwardRewriter (RC-4, D-108).

An injected fake SDK client exercises the bounded-retry loop, the
function-calling request shape, the notes-context conditioning in the
user message, and the unusable-output split with no live OpenAI call —
mirroring test_openai_query_rewriter_retry.py for the outward seam.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
import openai
import pytest

from memory_rag.adapters.chat_routing.outward_openai import OpenAIOutwardRewriter
from memory_rag.adapters.resilience import RetryPolicy
from memory_rag.core.chat import OutwardRewriteOutputError, OutwardRewriterUnavailableError

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


def _ok_response(search_query: str = "speech games for a 2 year old") -> _FakeChatResponse:
    return _tool_response(json.dumps({"search_query": search_query}))


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


def _rewriter(completions: _ScriptedCompletions, *, max_attempts: int = 3) -> OpenAIOutwardRewriter:
    # Zero backoff keeps these wiring tests instant; inter-attempt backoff
    # itself is covered offline in test_provider_resilience.py.
    return OpenAIOutwardRewriter(
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
    _rewriter(completions).rewrite_outward("what games suit him", notes_context=())
    kwargs = completions.captured_kwargs[0]
    assert kwargs["model"] == "gpt-4.1-mini"
    assert kwargs["temperature"] == 0
    assert kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "rewrite_outward_query"},
    }
    (tool,) = kwargs["tools"]
    parameters = tool["function"]["parameters"]
    assert parameters["required"] == ["search_query"]
    assert set(parameters["properties"]) == {"search_query"}


def test_notes_context_is_rendered_into_the_user_message() -> None:
    completions = _ScriptedCompletions([_ok_response()])
    _rewriter(completions).rewrite_outward(
        "what games suit him", notes_context=("He is 2 years old", "He likes books")
    )
    user_message = completions.captured_kwargs[0]["messages"][1]
    assert user_message["role"] == "user"
    assert "Question: what games suit him" in user_message["content"]
    assert "- He is 2 years old" in user_message["content"]
    assert "- He likes books" in user_message["content"]


def test_empty_notes_context_renders_the_none_marker() -> None:
    completions = _ScriptedCompletions([_ok_response()])
    _rewriter(completions).rewrite_outward("q", notes_context=())
    user_message = completions.captured_kwargs[0]["messages"][1]
    assert "(none)" in user_message["content"]


def test_rewrite_returns_query_and_raw_output() -> None:
    completions = _ScriptedCompletions([_ok_response()])
    outward = _rewriter(completions).rewrite_outward("q", notes_context=())
    assert outward.search_query == "speech games for a 2 year old"
    assert json.loads(outward.raw_output)["search_query"] == "speech games for a 2 year old"
    assert outward.model_name == "gpt-4.1-mini"
    assert outward.latency_ms >= 0


def test_rewrite_retries_a_transient_failure_then_succeeds() -> None:
    completions = _ScriptedCompletions([openai.APITimeoutError(request=_REQUEST), _ok_response()])
    outward = _rewriter(completions).rewrite_outward("q", notes_context=())
    assert outward.search_query == "speech games for a 2 year old"
    assert completions.calls == 2


def test_rewrite_raises_unavailable_after_bounded_retries() -> None:
    completions = _ScriptedCompletions(
        [
            openai.APITimeoutError(request=_REQUEST),
            openai.APITimeoutError(request=_REQUEST),
            openai.APITimeoutError(request=_REQUEST),
        ]
    )
    with pytest.raises(OutwardRewriterUnavailableError) as excinfo:
        _rewriter(completions, max_attempts=3).rewrite_outward("q", notes_context=())
    assert "max 3 attempts" in str(excinfo.value)
    assert completions.calls == 3


def test_missing_tool_call_raises_output_error_with_content() -> None:
    completions = _ScriptedCompletions(
        [_FakeChatResponse(choices=[_FakeChoice(_FakeMessage(content="prose instead"))])]
    )
    with pytest.raises(OutwardRewriteOutputError) as excinfo:
        _rewriter(completions).rewrite_outward("q", notes_context=())
    assert excinfo.value.raw_output == "prose instead"


def test_malformed_arguments_raise_output_error_with_raw_output() -> None:
    completions = _ScriptedCompletions([_tool_response("{not json")])
    with pytest.raises(OutwardRewriteOutputError) as excinfo:
        _rewriter(completions).rewrite_outward("q", notes_context=())
    assert excinfo.value.raw_output == "{not json"


def test_empty_search_query_raises_output_error() -> None:
    completions = _ScriptedCompletions([_tool_response(json.dumps({"search_query": "   "}))])
    with pytest.raises(OutwardRewriteOutputError, match="search_query"):
        _rewriter(completions).rewrite_outward("q", notes_context=())


def test_empty_api_key_or_model_is_refused() -> None:
    policy = RetryPolicy(timeout_seconds=5.0, max_attempts=1)
    with pytest.raises(ValueError):
        OpenAIOutwardRewriter("", model_name="gpt-4.1-mini", retry_policy=policy)
    with pytest.raises(ValueError):
        OpenAIOutwardRewriter("key", model_name="", retry_policy=policy)
