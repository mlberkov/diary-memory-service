"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from diary_rag import __version__
from diary_rag.adapters.telegram import register_telegram_webhook
from diary_rag.config import Settings, get_settings
from diary_rag.logging import configure_logging, get_logger


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a FastAPI app. Pass `settings` in tests to avoid env coupling."""
    explicit_settings = settings
    effective_settings = explicit_settings or get_settings()
    configure_logging(effective_settings.log_level)
    log = get_logger(__name__)

    app = FastAPI(
        title="Diary RAG Service",
        version=__version__,
        docs_url="/docs",
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "version": __version__,
            "env": effective_settings.app_env,
        }

    register_telegram_webhook(app)

    if explicit_settings is not None:
        app.dependency_overrides[get_settings] = lambda: explicit_settings

    log.info("app.created env=%s version=%s", effective_settings.app_env, __version__)
    return app


app = create_app()
