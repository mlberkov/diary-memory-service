# Backlog

Top of list = pick next. Each item maps to a row in `docs/execution-map.md`. When a slice is done, remove it and add the next downstream slice.

## Slice 1.3 — Remaining mock services (next)
- Owner: agent
- Map: execution-map 1.3
- Concrete: `MockEmbeddingClient` and `MockChatClient` once the interfaces they will mirror are sketched in slice 3.1 / 4.1. Hold until those interfaces are clearer; mock provider clients ahead of their real shape locks the wrong contract.

## Schema evolution before non-local deployment
- No migration tool is wired yet (A-34). Local Postgres schema upgrades are destructive: pull a packet that changes columns and you must `docker compose down -v` to reset `diary_pg_data` before the bootstrap DDL applies. This is acceptable for the single-dev contour but must be replaced (Alembic or equivalent) before the first non-local deployment. Consider a dedicated packet once the next production-shaped slice is on the horizon.

---

Closed in the webhook idempotency packet (D-023, slice 2.4):
- `SourceMessage` and `InboundMessage` now carry `external_message_id` and `edit_seq`; the idempotency key is `(external_chat_id, external_message_id, edit_seq)`.
- `DiaryRepository.get_or_create_source_message` returns `(SourceMessage, bool)` where the bool indicates replay/existing-row; mock, sqlite, and postgres backends all enforce uniqueness via DB-native conflict handling (`INSERT ... ON CONFLICT DO NOTHING` / `INSERT OR IGNORE` / dict-keyed dedupe).
- `DiaryRepository` gains `get_diary_entry_by_source_message_id` and `count_event_chunks_for_source` so `DiaryService.ingest` can reconstruct the original `IngestResult` on replay without re-parsing or re-chunking.
- `IngestResult.replayed: bool` flag propagates through `Dispatcher` metadata; the Telegram webhook log line now includes `edit_seq=…` and `effective_path=fresh|replay`.
- `TelegramMessage` accepts an optional `edit_date`; the webhook derives `edit_seq = edit_date if present else 0`.
- TechSpec §5 reconciled: `telegram_chat_id` / `telegram_user_id` → `external_chat_id` / `external_user_id`, plus `external_message_id` and `edit_seq`.
- Closed A-30 (mock non-idempotent state). Updated A-33 (Postgres contour). Opened A-34 (destructive local schema upgrades — no migration tool yet).
- New tests across all backends and the E2E webhook layer assert: replay short-circuits with no duplicate rows, edited state coexists as a distinct row, replay log line carries `effective_path=replay`.

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

Closed in the heuristic-routing packet:
- `core/routing/classifier.py` with deterministic ENTRY/ASK/CLARIFY rules; reuses `parse_diary_entry` for ISO-date detection (A-28).
- `RouteKind.CLARIFY` added; `InboundMessage.route_source` is now required (`"command"` | `"heuristic"`).
- Webhook calls the classifier when `parse_command` returns UNKNOWN with non-empty text; logs `route` + `route_source` + `confidence`.
- Dispatcher gains a CLARIFY handler with a fixed reply naming `/entry` and `/ask`; heuristic-routed ENTRY/ASK replies carry an explicit marker (R-6).
- `QueryService` strips trailing `?.!,;:` from the query payload before substring search — minimum normalization for plain-text questions to match.
- E2E smoke (`tests/test_end_to_end_smoke.py`) covers heuristic ENTRY, heuristic ASK, and CLARIFY (latter asserts no persistence).
- New decision: D-020 (heuristic routing rules + CLARIFY UX), closing A-16 and A-17. New open assumption: A-31 (mock-only per-route persistence).

Closed in the canonical local Postgres backend packet:
- `src/diary_rag/storage/postgres/{__init__,store}.py` — `PostgresDiaryStore` implementing `DiaryRepository` via psycopg3 sync + `psycopg_pool.ConnectionPool`; deterministic `close()` for tests/local use.
- `src/diary_rag/storage/postgres/schema.sql` — single canonical DDL loaded via `importlib.resources`; CREATE TABLE / CREATE INDEX IF NOT EXISTS; `detected_route` CHECK covers all `RouteKind` values.
- `docker-compose.yml` — single `postgres:16-alpine` service with `${VAR:-default}` env, named volume `diary_pg_data`, `pg_isready` healthcheck.
- `tests/test_postgres_store.py` — gated by `DIARY_RAG_PG_TEST_DSN`; mirrors SQLite cases (round-trip, family scoping, top-k, case-insensitive, empty inputs, R-3, restart survival).
- `config.Settings.postgres_dsn()` helper; `storage_backend` Literal extended to include `"postgres"`; `_build_store` adds a postgres branch with lazy import.
- `pyproject.toml`: `psycopg[binary]` and `psycopg-pool` runtime deps; hatch force-include for `schema.sql`.
- Docs: D-022 in `decision-log.md`; A-32 closed and A-33 opened in `assumptions.md`; row 2.0 added to `execution-map.md`; Postgres section in `QUICKSTART.md`; pointer in `RUNBOOK.md`; comment in `.env.example`.

Closed in the mock diary/query contour packet:
- Channel-neutral domain dataclasses `SourceMessage`, `DiaryEntry`, `EventChunk`, plus `Evidence`, `IngestResult`, `AnswerResult`, `FallbackMode` in `core/diary/models.py`.
- Strict ISO-only date parser in `core/diary/parser.py`.
- `MockDiaryStore` (`storage/mock/store.py`) holds sources, entries, chunks; deterministic case-insensitive substring search scoped to `family_id`.
- `DiaryService` records the raw `SourceMessage` before parsing (I-3, R-1) and falls back to `INVALID_INPUT` on a non-ISO first line; `QueryService` returns `NO_EVIDENCE` rather than fabricating answers (I-9, R-5/R-6) and rejects calls without `family_id` (R-3).
- `Dispatcher` wires `ENTRY` → `DiaryService.ingest`, `ASK` → `QueryService.answer`, with channel-neutral reply formatting.
- Webhook smoke: `/entry 2026-05-09\n…` then `/ask <substring>` returns a grounded-style mock reply listing the matched line with its date.
- New open assumptions: A-28 (mock ISO-only date parsing), A-29 (substring-match retrieval), A-30 (process-local non-idempotent mock state).
- `AnswerTrace` persistence is deliberately deferred to Phase 4.
