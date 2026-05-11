# Open Assumptions

Not yet locked. Each item must either be promoted to `docs/decision-log.md` (with the next D-### id) or explicitly deferred before the phase that depends on it begins.

Add new items here the moment one is identified. Do not let assumptions live only in code or chat.

## Storage & search
*A-5 → D-024. A-6 → D-025. A-7 → D-024. A-8 → D-024.*
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
- **A-20. Export/delete semantics**: directionally answered by D-027 for the export half — raw export on demand in JSON or TXT, scope-bounded. Remaining open: delivery channel per host (Telegram file reply / HTTP download / host-app screen), request shape, and the deletion half (still tied to A-10 edit/delete strategy).

## Integration target
- **A-21. TheyGrow integration surface**: HTTP API, in-process SDK, or message bus. Required before Phase 9.

## Operational
- **A-22. Hosting target**: directionally answered by D-027 — managed cloud is the default reference deployment shape; self-hosted OSS and embedded (TheyGrow) are peer shapes. Remaining open: which specific managed environment is the production reference (see A-41 below). Required before Phase 6.
- **A-23. Backup strategy**: directionally answered by D-027 — daily backup window (`03:00–05:00` target) covering at minimum `source_messages` plus enough relational scaffolding to restore lineage, plus a stronger-than-nightly recovery primitive. Remaining open: specific tooling and RPO/RTO targets (see A-40 below). Required before Phase 7/8.

## Naming & layout
- **A-24. Python package name**: Slice 1.1 introduced `diary_rag` (PyPI distribution name `diary-rag`) as the import root. Rationale: short, channel-neutral, matches "Diary Memory Service" naming. Not yet promoted to a decision-log entry. If a different name is preferred before Phase 9 (TheyGrow integration surface, A-21), rename now while the cost is low.
- **A-25. Health endpoint contract**: `/health` currently returns `{status, version, env}`. The full set of boot health checks (PostgreSQL connectivity, schema version, embedding-model dimension — see R-10) lands in Phase 2/3. The Slice 1.1 endpoint is a liveness probe only.

## Adapter security
- **A-26. Webhook secret enforcement**: the `/telegram/webhook` endpoint fails closed when `TELEGRAM_WEBHOOK_SECRET` is unset or mismatched (returns 401). The `X-Telegram-Bot-Api-Secret-Token` header is compared with `secrets.compare_digest`.

## Mock contour (current)
- **A-28. Mock `/entry` accepts ISO-only dates**: the date parser in `core/diary/parser.py` recognizes only `YYYY-MM-DD` on the first non-empty line. Anything else returns `INVALID_INPUT`. Precursor to A-12 (date parsing scope).
*A-29 → D-025.*
*A-30 → D-023.*
- **A-31. Mock per-route persistence**: in the current in-memory contour, only ENTRY messages persist a `SourceMessage`; ASK and CLARIFY do not. This describes mock behavior only — it is not an architectural rule about durable storage. Per-route persistence semantics are an open design question for Phase 2 and are not bound by this assumption.

## Local Postgres contour (current)
- **A-33. Local Postgres durable contour**: with `STORAGE_BACKEND=postgres`, the service writes through `PostgresDiaryStore` (psycopg3 sync + `psycopg_pool.ConnectionPool`) to the Postgres provided by `docker-compose.yml`. Schema is bootstrapped at process start from `src/diary_rag/storage/postgres/schema.sql` via `CREATE TABLE / CREATE INDEX IF NOT EXISTS`; no migration tool is wired. Retrieval reuses the same case-insensitive substring contract as the mock (A-29), now executed against Postgres with `lower(chunk_text) LIKE %s`. Webhook idempotency (R-2) is enforced by `UNIQUE (external_chat_id, external_message_id, edit_seq)` plus `INSERT ... ON CONFLICT DO NOTHING` in `get_or_create_source_message` (D-023). SQLite remains opt-in for offline dev; the canonical durable target is Postgres (D-007 / D-022).

## Schema evolution
- **A-34. Local schema upgrades are destructive**: with no migration tool in place, schema changes that add or alter columns require resetting the local Postgres volume (`docker compose down -v`) before the bootstrap DDL applies cleanly. SQLite picks up the new schema on a fresh DB file. Production schema evolution must be solved before the first non-local deployment; a future packet may introduce Alembic.

## Phase 3.1+3.2 indexing contour (current)
- **A-35. Sync indexing, no auto-retry**: `DiaryService.ingest` calls the `EmbeddingClient` synchronously after `save_event_chunks` commits (D-024). On provider failure the chunks remain persisted, `embedding_status` flips to `failed`, and zero `embedding_records` are written for that source; the ingest result still returns `FallbackMode.NONE` (raw + chunks survived — I-2, I-3). Failed embeddings stay failed; replay (R-2) does not retry. Reconciliation for failed rows is deferred to a future Phase-6 packet that will introduce bounded retries and a dead-letter strategy. The SQL probe `SELECT chunk_id FROM event_chunks WHERE embedding_status='failed'` is the operator inspection surface until then.
*A-36 → D-025 (replaced by A-36b — see below).*

## Phase 3.3 baseline-hybrid contour (current)
- **A-36b. 3072-dim ANN-index strategy remains open**: D-025 ships the dense leg as an exact family-scoped sequential scan over `vector(3072)`, which is correct at current diary scale and requires no schema churn. pgvector's HNSW / IVFFlat still cap at 2000 dim, so when corpus size demands ANN the choice is between `halfvec(3072)` + HNSW (small precision loss) or another approach. External vector DBs remain rejected on I-2 grounds. Revisit in the next quality-decision packet alongside BM25 / reranker / Qdrant evaluation.
- **A-37. Sparse text-search dictionary is `simple`**: the generated `event_chunks.chunk_text_tsv` column uses `to_tsvector('simple', chunk_text)` (D-025). 'simple' avoids stemming and stopword removal — diary content may mix Russian and English, and 'simple' treats both symmetrically without committing to a stemmer that would tokenize one language worse than the other. Multilingual sparse tuning belongs to the next quality-decision packet, not this one.

## Target-state architecture forks (opened by D-027)
- **A-38. Draft lifecycle semantics**: the lifecycle-representation slice is answered by D-028 — `SourceMessage.detected_route` is the lifecycle carrier (extended with `RouteKind.DRAFT`), and `core.routing.lifecycle_for` is the canonical mapping helper. Remaining open: how long an unpromoted draft is retained, whether it expires by inactivity or by explicit cleanup, and which exact user action promotes a draft to a note (a follow-up `/note` referencing it, a UI confirmation, an inline command, etc.). Required before the draft promotion / retention implementation packet.
- **A-39. Raw export packaging and delivery**: D-027 commits the formats (JSON and TXT) and the scope (raw `SourceMessage` rows within the requester's scope); D-029 closes the Telegram-delivery-channel slice (outbound `sendDocument` via multipart upload) and the request-shape slice (synchronous, single-shot — no time-range arguments, no async generation). Remaining open: audit-row schema for export provenance, inclusion of derived state as an optional flag, time-range arguments and async generation when scale demands them, and delivery channels for non-Telegram hosts (HTTP download endpoint, host-app screen). Required before each respective follow-up packet.
- **A-40. Backup tooling and recovery objectives**: D-027 commits the nightly window (`03:00–05:00` target) and a stronger-than-nightly recovery primitive, but does not commit a mechanism. Open: continuous WAL archiving vs streaming replicas vs managed-cloud PITR, retention windows for nightly snapshots, formal RPO/RTO targets per deployment shape, and the restore-drill cadence. Required before the first non-local deployment.
- **A-41. Cloud-first reference environment**: D-027 names managed cloud as the default deployment shape, but does not name which managed environment is the production reference (managed Postgres provider, hosting platform, observability stack). Self-hosted OSS and embedded shapes remain peers and have their own backend choices. Required before the production rollout packet.

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
- A-5 → D-024 (pgvector chosen for dense storage).
- A-7 → D-024 (sync indexing on ingest).
- A-8 → D-024 (`text-embedding-3-large` @ 3072 dim).
- A-6 → D-025 (hybrid merge lives at the service layer via RRF).
- A-29 → D-025 (substring placeholder retired; baseline hybrid retrieval lands).
- A-36 → D-025 (replaced by A-36b; exact family-scoped scan for now, halfvec/HNSW deferred).
