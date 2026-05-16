"""Boot-time R-10 chat gate (D-037).

``create_app`` must abort when:
- ``CHAT_BACKEND=openai`` but ``CHAT_MODEL`` ≠ ``gpt-4.1`` (the canonical
  Slice 4.5 contour);
- ``CHAT_BACKEND=openai`` and no ``OPENAI_API_KEY`` is set (the OpenAI
  chat client constructor refuses to build).

The mock contour ignores ``CHAT_MODEL`` and never requires a key.

None of the cases below make a real network call: the OpenAI client
constructor accepts any non-empty key but only opens a connection on the
first ``complete`` call.
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


def test_mock_backend_ignores_chat_model_setting() -> None:
    """With ``chat_backend=mock`` the gate does not require the chat
    model to match — only the canonical OpenAI path enforces that."""
    create_app(_settings(chat_model="anything-the-operator-wrote"))


def test_openai_chat_backend_with_canonical_model_boots_clean() -> None:
    create_app(
        _settings(
            chat_backend="openai",
            chat_model="gpt-4.1",
            openai_api_key="sk-test-not-actually-used",
        )
    )


def test_openai_chat_backend_with_wrong_model_aborts() -> None:
    with pytest.raises(BootHealthError, match="chat model mismatch"):
        create_app(
            _settings(
                chat_backend="openai",
                chat_model="gpt-4o",
                openai_api_key="sk-test-not-actually-used",
            )
        )


def test_openai_chat_backend_with_empty_model_aborts() -> None:
    with pytest.raises(BootHealthError, match="chat model mismatch"):
        create_app(
            _settings(
                chat_backend="openai",
                chat_model="",
                openai_api_key="sk-test-not-actually-used",
            )
        )


def test_openai_chat_backend_without_api_key_aborts() -> None:
    with pytest.raises(BootHealthError):
        create_app(
            _settings(
                chat_backend="openai",
                chat_model="gpt-4.1",
                openai_api_key="",
            )
        )
