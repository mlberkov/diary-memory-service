"""Boot-time R-10 knowledge-source gate (RC-4, D-108).

``create_app`` must abort when ``KNOWLEDGE_BACKEND=tavily`` and no
``TAVILY_API_KEY`` is set (the Tavily adapter constructor refuses to
build). The mock contour never requires a key.

None of the cases below make a real network call: the Tavily client is
constructed lazily and only opens a connection on the first ``search``
call.
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


def test_mock_backend_never_requires_a_key() -> None:
    create_app(_settings(knowledge_backend="mock", tavily_api_key=""))


def test_tavily_backend_with_a_key_boots_clean() -> None:
    create_app(
        _settings(
            knowledge_backend="tavily",
            tavily_api_key="tvly-test-not-actually-used",
        )
    )


def test_tavily_backend_without_a_key_aborts() -> None:
    with pytest.raises(BootHealthError, match="TAVILY_API_KEY"):
        create_app(_settings(knowledge_backend="tavily", tavily_api_key=""))


def test_knowledge_gate_is_independent_of_the_classifier_gate() -> None:
    """The knowledge gate composes with (does not change) the RC-2
    classifier gate: a classifier-pin mismatch still aborts even when
    the knowledge contour is fine."""
    create_app(
        _settings(
            classifier_backend="openai",
            classifier_model="gpt-4.1-mini",
            openai_api_key="sk-test-not-actually-used",
            knowledge_backend="tavily",
            tavily_api_key="tvly-test-not-actually-used",
        )
    )
    with pytest.raises(BootHealthError, match="classifier model mismatch"):
        create_app(
            _settings(
                classifier_backend="openai",
                classifier_model="gpt-4.1",
                openai_api_key="sk-test-not-actually-used",
                knowledge_backend="tavily",
                tavily_api_key="tvly-test-not-actually-used",
            )
        )
