"""MockKnowledgeSource behavior (RC-4, D-108).

The deterministic stand-in behind ``KNOWLEDGE_BACKEND=mock``: honest
``provider_name`` provenance, no excerpts by default (no fabricated
web-plane content in mock mode), constructor-scripted excerpts for
tests, and a deterministic ``raw_output`` mirroring the real adapter's
response-body shape.
"""

from __future__ import annotations

import json

from memory_rag.adapters.knowledge import MockKnowledgeSource
from memory_rag.core.chat import KnowledgeExcerpt


def test_default_mock_returns_no_excerpts() -> None:
    result = MockKnowledgeSource().search("toddler speech games")
    assert result.excerpts == ()
    assert result.latency_ms == 0


def test_provider_name_is_honest() -> None:
    assert MockKnowledgeSource().provider_name == "mock"


def test_scripted_excerpts_round_trip_deterministically() -> None:
    excerpts = (
        KnowledgeExcerpt(ref="https://example.org/a", title="A", text="alpha"),
        KnowledgeExcerpt(ref="https://example.org/b", title="B", text="beta"),
    )
    source = MockKnowledgeSource(excerpts=excerpts)
    first = source.search("q")
    second = source.search("q")
    assert first.excerpts == excerpts
    assert first == second


def test_raw_output_mirrors_the_provider_body_shape() -> None:
    excerpts = (KnowledgeExcerpt(ref="https://example.org/a", title="A", text="alpha"),)
    result = MockKnowledgeSource(excerpts=excerpts).search("my query")
    payload = json.loads(result.raw_output)
    assert payload["query"] == "my query"
    assert payload["results"] == [
        {"url": "https://example.org/a", "title": "A", "content": "alpha"}
    ]
