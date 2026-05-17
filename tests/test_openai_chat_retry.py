"""Offline retry/timeout wiring tests for OpenAIChatClient (Slice 6.1 / D-047).

An injected fake SDK client exercises the bounded-retry loop with no live
OpenAI call. The live smoke test lives in test_chat_client_openai.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import openai
import pytest

from memory_rag.adapters.answers.openai_client import OpenAIChatClient
from memory_rag.adapters.resilience import RetryPolicy
from memory_rag.core.answers.client import ChatProviderUnavailableError
from memory_rag.core.domain.answer_prompt import AnswerPrompt

_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")

_PROMPT = AnswerPrompt(
    prompt_version="v1",
    system_text="system",
    user_text="user",
    cited_chunk_ids=(),
)


@dataclass
class _FakeMessage:
    content: str | None


@dataclass
class _FakeChoice:
    message: _FakeMessage


@dataclass
class _FakeUsage:
    prompt_tokens: int
    completion_tokens: int


@dataclass
class _FakeChatResponse:
    choices: list[_FakeChoice]
    usage: _FakeUsage | None


def _ok_response() -> _FakeChatResponse:
    return _FakeChatResponse(
        choices=[_FakeChoice(_FakeMessage('{"answer": "hi"}'))],
        usage=_FakeUsage(prompt_tokens=11, completion_tokens=7),
    )


class _ScriptedCompletions:
    """Fake ``client.chat.completions`` namespace replaying a fixed script."""

    def __init__(self, *script: object) -> None:
        self._script = list(script)
        self.calls = 0

    def create(self, **_kwargs: Any) -> _FakeChatResponse:
        self.calls += 1
        step = self._script.pop(0)
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


def _client(completions: _ScriptedCompletions, *, max_attempts: int = 3) -> OpenAIChatClient:
    # Zero backoff keeps these wiring tests instant; inter-attempt backoff
    # itself is covered offline in test_provider_resilience.py.
    return OpenAIChatClient(
        api_key="test-key",
        model_name="gpt-4.1",
        retry_policy=RetryPolicy(
            timeout_seconds=5.0,
            max_attempts=max_attempts,
            backoff_base_seconds=0.0,
            backoff_cap_seconds=0.0,
        ),
        _client=_FakeOpenAI(completions),
    )


def test_complete_retries_a_transient_failure_then_succeeds() -> None:
    completions = _ScriptedCompletions(
        openai.APITimeoutError(request=_REQUEST),
        _ok_response(),
    )
    response = _client(completions).complete(_PROMPT)
    assert response.raw_text == '{"answer": "hi"}'
    assert response.model_name == "gpt-4.1"
    assert response.token_counts == {"prompt": 11, "completion": 7}
    assert response.latency_ms >= 0
    assert completions.calls == 2


def test_complete_raises_provider_unavailable_after_bounded_retries() -> None:
    completions = _ScriptedCompletions(
        openai.APITimeoutError(request=_REQUEST),
        openai.APITimeoutError(request=_REQUEST),
        openai.APITimeoutError(request=_REQUEST),
    )
    with pytest.raises(ChatProviderUnavailableError) as excinfo:
        _client(completions, max_attempts=3).complete(_PROMPT)
    assert "max 3 attempts" in str(excinfo.value)
    assert completions.calls == 3


def test_complete_fails_fast_on_a_non_retryable_error() -> None:
    completions = _ScriptedCompletions(
        openai.AuthenticationError(
            "bad key",
            response=httpx.Response(status_code=401, request=_REQUEST),
            body=None,
        ),
    )
    with pytest.raises(ChatProviderUnavailableError):
        _client(completions, max_attempts=3).complete(_PROMPT)
    assert completions.calls == 1
