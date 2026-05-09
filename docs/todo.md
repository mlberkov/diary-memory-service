# Backlog

Top of list = pick next. Each item maps to a row in `docs/execution-map.md`. When a slice is done, remove it and add the next downstream slice.

## Slice 1.1 — Language & toolchain (next)
- Owner: agent
- Map: execution-map 1.1
- Concrete: `pyproject.toml` for Python 3.11 (D-016), `uv` lockfile (D-017), Ruff + Mypy + Pytest configs (D-018); real `make format`, `make lint`, `make typecheck`, `make test`, `make check`.
- Outcome: an empty test suite passes; `make check` runs the full toolchain on a fresh clone.
- Done when: `make check` is green in CI; `docs/RUNBOOK.md` matches the wired commands.

## Slice 1.2 — Telegram adapter shell
- Owner: agent
- Map: execution-map 1.2
- Concrete: webhook receiver (D-019), command parser for `/start`, `/help`, `/entry`, `/ask`, reply formatter, dev-tunnel documentation in `QUICKSTART.md`.
- Outcome: a tunneled local run can receive a Telegram update and dispatch to a stub handler. No real provider integration.
- Done when: a manual webhook send reaches the dispatcher; smoke test exercises the handshake.

## Slice 1.3 — Mock services
- Owner: agent
- Map: execution-map 1.3
- Concrete: `MockSourceMessageRepository`, `MockSearchRepository`, `MockEmbeddingClient`, `MockChatClient` exposing the interfaces real implementations will use.
- Outcome: 1.4 and 1.5 can compose these mocks for an end-to-end smoke test without a real DB or providers.
- Done when: tests against the mocks pass; interface contracts documented.

---

Closed in Slice 0.3 (this pass): A-1 → D-016, A-2 → D-017, A-3 → D-018, A-4 → D-019. Slice 0.2 (supporting docs baseline) and Slice 0.3 (resolve Phase-0 blockers) are done.
