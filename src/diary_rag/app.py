"""FastAPI application factory.

Boot gates (R-10, D-024): on app creation we build the configured
:class:`EmbeddingClient` and assert its ``model_name`` and ``dimension``
match ``Settings.embedding_model`` / ``Settings.embedding_dimension``;
a mismatch raises before any traffic is served. When
``storage_backend == "postgres"`` we additionally probe ``pg_extension``
to confirm pgvector is installed.

Slice 4.3a (D-034): the chat-client contour is gated the same way —
``build_chat_client(settings)`` must produce a client with a non-empty
``model_name``. Real provider integration lands later; for now the only
supported backend is ``mock``.

The full set of R-10 probes (schema version, full provider reachability)
lands with the migration packet — this slice only covers what the
current phase actually depends on.
"""

from __future__ import annotations

from fastapi import FastAPI

from diary_rag import __version__
from diary_rag.adapters.answers import build_chat_client
from diary_rag.adapters.embeddings import build_embedding_client
from diary_rag.adapters.telegram import register_telegram_webhook
from diary_rag.config import Settings, get_settings
from diary_rag.logging import configure_logging, get_logger


class BootHealthError(RuntimeError):
    """Raised when a boot-time health gate fails (R-10)."""


# The canonical Phase-3.1/3.2 contour locks the pgvector column at
# ``vector(3072)`` (D-024). The boot gate enforces that the operator's
# ``EMBEDDING_DIMENSION`` matches what the schema can hold so we never
# silently produce vectors the durable backend cannot store.
_CANONICAL_DIMENSION = 3072
_CANONICAL_OPENAI_MODEL = "text-embedding-3-large"


def _verify_embedding_contour(settings: Settings) -> None:
    if settings.embedding_dimension != _CANONICAL_DIMENSION:
        raise BootHealthError(
            "embedding dimension mismatch: "
            f"settings={settings.embedding_dimension} "
            f"canonical={_CANONICAL_DIMENSION} (matches pgvector column)"
        )
    if (
        settings.embedding_backend == "openai"
        and settings.embedding_model != _CANONICAL_OPENAI_MODEL
    ):
        raise BootHealthError(
            "embedding model mismatch: "
            f"settings={settings.embedding_model!r} "
            f"canonical={_CANONICAL_OPENAI_MODEL!r}"
        )
    try:
        client = build_embedding_client(settings)
    except ValueError as exc:
        raise BootHealthError(f"embedding client build failed: {exc}") from exc
    if client.dimension != settings.embedding_dimension:
        raise BootHealthError(
            "embedding client dimension mismatch: "
            f"client={client.dimension} settings={settings.embedding_dimension}"
        )


def _verify_chat_contour(settings: Settings) -> None:
    try:
        client = build_chat_client(settings)
    except ValueError as exc:
        raise BootHealthError(f"chat client build failed: {exc}") from exc
    if not client.model_name:
        raise BootHealthError("chat client reported an empty model_name")


def _verify_pgvector(settings: Settings) -> None:
    if settings.storage_backend != "postgres":
        return
    import psycopg

    try:
        with (
            psycopg.connect(settings.postgres_dsn(), connect_timeout=5) as conn,
            conn.cursor() as cur,
        ):
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            row = cur.fetchone()
    except psycopg.Error as exc:
        raise BootHealthError(f"postgres connectivity probe failed: {exc}") from exc
    if row is None:
        raise BootHealthError(
            "pgvector extension is not installed on the configured Postgres database"
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a FastAPI app. Pass `settings` in tests to avoid env coupling."""
    explicit_settings = settings
    effective_settings = explicit_settings or get_settings()
    configure_logging(effective_settings.log_level)
    log = get_logger(__name__)

    _verify_embedding_contour(effective_settings)
    _verify_chat_contour(effective_settings)
    _verify_pgvector(effective_settings)

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

    log.info(
        "app.created env=%s version=%s embedding_backend=%s embedding_dim=%d " "chat_backend=%s",
        effective_settings.app_env,
        __version__,
        effective_settings.embedding_backend,
        effective_settings.embedding_dimension,
        effective_settings.chat_backend,
    )
    return app


app = create_app()
