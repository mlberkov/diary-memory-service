"""Settings load from defaults without requiring secrets."""

from __future__ import annotations

from diary_rag.config import Settings


def test_settings_defaults_do_not_require_secrets() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.app_env == "local"
    assert s.log_level == "INFO"
    assert s.telegram_bot_token == ""
    assert s.openai_api_key == ""
