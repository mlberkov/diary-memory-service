"""Process configuration loaded from environment / .env.

Fields are intentionally optional at Slice 1.1 so that tests and a smoke
boot do not require real provider credentials. Each field becomes required
in the slice that depends on it (see docs/execution-map.md).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Application settings.

    Sources, in order of precedence: real environment > `.env` > defaults.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = Field(default="local", description="local|dev|staging|prod")
    log_level: LogLevel = Field(default="INFO")

    # Filled in by later slices. Empty defaults so Slice 1.1 boots clean.
    telegram_bot_token: str = Field(default="")
    openai_api_key: str = Field(default="")

    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432)
    postgres_db: str = Field(default="theygrow_diary_rag")
    postgres_user: str = Field(default="postgres")
    postgres_password: str = Field(default="postgres")

    embedding_model: str = Field(default="")
    chat_model: str = Field(default="")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached Settings instance."""
    return Settings()
