# Backlog

Top of list = pick next. Each item maps to a row in `docs/execution-map.md`. When a slice is done, remove it and add the next downstream slice.

## Slice 1.3 — Remaining mock services (next)
- Owner: agent
- Map: execution-map 1.3
- Concrete: `MockEmbeddingClient` and `MockChatClient` once the interfaces they will mirror are sketched in slice 3.1 / 4.1. Hold until those interfaces are clearer; mock provider clients ahead of their real shape locks the wrong contract.

## Slice 1.4 — Routing
- Owner: agent
- Map: execution-map 1.4
- Concrete: heuristic plain-text routing (date-led → entry, otherwise → ask) and the low-confidence clarification path. Decides A-16/A-17.

## Slice 1.5 — Mock end-to-end smoke (extend)
- Owner: agent
- Map: execution-map 1.5
- Concrete: extend the existing smoke once heuristic routing lands so plain-text messages flow through the same diary/query services.

## TechSpec field-name reconciliation
- `core/diary/models.SourceMessage` uses `external_chat_id` / `external_user_id` to keep the channel-of-origin out of core (Invariant I-1). TechSpec §5 still names these fields `telegram_chat_id` / `telegram_user_id`. Reconcile before Phase 2.1 schema lands — either rename the spec fields, or introduce a `channel_kind` + `external_*` pair.

---

Closed in Slice 0.3: A-1 → D-016, A-2 → D-017, A-3 → D-018, A-4 → D-019.

Closed in Slice 1.1:
- `pyproject.toml` for Python 3.11, `uv`-managed venv, Ruff + Mypy + Pytest wired.
- `Makefile` real targets: `format`, `lint`, `typecheck`, `test`, `check`, `run`.
- `src/diary_rag` package skeleton (`config`, `logging`, `app`, `__main__`) plus placeholder packages for `adapters/telegram`, `core/routing`, `services`, `storage/mock`.
- FastAPI `/health` endpoint smokeable via `make run`.
- `make check` is green; `/health` returns 200.
- `.python-version` pins 3.11.

Closed in Slice 1.2:
- `POST /telegram/webhook` mounted on the FastAPI app (D-019).
- `X-Telegram-Bot-Api-Secret-Token` validation, fail-closed when secret is unset or mismatched (A-26).
- Telegram update Pydantic schema (`adapters/telegram/models.py`).
- Command parser for `/start`, `/help`, `/entry`, `/ask` with `@BotName` suffix stripping.
- Channel-neutral routing types in `core/routing` (`RouteKind`, `InboundMessage`, `DispatchResult`).
- `Dispatcher` (`services/dispatcher.py`) with stub handlers per route.
- `sendMessage`-shaped JSON returned in the webhook response body — no outbound HTTP.
- Tests: secret gating, command parsing, dispatch wiring, reply payload, update schema.
- New open assumption: A-26.

Closed in the mock diary/query contour packet:
- Channel-neutral domain dataclasses `SourceMessage`, `DiaryEntry`, `EventChunk`, plus `Evidence`, `IngestResult`, `AnswerResult`, `FallbackMode` in `core/diary/models.py`.
- Strict ISO-only date parser in `core/diary/parser.py`.
- `MockDiaryStore` (`storage/mock/store.py`) holds sources, entries, chunks; deterministic case-insensitive substring search scoped to `family_id`.
- `DiaryService` records the raw `SourceMessage` before parsing (I-3, R-1) and falls back to `INVALID_INPUT` on a non-ISO first line; `QueryService` returns `NO_EVIDENCE` rather than fabricating answers (I-9, R-5/R-6) and rejects calls without `family_id` (R-3).
- `Dispatcher` wires `ENTRY` → `DiaryService.ingest`, `ASK` → `QueryService.answer`, with channel-neutral reply formatting.
- Webhook smoke: `/entry 2026-05-09\n…` then `/ask <substring>` returns a grounded-style mock reply listing the matched line with its date.
- New open assumptions: A-28 (mock ISO-only date parsing), A-29 (substring-match retrieval), A-30 (process-local non-idempotent mock state).
- `AnswerTrace` persistence is deliberately deferred to Phase 4.
