# Quickstart

> The repository is in **Phase 0**. There is no runnable application yet.
> Anything below marked **(Phase 1+)** is aspirational and becomes real as phases land.

## Today

Read the docs:

```bash
git clone <this repo>
cd telegram-dairy
$EDITOR AGENTS.md
```

Read order: `AGENTS.md` → `CLAUDE.md` → `docs/product/PRD.md` → `docs/product/BuildPlan.md` → `docs/product/TechSpec.md` → `docs/decision-log.md`.

Then look at `docs/RUNBOOK.md` for how work is done here, and `docs/todo.md` for what's next.

## (Phase 1+) Local bootstrap

Tooling is locked: Python 3.11 (D-016), `uv` (D-017), Ruff + Mypy + Pytest (D-018). Once Slice 1.1 wires the targets:

```bash
uv sync                    # install deps from the uv lockfile
cp .env.example .env       # fill TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, POSTGRES_*
make check                 # ruff (lint + format check) + mypy + pytest
make run                   # start the bot locally (Phase 1.2)
```

Prerequisites: `uv` installed; `uv` will pick up or install Python 3.11.

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
