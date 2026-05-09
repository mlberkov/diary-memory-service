"""FastAPI application factory.

Slice 1.1 wires only `/health` so the service is smokeable. The Telegram
webhook receiver and command dispatch land in Slice 1.2 under
`diary_rag.adapters.telegram`.
"""

from __future__ import annotations

from fastapi import FastAPI

from diary_rag import __version__
from diary_rag.config import Settings, get_settings
from diary_rag.logging import configure_logging, get_logger


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a FastAPI app. Pass `settings` in tests to avoid env coupling."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)
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
            "env": settings.app_env,
        }

    log.info("app.created env=%s version=%s", settings.app_env, __version__)
    return app


app = create_app()
