"""Offline retry/wiring tests for TavilyKnowledgeSource (RC-4, D-108).

An injected ``httpx`` client with a ``MockTransport`` exercises the
bounded-retry loop, the request shape (key only in the auth header),
the result mapping (ref = result url), the ``max_results`` cap, and
the unusable-output split with no live Tavily call — mirroring
test_openai_query_rewriter_retry.py for the knowledge seam.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from memory_rag.adapters.knowledge.tavily import TavilyKnowledgeSource
from memory_rag.adapters.resilience import RetryPolicy
from memory_rag.core.chat import (
    KnowledgeSourceOutputError,
    KnowledgeSourceUnavailableError,
)

_OK_BODY: dict[str, Any] = {
    "query": "q",
    "results": [
        {"url": "https://example.org/a", "title": "A", "content": "alpha", "score": 0.9},
        {"url": "https://example.org/b", "title": "B", "content": "beta", "score": 0.5},
    ],
}


class _ScriptedTransport(httpx.BaseTransport):
    """Replays a fixed script of responses/exceptions and captures requests."""

    def __init__(self, script: list[object]) -> None:
        self.script = script
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        assert isinstance(step, httpx.Response)
        return step


def _source(
    script: list[object], *, max_attempts: int = 3, max_results: int = 5
) -> tuple[TavilyKnowledgeSource, _ScriptedTransport]:
    transport = _ScriptedTransport(script)
    client = httpx.Client(
        transport=transport,
        headers={"Authorization": "Bearer test-tavily-key"},
    )
    source = TavilyKnowledgeSource(
        "test-tavily-key",
        # Zero backoff keeps these wiring tests instant; inter-attempt
        # backoff itself is covered offline in test_provider_resilience.py.
        retry_policy=RetryPolicy(
            timeout_seconds=5.0,
            max_attempts=max_attempts,
            backoff_base_seconds=0.0,
            backoff_cap_seconds=0.0,
        ),
        max_results=max_results,
        _client=client,
    )
    return source, transport


def _ok_response(body: dict[str, Any] | str | None = None) -> httpx.Response:
    if isinstance(body, str):
        return httpx.Response(200, text=body)
    return httpx.Response(200, json=body if body is not None else _OK_BODY)


def test_provider_name_is_tavily() -> None:
    source, _ = _source([_ok_response()])
    assert source.provider_name == "tavily"


def test_search_maps_results_onto_excerpts_with_url_refs() -> None:
    source, _ = _source([_ok_response()])
    result = source.search("toddler speech games")
    assert [e.ref for e in result.excerpts] == [
        "https://example.org/a",
        "https://example.org/b",
    ]
    assert result.excerpts[0].title == "A"
    assert result.excerpts[0].text == "alpha"
    # raw_output preserves the provider body verbatim (trace provenance).
    assert json.loads(result.raw_output) == _OK_BODY
    assert result.latency_ms >= 0


def test_request_carries_the_key_only_in_the_auth_header() -> None:
    source, transport = _source([_ok_response()])
    source.search("my question")
    (request,) = transport.requests
    assert request.headers["authorization"] == "Bearer test-tavily-key"
    body = json.loads(request.content)
    assert body == {"query": "my question", "max_results": 5}
    assert "test-tavily-key" not in request.content.decode()


def test_max_results_caps_the_excerpt_list() -> None:
    source, _ = _source([_ok_response()], max_results=1)
    result = source.search("q")
    assert len(result.excerpts) == 1
    assert result.excerpts[0].ref == "https://example.org/a"


def test_empty_results_list_is_a_valid_outcome() -> None:
    source, _ = _source([_ok_response({"query": "q", "results": []})])
    result = source.search("q")
    assert result.excerpts == ()
    assert result.raw_output != ""


def test_retries_a_transient_failure_then_succeeds() -> None:
    source, transport = _source(
        [httpx.ConnectError("boom"), _ok_response()],
    )
    result = source.search("q")
    assert len(result.excerpts) == 2
    assert len(transport.requests) == 2


def test_5xx_is_retried() -> None:
    source, transport = _source([httpx.Response(503), _ok_response()])
    result = source.search("q")
    assert len(result.excerpts) == 2
    assert len(transport.requests) == 2


def test_429_is_retried_honoring_a_numeric_retry_after() -> None:
    source, transport = _source([httpx.Response(429, headers={"retry-after": "0"}), _ok_response()])
    result = source.search("q")
    assert len(result.excerpts) == 2
    assert len(transport.requests) == 2


def test_raises_unavailable_after_bounded_retries() -> None:
    source, transport = _source(
        [httpx.Response(503), httpx.Response(503), httpx.Response(503)],
        max_attempts=3,
    )
    with pytest.raises(KnowledgeSourceUnavailableError) as excinfo:
        source.search("q")
    assert "max 3 attempts" in str(excinfo.value)
    assert len(transport.requests) == 3


def test_other_4xx_fails_fast_without_retry() -> None:
    source, transport = _source([httpx.Response(401), _ok_response()])
    with pytest.raises(KnowledgeSourceUnavailableError):
        source.search("q")
    assert len(transport.requests) == 1


def test_non_json_body_raises_output_error_with_raw_body() -> None:
    source, _ = _source([_ok_response("<html>not json</html>")])
    with pytest.raises(KnowledgeSourceOutputError) as excinfo:
        source.search("q")
    assert excinfo.value.raw_output == "<html>not json</html>"


def test_missing_results_list_raises_output_error() -> None:
    source, _ = _source([_ok_response({"query": "q"})])
    with pytest.raises(KnowledgeSourceOutputError, match="results"):
        source.search("q")


def test_result_entry_without_a_url_raises_output_error() -> None:
    source, _ = _source(
        [_ok_response({"results": [{"title": "A", "content": "alpha"}]})],
    )
    with pytest.raises(KnowledgeSourceOutputError, match="url"):
        source.search("q")


def test_empty_api_key_or_bad_max_results_is_refused() -> None:
    policy = RetryPolicy(timeout_seconds=5.0, max_attempts=1)
    with pytest.raises(ValueError):
        TavilyKnowledgeSource("", retry_policy=policy, max_results=5)
    with pytest.raises(ValueError):
        TavilyKnowledgeSource("key", retry_policy=policy, max_results=0)
