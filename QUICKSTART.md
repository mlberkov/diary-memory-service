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

See `.env.example` for the full list. Currently used:

- `TELEGRAM_BOT_TOKEN` — bot identity (Phase 1.2+)
- `TELEGRAM_WEBHOOK_SECRET` — required for `/telegram/webhook` to accept any call (A-26)
- `OPENAI_API_KEY`
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- `EMBEDDING_MODEL` (value not yet chosen — see `docs/assumptions.md` A-8)
- `CHAT_MODEL` (value not yet chosen — see `docs/assumptions.md` A-9)

### Required services

- **(Phase 2+)** PostgreSQL with vector + sparse-search capabilities. The exact extension/strategy is open — see `docs/assumptions.md` A-5/A-6.
- **(Phase 3+)** Outbound network access to the chosen LLM/embedding provider.

### Telegram transport

The bot uses a **webhook receiver in all environments** (D-019). Local development requires a public URL pointing at the local process — use a tunnel such as `ngrok` or `cloudflared`. Long-polling is not supported.

#### Local smoke against the webhook

```bash
export TELEGRAM_WEBHOOK_SECRET=dev-secret
make run    # FastAPI on http://127.0.0.1:8000

# 401 — missing or wrong header
curl -i -X POST http://127.0.0.1:8000/telegram/webhook \
  -H "Content-Type: application/json" \
  -d '{"update_id":1,"message":{"message_id":1,"date":1715300000,"chat":{"id":42},"from":{"id":7},"text":"/start"}}'

# 200 — sendMessage payload returned in the response body
curl -X POST http://127.0.0.1:8000/telegram/webhook \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: dev-secret" \
  -d '{"update_id":1,"message":{"message_id":1,"date":1715300000,"chat":{"id":42},"from":{"id":7},"text":"/start"}}'
# → {"method":"sendMessage","chat_id":42,"text":"Welcome — diary mode. ..."}
```

#### Registering the webhook with Telegram (when using a real bot)

```bash
# 1. Run a tunnel pointing at port 8000
ngrok http 8000   # copy the https URL it prints

# 2. Tell Telegram where to post updates and which secret to send back
curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  --data-urlencode "url=https://YOUR-TUNNEL.ngrok.app/telegram/webhook" \
  --data-urlencode "secret_token=${TELEGRAM_WEBHOOK_SECRET}"
```

## When something is broken

- Workflow & recovery: `docs/RUNBOOK.md`
- What must hold at runtime: `docs/RUNTIME-INVARIANTS.md`
- Data shape rules: `docs/INVARIANTS.md`
- Open decisions: `docs/assumptions.md`
- Why things are the way they are: `docs/decision-log.md`
