"""Settings load from defaults without requiring secrets."""

from __future__ import annotations

from memory_rag.config import Settings


def test_settings_defaults_do_not_require_secrets() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.app_env == "local"
    assert s.log_level == "INFO"
    assert s.telegram_bot_token == ""
    assert s.openai_api_key == ""


def test_classifier_defaults_are_mock_and_unpinned() -> None:
    """RC-2 (D-108): the classifier contour defaults to mock with an empty
    model — the canonical ``gpt-4.1-mini`` pin is enforced only on the
    openai backend, by the boot gate."""
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.classifier_backend == "mock"
    assert s.classifier_model == ""
