# Backlog

Top of list = pick next. Each item maps to a row in `docs/execution-map.md`. When a slice is done, remove it and add the next downstream slice.

## Slice 1.2 — Telegram adapter shell (next)
- Owner: agent
- Map: execution-map 1.2
- Concrete: webhook receiver mounted on the existing FastAPI app (D-019), command parser for `/start`, `/help`, `/entry`, `/ask`, reply formatter, dev-tunnel documentation in `QUICKSTART.md`.
- Outcome: a tunneled local run can receive a Telegram update and dispatch to a stub handler. No real provider integration.
- Done when: a manual webhook send reaches the dispatcher; smoke test exercises the handshake.

## Slice 1.3 — Mock services
- Owner: agent
- Map: execution-map 1.3
- Concrete: `MockSourceMessageRepository`, `MockSearchRepository`, `MockEmbeddingClient`, `MockChatClient` exposing the interfaces real implementations will use. Replaces the placeholder `InMemorySourceMessageStore`.
- Outcome: 1.4 and 1.5 can compose these mocks for an end-to-end smoke test without a real DB or providers.
- Done when: tests against the mocks pass; interface contracts documented.

## Slice 1.4 — Routing
- Owner: agent
- Map: execution-map 1.4
- Concrete: command + heuristic routing, low-confidence clarification path. Decides A-16/A-17.

## Slice 1.5 — Mock end-to-end smoke
- Owner: agent
- Map: execution-map 1.5
- Concrete: smoke run exercising `/entry` and `/ask` against mocks end-to-end.

---

Closed in Slice 0.3: A-1 → D-016, A-2 → D-017, A-3 → D-018, A-4 → D-019.

Closed in Slice 1.1:
- `pyproject.toml` for Python 3.11, `uv`-managed venv, Ruff + Mypy + Pytest wired.
- `Makefile` real targets: `format`, `lint`, `typecheck`, `test`, `check`, `run`.
- `src/diary_rag` package skeleton (`config`, `logging`, `app`, `__main__`) plus placeholder packages for `adapters/telegram`, `core/routing`, `services`, `storage/mock`.
- `InMemorySourceMessageStore` stub (replaced in Slice 1.3).
- FastAPI `/health` endpoint smokeable via `make run`.
- `make check` is green; `/health` returns 200.
- `.python-version` pins 3.11.
