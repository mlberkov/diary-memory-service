"""Boot-time R-10 gate (D-024).

``create_app`` must abort when:
- ``EMBEDDING_DIMENSION`` ≠ 3072 (the canonical pgvector column dim),
- ``EMBEDDING_BACKEND=openai`` but ``EMBEDDING_MODEL`` ≠
  ``text-embedding-3-large``,
- ``EMBEDDING_BACKEND=openai`` and no ``OPENAI_API_KEY`` is set
  (the OpenAI client constructor refuses to build).

The pgvector probe is exercised only when ``storage_backend ==
"postgres"``; the default ``memory`` backend skips it so tests run
without Docker.
"""

from __future__ import annotations

from typing import Any

import pytest

from memory_rag.app import BootHealthError, create_app
from memory_rag.config import Settings


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_default_settings_boot_clean() -> None:
    create_app(_settings())


def test_mismatched_dimension_aborts_boot() -> None:
    with pytest.raises(BootHealthError, match="dimension mismatch"):
        create_app(_settings(embedding_dimension=1536))


def test_smaller_dimension_aborts_boot() -> None:
    with pytest.raises(BootHealthError, match="dimension mismatch"):
        create_app(_settings(embedding_dimension=64))


def test_mock_backend_ignores_model_name_setting() -> None:
    """With ``embedding_backend=mock`` the gate does not require the
    model name to match — only the canonical OpenAI path enforces that."""
    create_app(_settings(embedding_model="anything-the-operator-wrote"))


def test_openai_backend_with_wrong_model_aborts() -> None:
    with pytest.raises(BootHealthError, match="model mismatch"):
        create_app(
            _settings(
                embedding_backend="openai",
                embedding_model="text-embedding-3-small",
                openai_api_key="sk-test-not-actually-used",
            )
        )


def test_openai_backend_without_api_key_aborts() -> None:
    with pytest.raises(BootHealthError):
        create_app(_settings(embedding_backend="openai", openai_api_key=""))
