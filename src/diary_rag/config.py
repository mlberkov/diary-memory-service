"""Process configuration loaded from environment / .env.

Fields are intentionally optional at Slice 1.1 so that tests and a smoke
boot do not require real provider credentials. Each field becomes required
in the slice that depends on it (see docs/execution-map.md).

Phase 3.1+3.2 (D-024) makes the embedding contour load-bearing:
``embedding_backend`` selects ``mock`` (default — used by every
automated test and by any boot without an OpenAI key) or ``openai``.
``embedding_model`` and ``embedding_dimension`` default to the canonical
quality-first contour (``text-embedding-3-large``, 3072). The boot gate
in ``app.py`` cross-checks these against the live ``EmbeddingClient``;
a mismatch aborts startup (R-10).

Slice 3.3 (D-025) adds two retrieval knobs (``retrieval_top_k``,
``retrieval_candidate_k``) used by ``QueryService`` to size the dense /
sparse candidate pools and the final evidence list returned to the
answer pipeline.
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

    # Filled in by later slices. Empty defaults so the service boots clean.
    telegram_bot_token: str = Field(default="")
    telegram_webhook_secret: str = Field(default="")
    openai_api_key: str = Field(default="")

    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432)
    postgres_db: str = Field(default="theygrow_diary_rag")
    postgres_user: str = Field(default="postgres")
    postgres_password: str = Field(default="postgres")

    storage_backend: Literal["memory", "sqlite", "postgres"] = Field(default="memory")
    sqlite_path: str = Field(default="./data/diary.db")

    embedding_backend: Literal["mock", "openai"] = Field(default="mock")
    embedding_model: str = Field(default="text-embedding-3-large")
    embedding_dimension: int = Field(default=3072)
    chat_model: str = Field(default="")

    # Slice 3.3 (D-025) baseline-hybrid retrieval knobs. Defaults are
    # tuning placeholders, not quality claims; the next quality-decision
    # packet revisits them alongside BM25 / rerankers / external search
    # backends.
    retrieval_top_k: int = Field(default=5, ge=1)
    retrieval_candidate_k: int = Field(default=20, ge=1)

    # /drafts recall knobs. ``drafts_default_limit`` is used when the user
    # omits ``N``; ``drafts_max_limit`` is a silent defensive cap so that
    # an explicit ``N`` larger than the cap is served clamped (the user is
    # told via the reply header, not via a usage error).
    drafts_default_limit: int = Field(default=5, ge=1)
    drafts_max_limit: int = Field(default=20, ge=1)

    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached Settings instance."""
    return Settings()
