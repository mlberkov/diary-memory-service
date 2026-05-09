# Runbook — Working in this Repo

## Roles
- **Human owner** — sets product direction, approves assumptions and decisions, owns merges.
- **AI agent (Claude Code, etc.)** — drafts docs, code, and tests under the rules in `AGENTS.md` and `CLAUDE.md`.

## Canonical loop

1. **Read.** Open the canonical docs in the order set by `CLAUDE.md`. Skim recent decision-log entries.
2. **Pick.** Take the top item in `docs/todo.md`. Confirm it maps to a row in `docs/execution-map.md`.
3. **Plan.** State the slice's goal, the files it will touch, the invariants involved, the test surface, and the fallback paths. Surface every assumption.
4. **Align docs.** If the slice implies new behavior not in the canonical docs, surface the mismatch and propose the smallest fix *before* coding.
5. **Implement.** Smallest viable end-to-end slice. Mock before real. Pure functions over services where possible.
6. **Verify.** Run `make check` (when it exists) and the slice's tests. Walk through the runtime invariants for the slice's path.
7. **Update docs.** `decision-log.md` for decisions, `assumptions.md` for new open items, `todo.md` for remaining work, `execution-map.md` for new files.
8. **Commit.** Phase-aligned, small, readable.

## When canonical docs disagree with a request
- Stop. Do not silently comply.
- Quote the specific canonical text and the conflicting request.
- Propose the smallest consistent resolution: either change the request, or update the canonical doc with a new decision-log entry.

## When a runtime fallback fires
- Confirm the requested vs effective path was logged (R-6).
- Confirm the answer carried the right `fallback_mode` (R-5).
- If neither held, treat as an incident: write a decision-log entry and add an invariant if needed.

## When provider behavior degrades (Phase 6+)
- Check provider call logs (R-7).
- Confirm bounded retries (R-9) actually triggered.
- Verify durable state is intact (raw `SourceMessage` rows present; no chunks orphaned).
- Reprocess from raw via the replay path; do not hand-fix derived state.

## Local commands

The toolchain is **Python 3.11 + uv + Ruff + Mypy + Pytest** (D-016 / D-017 / D-018). Slice 1.1 wired all targets below to real commands.

- `make init` — print `uv` and Python versions.
- `make sync` — `uv sync --all-extras`.
- `make format` — Ruff format + Ruff lint autofix.
- `make lint` — Ruff lint + format check (no writes).
- `make typecheck` — Mypy strict.
- `make test` — Pytest.
- `make check` — runs `lint` + `typecheck` + `test`.
- `make run` — boot the FastAPI shell on `127.0.0.1:8000` (Slice 1.1 `/health`; Telegram webhook in Slice 1.2).
- `make tree` — show the top of the repo tree.
- `make clean` — remove caches and build artifacts.

### Telegram in local development
Webhook only (D-019). Expose the local process via a tunnel (e.g. `ngrok`, `cloudflared`) and register the tunnel URL with the bot. There is no polling fallback.

## Useful reads when stuck
- Workflow & recovery: this file.
- What must hold at runtime: `docs/RUNTIME-INVARIANTS.md`.
- Data shape rules: `docs/INVARIANTS.md`.
- Open questions: `docs/assumptions.md`.
- Why things are the way they are: `docs/decision-log.md`.
