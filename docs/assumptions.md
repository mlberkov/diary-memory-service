# Open Assumptions

Not yet locked. Each item must either be promoted to `docs/decision-log.md` (with the next D-### id) or explicitly deferred before the phase that depends on it begins.

Add new items here the moment one is identified. Do not let assumptions live only in code or chat.

## Storage & search
- **A-5. PostgreSQL extensions**: pgvector for dense vectors is the leading candidate but not locked. The sparse retrieval mechanism (Postgres FTS, ParadeDB, external) is also not locked. Required before Phase 3.
- **A-6. Hybrid retrieval implementation**: where dense and sparse signals merge (DB-side, app-side, or external) is undecided. Required before Phase 3.
- **A-7. Indexing path (sync vs async)**: BuildPlan §Phase 3 mentions "indexing queue or async job". Whether MVP uses sync indexing on ingest or a background queue is undecided.
- **A-8. Embedding model & dimension**: `EMBEDDING_MODEL` env var is empty. Specific model and vector dimension undecided. Required before Phase 3.
- **A-9. Chat model**: `CHAT_MODEL` env var is empty. Specific model undecided. Required before Phase 4.

## Domain semantics
- **A-10. Edit/delete strategy**: TechSpec §12 explicitly leaves this open — revisions vs in-place mutation, tombstones vs hard delete, re-indexing trigger. Required before Phase 2.5.
- **A-11. Diary entry grouping**: whether consecutive Telegram messages within a window can form one logical entry, or each Telegram message is one entry. PRD example shows a single multi-line message. Required before Phase 2.3.
- **A-12. Date parsing scope**: which date formats are accepted (ISO only? localized? relative like "yesterday"?). Required before Phase 2.3.
- **A-13. Timezone handling**: where the entry timezone comes from (per-user setting, Telegram metadata, default). Required before Phase 2.3.
- **A-14. Family/child bootstrap**: how `Family` and `Child` records are first created — implicit on first message, or explicit `/setup`. Required before Phase 2.1.
- **A-15. Visibility scopes**: enumerated values for `visibility_scope` are undefined. Required before Phase 8.

## Routing & UX
*A-16 → D-020. A-17 → D-020.*

## Privacy & lifecycle
- **A-18. Data residency**: not stated.
- **A-19. Retention policy**: revision and trace retention are not bounded. Required before Phase 8.
- **A-20. Export/delete semantics**: shape of user-initiated export and delete is unspecified.

## Integration target
- **A-21. TheyGrow integration surface**: HTTP API, in-process SDK, or message bus. Required before Phase 9.

## Operational
- **A-22. Hosting target**: where the service runs (local-only MVP? managed PaaS? self-hosted VM?). Required before Phase 6.
- **A-23. Backup strategy**: not stated. Required before Phase 7/8.

## Naming & layout
- **A-24. Python package name**: Slice 1.1 introduced `diary_rag` (PyPI distribution name `diary-rag`) as the import root. Rationale: short, channel-neutral, matches "Diary Memory Service" naming. Not yet promoted to a decision-log entry. If a different name is preferred before Phase 9 (TheyGrow integration surface, A-21), rename now while the cost is low.
- **A-25. Health endpoint contract**: `/health` currently returns `{status, version, env}`. The full set of boot health checks (PostgreSQL connectivity, schema version, embedding-model dimension — see R-10) lands in Phase 2/3. The Slice 1.1 endpoint is a liveness probe only.

## Adapter security
- **A-26. Webhook secret enforcement**: the `/telegram/webhook` endpoint fails closed when `TELEGRAM_WEBHOOK_SECRET` is unset or mismatched (returns 401). The `X-Telegram-Bot-Api-Secret-Token` header is compared with `secrets.compare_digest`.

## Mock contour (current)
- **A-28. Mock `/entry` accepts ISO-only dates**: the date parser in `core/diary/parser.py` recognizes only `YYYY-MM-DD` on the first non-empty line. Anything else returns `INVALID_INPUT`. Precursor to A-12 (date parsing scope).
- **A-29. Mock retrieval is case-insensitive substring match**: `MockDiaryStore.search_chunks` is the only retrieval surface; results are scoped to one `family_id` and returned in insertion order. Precursor to A-5/A-6 (hybrid retrieval design) and to the eventual `SearchRepository` interface.
*A-30 → D-023.*
- **A-31. Mock per-route persistence**: in the current in-memory contour, only ENTRY messages persist a `SourceMessage`; ASK and CLARIFY do not. This describes mock behavior only — it is not an architectural rule about durable storage. Per-route persistence semantics are an open design question for Phase 2 and are not bound by this assumption.

## Local Postgres contour (current)
- **A-33. Local Postgres durable contour**: with `STORAGE_BACKEND=postgres`, the service writes through `PostgresDiaryStore` (psycopg3 sync + `psycopg_pool.ConnectionPool`) to the Postgres provided by `docker-compose.yml`. Schema is bootstrapped at process start from `src/diary_rag/storage/postgres/schema.sql` via `CREATE TABLE / CREATE INDEX IF NOT EXISTS`; no migration tool is wired. Retrieval reuses the same case-insensitive substring contract as the mock (A-29), now executed against Postgres with `lower(chunk_text) LIKE %s`. Webhook idempotency (R-2) is enforced by `UNIQUE (external_chat_id, external_message_id, edit_seq)` plus `INSERT ... ON CONFLICT DO NOTHING` in `get_or_create_source_message` (D-023). SQLite remains opt-in for offline dev; the canonical durable target is Postgres (D-007 / D-022).

## Schema evolution
- **A-34. Local schema upgrades are destructive**: with no migration tool in place, schema changes that add or alter columns require resetting the local Postgres volume (`docker compose down -v`) before the bootstrap DDL applies cleanly. SQLite picks up the new schema on a fresh DB file. Production schema evolution must be solved before the first non-local deployment; a future packet may introduce Alembic.

---

## Recently closed
- A-1 → D-016 (Python 3.11 as implementation language).
- A-2 → D-017 (`uv` as dependency and environment manager).
- A-3 → D-018 (Ruff + Mypy + Pytest as baseline toolchain).
- A-4 → D-019 (Telegram webhook transport, dev via tunnel).
- A-16 → D-020 (heuristic routing rule set with explicit confidence labels).
- A-17 → D-020 (CLARIFY reply naming both `/entry` and `/ask`).
- A-30 → D-023 (mock non-idempotent state; idempotency now enforced across all backends).
- A-32 → D-022 (Postgres replaces SQLite as the canonical durable backend; SQLite stays opt-in).
