"""Unit tests for :class:`MockEmbeddingClient` (D-024).

The mock is the test/dev default; it must be deterministic, must
report the right dimension, and must keep its provider identity
honest (``model_name == "mock"``).
"""

from __future__ import annotations

import pytest

from memory_rag.adapters.embeddings import MockEmbeddingClient


def test_mock_client_reports_mock_model_name() -> None:
    client = MockEmbeddingClient()
    assert client.model_name == "mock"


def test_mock_client_reports_configured_dimension() -> None:
    assert MockEmbeddingClient().dimension == 3072
    assert MockEmbeddingClient(dimension=64).dimension == 64


def test_mock_client_returns_vector_of_configured_dimension() -> None:
    client = MockEmbeddingClient(dimension=3072)
    vectors = client.embed(["hello"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 3072
    assert all(isinstance(x, float) for x in vectors[0])


def test_mock_client_is_deterministic_for_same_input() -> None:
    client = MockEmbeddingClient(dimension=128)
    a = client.embed(["walked the dog"])[0]
    b = client.embed(["walked the dog"])[0]
    assert a == b


def test_mock_client_produces_distinct_vectors_for_distinct_inputs() -> None:
    client = MockEmbeddingClient(dimension=128)
    a, b = client.embed(["walked the dog", "made pasta"])
    assert a != b


def test_mock_client_preserves_input_order() -> None:
    client = MockEmbeddingClient(dimension=64)
    single = client.embed(["alpha"])[0]
    batch = client.embed(["alpha", "beta"])[0]
    assert single == batch


def test_mock_client_rejects_non_positive_dimension() -> None:
    with pytest.raises(ValueError):
        MockEmbeddingClient(dimension=0)
    with pytest.raises(ValueError):
        MockEmbeddingClient(dimension=-1)


def test_mock_client_handles_empty_input() -> None:
    client = MockEmbeddingClient(dimension=64)
    assert client.embed([]) == []
