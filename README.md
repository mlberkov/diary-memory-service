# telegram-dairy

Diary RAG Service for **TheyGrow** — a low-friction memory system for parents who write family and child observations in Telegram and later ask natural-language questions over them.

> **Status:** Phase 0 / early Phase 1 — source-of-truth establishment mode. Canonical docs are in place; no application code yet.

## What this is

The product is a **standalone Diary Memory Service**. Telegram is the first client channel. The same service is later integrated into TheyGrow as a reusable internal memory subsystem.

Core rules (from `AGENTS.md` and the canonical docs):

- Telegram is a channel, not the system core.
- PostgreSQL is the durable source of truth.
- Raw source messages are persisted before enrichment.
- Each diary event line becomes its own chunk.
- Hybrid retrieval is required.
- Every answer is grounded in retrieved evidence.
- Optional AI enrichments are feature-flagged.
- Shared diary mode preserves authorship.

## What's in this repo

### Canonical (treat as source of truth)
- `docs/product/PRD.md` — product intent, users, scope, success criteria.
- `docs/product/BuildPlan.md` — phased build plan (Phase 0 → 9).
- `docs/product/TechSpec.md` — entities, contracts, retrieval architecture.
- `docs/decision-log.md` — accepted decisions (D-001 …).

### Operating contract
- `AGENTS.md` — operating rules for any AI agent in this repo.
- `CLAUDE.md` — Claude Code read order and working mode.

### Supporting
- `docs/ARCHITECTURE.md` — one-page system shape and layer boundaries.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` — non-negotiables.
- `docs/RUNBOOK.md` — canonical workflow inside this repo.
- `docs/CHECKLIST.md` — pre-implementation and pre-merge gates.
- `docs/execution-map.md` — phase → files map.
- `docs/assumptions.md` / `docs/assumption-audit.md` — open questions and their risk/owner.
- `docs/todo.md` — ordered backlog of the next slices.

### Scaffold
- `Makefile` — placeholder targets, no real commands yet.
- `.env.example` — config keys we expect to need.
- `.gitignore` — local artifacts and secrets.

## Current status

- Canonical docs (PRD, BuildPlan, TechSpec, decision log) populated.
- Operating contract (AGENTS, CLAUDE) populated.
- Supporting docs populated; open items surfaced in `docs/assumptions.md`.
- Phase-1 platform decisions locked: **Python 3.11** (D-016), **`uv`** (D-017), **Ruff + Mypy + Pytest** (D-018), **Telegram webhook transport** (D-019).
- No application code yet.
- Next gate: Slice 1.1 — wire the toolchain (`docs/todo.md`).

## How to start

1. Read `AGENTS.md`, then `CLAUDE.md`.
2. Read canonical docs in the order listed in `CLAUDE.md`.
3. Pick the top item from `docs/todo.md` and follow `docs/RUNBOOK.md`.
