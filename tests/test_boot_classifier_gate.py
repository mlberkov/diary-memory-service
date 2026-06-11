"""Boot-time R-10 classifier gate (RC-2, D-108).

``create_app`` must abort when:
- ``CLASSIFIER_BACKEND=openai`` but ``CLASSIFIER_MODEL`` ≠ ``gpt-4.1-mini``
  (the canonical RC-2 pin — separate from the D-037 ``CHAT_MODEL`` gate);
- ``CLASSIFIER_BACKEND=openai`` and no ``OPENAI_API_KEY`` is set (the
  OpenAI classifier constructor refuses to build).

The mock contour ignores ``CLASSIFIER_MODEL`` and never requires a key.

None of the cases below make a real network call: the OpenAI client
constructor accepts any non-empty key but only opens a connection on the
first ``classify`` call.
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


def test_mock_backend_ignores_classifier_model_setting() -> None:
    """With ``classifier_backend=mock`` the gate does not require the
    classifier model to match — only the canonical OpenAI path enforces
    that."""
    create_app(_settings(classifier_model="anything-the-operator-wrote"))


def test_openai_classifier_backend_with_canonical_model_boots_clean() -> None:
    create_app(
        _settings(
            classifier_backend="openai",
            classifier_model="gpt-4.1-mini",
            openai_api_key="sk-test-not-actually-used",
        )
    )


def test_openai_classifier_backend_with_wrong_model_aborts() -> None:
    with pytest.raises(BootHealthError, match="classifier model mismatch"):
        create_app(
            _settings(
                classifier_backend="openai",
                classifier_model="gpt-4.1",
                openai_api_key="sk-test-not-actually-used",
            )
        )


def test_openai_classifier_backend_with_empty_model_aborts() -> None:
    with pytest.raises(BootHealthError, match="classifier model mismatch"):
        create_app(
            _settings(
                classifier_backend="openai",
                classifier_model="",
                openai_api_key="sk-test-not-actually-used",
            )
        )


def test_openai_classifier_backend_without_api_key_aborts() -> None:
    with pytest.raises(BootHealthError):
        create_app(
            _settings(
                classifier_backend="openai",
                classifier_model="gpt-4.1-mini",
                openai_api_key="",
            )
        )


def test_classifier_gate_is_independent_of_the_chat_gate() -> None:
    """The classifier pin is a separate canonical pin alongside (not a
    change to) the D-037 chat gate: both openai contours boot together
    only with both canonical models."""
    create_app(
        _settings(
            chat_backend="openai",
            chat_model="gpt-4.1",
            classifier_backend="openai",
            classifier_model="gpt-4.1-mini",
            openai_api_key="sk-test-not-actually-used",
        )
    )
    with pytest.raises(BootHealthError, match="classifier model mismatch"):
        create_app(
            _settings(
                chat_backend="openai",
                chat_model="gpt-4.1",
                classifier_backend="openai",
                classifier_model="gpt-4.1",
                openai_api_key="sk-test-not-actually-used",
            )
        )
