# Quickstart

> The repository is in **early Phase 1**. The toolchain is wired and the FastAPI shell boots.
> Telegram, ingestion, retrieval, and provider integration are still pending — see `docs/todo.md`.

## Read first

```bash
git clone <this repo>
cd telegram-dairy
$EDITOR AGENTS.md
```

Read order: `AGENTS.md` → `CLAUDE.md` → `docs/product/PRD.md` → `docs/product/BuildPlan.md` → `docs/product/TechSpec.md` → `docs/decision-log.md`.

Then look at `docs/RUNBOOK.md` for how work is done here, and `docs/todo.md` for what's next.

## Local bootstrap

Tooling is locked: Python 3.11 (D-016), `uv` (D-017), Ruff + Mypy + Pytest (D-018).

Prerequisites: `uv` installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`). `uv` will pick up or install the Python 3.11 interpreter pinned in `.python-version`.

```bash
uv sync --all-extras       # install runtime + dev deps; creates .venv
cp .env.example .env       # optional at Slice 1.1; fill in as later slices need it
make check                 # ruff (lint + format check) + mypy + pytest
make run                   # boot the FastAPI shell on http://127.0.0.1:8000
curl http://127.0.0.1:8000/health
# {"status":"ok","version":"0.0.0","env":"local"}
```

Available `make` targets: `init`, `sync`, `format`, `lint`, `typecheck`, `test`, `check`, `run`, `tree`, `clean`.

### Required environment

See `.env.example` for the full list. As of Phase 0:

- `TELEGRAM_BOT_TOKEN`
- `OPENAI_API_KEY`
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- `EMBEDDING_MODEL` (value not yet chosen — see `docs/assumptions.md` A-8)
- `CHAT_MODEL` (value not yet chosen — see `docs/assumptions.md` A-9)

### Required services

- **(Phase 2+)** PostgreSQL with vector + sparse-search capabilities. The exact extension/strategy is open — see `docs/assumptions.md` A-5/A-6.
- **(Phase 3+)** Outbound network access to the chosen LLM/embedding provider.

### Telegram transport

The bot uses a **webhook receiver in all environments** (D-019). Local development requires a public URL pointing at the local process — use a tunnel such as `ngrok` or `cloudflared`. Long-polling is not supported.

## When something is broken

- Workflow & recovery: `docs/RUNBOOK.md`
- What must hold at runtime: `docs/RUNTIME-INVARIANTS.md`
- Data shape rules: `docs/INVARIANTS.md`
- Open decisions: `docs/assumptions.md`
- Why things are the way they are: `docs/decision-log.md`
