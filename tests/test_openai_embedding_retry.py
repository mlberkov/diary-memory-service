"""Offline retry/timeout wiring tests for OpenAIEmbeddingClient (Slice 6.1 / D-047).

An injected fake SDK client exercises the bounded-retry loop with no live
OpenAI call. The live smoke test lives in test_embedding_client_openai.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import openai
import pytest

from memory_rag.adapters.embeddings.openai_client import OpenAIEmbeddingClient
from memory_rag.adapters.resilience import RetryPolicy

_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/embeddings")


@dataclass
class _FakeItem:
    embedding: list[float]


@dataclass
class _FakeEmbeddingResponse:
    data: list[_FakeItem]


class _ScriptedEmbeddings:
    """Fake ``client.embeddings`` namespace replaying a fixed script."""

    def __init__(self, *script: object) -> None:
        self._script = list(script)
        self.calls = 0

    def create(self, **_kwargs: Any) -> _FakeEmbeddingResponse:
        self.calls += 1
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        assert isinstance(step, list)
        return _FakeEmbeddingResponse(data=[_FakeItem(list(v)) for v in step])


class _FakeOpenAI:
    def __init__(self, embeddings: _ScriptedEmbeddings) -> None:
        self.embeddings = embeddings


def _client(embeddings: _ScriptedEmbeddings, *, max_attempts: int = 3) -> OpenAIEmbeddingClient:
    return OpenAIEmbeddingClient(
        api_key="test-key",
        dimension=3,
        retry_policy=RetryPolicy(timeout_seconds=5.0, max_attempts=max_attempts),
        _client=_FakeOpenAI(embeddings),
    )


def test_embed_retries_a_transient_failure_then_succeeds() -> None:
    embeddings = _ScriptedEmbeddings(
        openai.APITimeoutError(request=_REQUEST),
        [[1.0, 2.0, 3.0]],
    )
    client = _client(embeddings)
    assert client.embed(["a diary line"]) == [[1.0, 2.0, 3.0]]
    assert embeddings.calls == 2


def test_embed_reraises_original_error_after_bounded_retries() -> None:
    embeddings = _ScriptedEmbeddings(
        openai.APITimeoutError(request=_REQUEST),
        openai.APITimeoutError(request=_REQUEST),
        openai.APITimeoutError(request=_REQUEST),
    )
    client = _client(embeddings, max_attempts=3)
    with pytest.raises(openai.APITimeoutError):
        client.embed(["a diary line"])
    assert embeddings.calls == 3


def test_embed_fails_fast_on_a_non_retryable_error() -> None:
    embeddings = _ScriptedEmbeddings(
        openai.AuthenticationError(
            "bad key",
            response=httpx.Response(status_code=401, request=_REQUEST),
            body=None,
        ),
    )
    client = _client(embeddings, max_attempts=3)
    with pytest.raises(openai.AuthenticationError):
        client.embed(["a diary line"])
    assert embeddings.calls == 1


def test_constructing_the_real_client_passes_timeout_and_disables_sdk_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _capture(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("openai.OpenAI", _capture)
    OpenAIEmbeddingClient(
        api_key="test-key",
        retry_policy=RetryPolicy(timeout_seconds=12.5, max_attempts=2),
    )
    assert captured["timeout"] == 12.5
    assert captured["max_retries"] == 0
