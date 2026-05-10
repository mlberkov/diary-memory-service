"""Optional live OpenAI smoke for :class:`OpenAIEmbeddingClient` (D-024).

This test is **not part of the standard packet gate**. It hits the real
OpenAI API and is skipped unless ``DIARY_RAG_OPENAI_TEST_KEY`` is set,
which matches the gating pattern used for ``test_postgres_store.py``.

When enabled it verifies that ``text-embedding-3-large`` with
``dimensions=3072`` round-trips a single short input and returns a
3072-dim list of floats.
"""

from __future__ import annotations

import os

import pytest

from diary_rag.adapters.embeddings.openai_client import OpenAIEmbeddingClient

OPENAI_TEST_KEY = os.environ.get("DIARY_RAG_OPENAI_TEST_KEY")

pytestmark = pytest.mark.skipif(
    OPENAI_TEST_KEY is None,
    reason="DIARY_RAG_OPENAI_TEST_KEY not set; live OpenAI smoke skipped.",
)


def test_openai_client_round_trip_returns_3072_dim_vector() -> None:
    assert OPENAI_TEST_KEY is not None
    client = OpenAIEmbeddingClient(api_key=OPENAI_TEST_KEY)
    vectors = client.embed(["a short diary line"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 3072
    assert client.model_name == "text-embedding-3-large"
    assert client.dimension == 3072
