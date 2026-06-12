"""FastAPI application factory.

Boot gates (R-10, D-024): on app creation we build the configured
:class:`EmbeddingClient` and assert its ``model_name`` and ``dimension``
match ``Settings.embedding_model`` / ``Settings.embedding_dimension``;
a mismatch raises before any traffic is served. When
``storage_backend == "postgres"`` we additionally probe ``pg_extension``
to confirm pgvector is installed.

Slice 4.5 (D-037): the chat-client contour is gated the same way —
``build_chat_client(settings)`` must produce a client with a non-empty
``model_name``. When ``chat_backend == "openai"`` the gate additionally
asserts ``chat_model == "gpt-4.1"`` (the canonical Slice 4.5 contour);
the ``OpenAIChatClient`` constructor refuses an empty ``OPENAI_API_KEY``.

The full set of R-10 probes (schema version, full provider reachability)
lands with the migration packet — this slice only covers what the
current phase actually depends on.
"""

from __future__ import annotations

from fastapi import FastAPI

from memory_rag import __version__
from memory_rag.adapters.answers import build_chat_client
from memory_rag.adapters.chat_routing import (
    build_outward_rewriter,
    build_query_rewriter,
    build_route_classifier,
)
from memory_rag.adapters.embeddings import build_embedding_client
from memory_rag.adapters.knowledge import build_knowledge_source
from memory_rag.adapters.telegram import register_telegram_webhook
from memory_rag.config import Settings, get_settings
from memory_rag.logging import configure_logging, get_logger


class BootHealthError(RuntimeError):
    """Raised when a boot-time health gate fails (R-10)."""


# The canonical Phase-3.1/3.2 contour locks the pgvector column at
# ``vector(3072)`` (D-024). The boot gate enforces that the operator's
# ``EMBEDDING_DIMENSION`` matches what the schema can hold so we never
# silently produce vectors the durable backend cannot store.
_CANONICAL_DIMENSION = 3072
_CANONICAL_OPENAI_MODEL = "text-embedding-3-large"
_CANONICAL_OPENAI_CHAT_MODEL = "gpt-4.1"
_CANONICAL_OPENAI_CLASSIFIER_MODEL = "gpt-4.1-mini"


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
    if settings.chat_backend == "openai" and settings.chat_model != _CANONICAL_OPENAI_CHAT_MODEL:
        raise BootHealthError(
            "chat model mismatch: "
            f"settings={settings.chat_model!r} "
            f"canonical={_CANONICAL_OPENAI_CHAT_MODEL!r}"
        )
    try:
        client = build_chat_client(settings)
    except ValueError as exc:
        raise BootHealthError(f"chat client build failed: {exc}") from exc
    if not client.model_name:
        raise BootHealthError("chat client reported an empty model_name")


def _verify_classifier_contour(settings: Settings) -> None:
    if (
        settings.classifier_backend == "openai"
        and settings.classifier_model != _CANONICAL_OPENAI_CLASSIFIER_MODEL
    ):
        raise BootHealthError(
            "classifier model mismatch: "
            f"settings={settings.classifier_model!r} "
            f"canonical={_CANONICAL_OPENAI_CLASSIFIER_MODEL!r}"
        )
    try:
        client = build_route_classifier(settings)
    except ValueError as exc:
        raise BootHealthError(f"classifier client build failed: {exc}") from exc
    if not client.model_name:
        raise BootHealthError("classifier client reported an empty model_name")
    # The query rewriter rides the same contour (RC-3): same backend knob,
    # same canonical pin, one factory shared with the request path.
    try:
        rewriter = build_query_rewriter(settings)
    except ValueError as exc:
        raise BootHealthError(f"rewriter client build failed: {exc}") from exc
    if not rewriter.model_name:
        raise BootHealthError("rewriter client reported an empty model_name")
    # The outward rewriter rides the same contour too (RC-4): same backend
    # knob, same canonical pin, one factory shared with the request path.
    try:
        outward_rewriter = build_outward_rewriter(settings)
    except ValueError as exc:
        raise BootHealthError(f"outward rewriter client build failed: {exc}") from exc
    if not outward_rewriter.model_name:
        raise BootHealthError("outward rewriter client reported an empty model_name")


def _verify_knowledge_contour(settings: Settings) -> None:
    if settings.knowledge_backend == "tavily" and not settings.tavily_api_key:
        raise BootHealthError(
            "knowledge backend mismatch: "
            "knowledge_backend='tavily' requires a non-empty TAVILY_API_KEY"
        )
    try:
        source = build_knowledge_source(settings)
    except ValueError as exc:
        raise BootHealthError(f"knowledge source build failed: {exc}") from exc
    if not source.provider_name:
        raise BootHealthError("knowledge source reported an empty provider_name")


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
    _verify_classifier_contour(effective_settings)
    _verify_knowledge_contour(effective_settings)
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
        "app.created env=%s version=%s embedding_backend=%s embedding_dim=%d "
        "chat_backend=%s chat_model=%s classifier_backend=%s classifier_model=%s "
        "knowledge_backend=%s",
        effective_settings.app_env,
        __version__,
        effective_settings.embedding_backend,
        effective_settings.embedding_dimension,
        effective_settings.chat_backend,
        effective_settings.chat_model,
        effective_settings.classifier_backend,
        effective_settings.classifier_model,
        effective_settings.knowledge_backend,
    )
    return app


app = create_app()
