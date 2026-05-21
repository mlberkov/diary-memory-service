# DEPLOY-1.2 (D-061) — VPS runtime image for memory_rag.
#
# Base: python:3.11-slim (matches pyproject requires-python >=3.11,<3.12).
# Tooling: uv (matches the repo's UV-based workflow); uv sync consumes
# uv.lock. Runtime user: UID 10001 (non-root). CMD is intentionally
# omitted — each docker-compose service supplies its own command
# (see docker-compose.yml: app_init runs the migrations runner; app
# runs uvicorn behind FastAPI).

FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 --shell /bin/sh app \
    && chown -R app:app /app

USER app
