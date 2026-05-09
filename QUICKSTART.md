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

Once Slice 1.1 lands and a language is chosen, the loop will look like this:

```bash
cp .env.example .env       # fill TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, POSTGRES_*
make init                  # environment sanity
make check                 # lint + types + tests + config
make run                   # start the bot locally
```

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

Phase 1 uses a webhook receiver (per BuildPlan §Phase 1). Local-dev tunneling vs. polling is open — see `docs/assumptions.md` A-4.

## When something is broken

- Workflow & recovery: `docs/RUNBOOK.md`
- What must hold at runtime: `docs/RUNTIME-INVARIANTS.md`
- Data shape rules: `docs/INVARIANTS.md`
- Open decisions: `docs/assumptions.md`
- Why things are the way they are: `docs/decision-log.md`
