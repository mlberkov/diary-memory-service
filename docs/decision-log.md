# Decision Log

## Status
Canonical decisions accepted as of current repository bootstrap

---

## D-001 — Telegram-first, TheyGrow-later

### Decision
The service will start as a Telegram-based diary and Q&A flow and later be integrated into TheyGrow.

### Why
Telegram minimizes capture friction.
The long-term value lies in a reusable memory service, not in Telegram itself.

### Consequence
Telegram must be treated as a client channel, not as the core product boundary.

---

## D-002 — Standalone Diary Memory Service

### Decision
The architecture will center on a standalone Diary Memory Service.

### Why
This keeps ingestion, storage, retrieval, and answer generation portable across future interfaces.

### Consequence
The core service must be callable from Telegram today and TheyGrow tomorrow.

---

## D-003 — Text-only MVP

### Decision
The MVP supports text messages only.

### Why
This minimizes complexity and validates the core memory loop first.

### Consequence
Voice, image, and video ingestion are deferred.

---

## D-004 — Date-based diary entry format

### Decision
A message beginning with a date is treated as a diary entry.

### Why
This provides a simple and inspectable ingestion rule for MVP.

### Consequence
The parser must be deterministic and versioned.

---

## D-005 — Event-level chunking

### Decision
Each event line after the date becomes a separate chunk.

### Why
This creates fine-grained retrieval units and preserves temporal structure.

### Consequence
The system must also preserve raw message and logical entry lineage.

---

## D-006 — Explicit commands plus heuristic routing

### Decision
The product will support `/entry` and `/ask` as explicit routing commands, while retaining heuristic routing as a convenience layer.

### Why
Heuristic-only routing is too brittle for production use.

### Consequence
Low-confidence routing must ask for clarification rather than silently misclassify.

---

## D-007 — PostgreSQL as durable source of truth

### Decision
PostgreSQL will be the primary durable store.

### Why
It fits future TheyGrow integration, relational metadata handling, and auditability.

### Consequence
Embeddings and indexing are downstream enrichments, not the system of record.

---

## D-008 — Hybrid retrieval required

### Decision
The search layer must support hybrid retrieval.

### Why
Diary questions can depend on both semantic similarity and exact lexical match.

### Consequence
The retrieval backend must be chosen or wrapped so that hybrid search is supported from the beginning.

---

## D-009 — Retrieval backend behind abstraction

### Decision
The search backend must be hidden behind a retrieval interface.

### Why
This avoids tight coupling to one vendor or one storage engine.

### Consequence
The domain and orchestration layers must not depend on backend-specific APIs.

---

## D-010 — OpenAI for embeddings and generation on MVP

### Decision
OpenAI APIs are the initial provider for embeddings and answer generation.

### Why
This optimizes for implementation speed and quality on the first slice.

### Consequence
Provider access must still be wrapped by explicit adapters and config.

---

## D-011 — Framework-light core

### Decision
The main ingestion, retrieval, and answer orchestration flow will be implemented from scratch.

### Why
The system needs explicit contracts, provenance, and migration-friendly behavior.

### Consequence
LangChain may be used only as an optional utility layer.
LangGraph is not part of the MVP foundation.

---

## D-012 — Optional reranking and query rewriting

### Decision
Reranking and query rewriting are planned but not mandatory in the first production slice.

### Why
They may improve quality, but they should be justified by evaluation rather than assumed.

### Consequence
These features must be feature-flagged and added only after the base flow is stable.

---

## D-013 — Grounded answer requirement

### Decision
Every answer must be grounded in retrieved diary evidence.

### Why
Trust depends on provenance and inspectability.

### Consequence
The system must support explicit fallback when evidence is absent or weak.

---

## D-014 — Shared diary must preserve authorship

### Decision
Shared-family mode is supported, but authorship must remain explicit.

### Why
Joint memory without authorship creates ambiguity and future access-control problems.

### Consequence
Author metadata is mandatory at source, entry, and chunk levels.

---

## D-015 — Future TheyGrow integration seam

### Decision
The service must expose boundaries that make future TheyGrow integration cheap.

### Why
The long-term target is reuse, not replacement.

### Consequence
Telegram-specific assumptions must stay isolated in adapter code and not leak into core domain logic.

---

## D-016 — Implementation language: Python 3.11

### Decision
The service is implemented in Python 3.11.

### Why
Python is the working language for the AI/RAG ecosystem (provider SDKs, embedding tooling, evaluation harnesses) and matches the team's existing fluency. 3.11 is recent enough for performance and typing improvements while broadly supported by tooling.

### Consequence
Closes assumption A-1. All tooling, CI, and runtime targets assume CPython 3.11+. A move to a newer minor version is allowed; downgrade requires a new decision.

---

## D-017 — Dependency and environment manager: uv

### Decision
`uv` is the canonical dependency and virtual-environment manager.

### Why
`uv` is fast, deterministic, and consolidates resolver, installer, and venv management in one tool, removing the separate choice between pip-tools, poetry, and venv handling.

### Consequence
Closes assumption A-2. The repo uses a `uv`-managed lockfile. Make targets shell out to `uv` rather than directly to `pip`/`python`. Contributors need only `uv` plus a Python 3.11 interpreter that `uv` can pick up or install.

---

## D-018 — Baseline toolchain: Ruff, Mypy, Pytest

### Decision
The baseline toolchain is:
- **Ruff** — formatter and linter,
- **Mypy** — static type checker,
- **Pytest** — test runner.

`Makefile` exposes `format`, `lint`, `typecheck`, `test`, and `check` (where `check` runs `lint` + `typecheck` + `test`).

### Why
Ruff replaces Black + isort + flake8 with one fast tool. Mypy is the de-facto Python type checker. Pytest is the lowest-friction test runner and is the implicit assumption in the build plan.

### Consequence
Closes assumption A-3. CI gates on `make check`. New code must pass Ruff and Mypy in the configuration agreed in Slice 1.1.

---

## D-020 — Heuristic plain-text routing rules and CLARIFY reply

### Decision
Plain-text Telegram messages (no `/entry` or `/ask` command) are classified by a deterministic in-process function `core.routing.classifier.classify_plain_text` into one of three routes:

- **ENTRY** when the first non-empty line is a valid ISO `YYYY-MM-DD` date *and* the body has at least one event line. Detected by reusing `core.diary.parser.parse_diary_entry` so the ISO-only rule (A-28) lives in one place.
- **ASK** when the text ends with `?` *or* its first whitespace-separated token (lower-cased, trailing punctuation stripped) is in the fixed set `{what, when, who, where, why, how, which, did, do, does, is, are, was, were, can, could, would, should, show, tell, find, list, give, remind}`.
- **CLARIFY** otherwise. The dispatcher answers with a fixed reply naming both `/entry` and `/ask`; nothing is persisted and no route is guessed.

Heuristic-routed ENTRY and ASK replies append a single marker — `(routed as entry — send /entry next time to be explicit)` or `(routed as question — send /ask next time to be explicit)` — so the user can see the heuristic fired (R-6, R-11). Command-routed replies do not carry this marker. Every `InboundMessage` carries `route_source ∈ {"command", "heuristic"}`; the webhook log line records both `route` and `route_source`, and `confidence` for heuristic routes.

The query service performs the smallest normalization needed for substring retrieval to work with terminal punctuation — it strips trailing `?.!,;:` from the payload before passing to the mock store. No semantic expansion, token ranking, or retrieval redesign.

### Why
D-006 says heuristic routing is convenience and low-confidence routing must ask for clarification rather than misclassify. Slice 1.4 needed concrete rules and a clarification UX before the heuristic could ship. Reusing `parse_diary_entry` keeps ISO date semantics in one place; fixing the question-word set keeps the classifier deterministic and inspectable; the explicit marker satisfies R-6 (requested vs effective path) without changing the persisted contract.

### Consequence
Closes assumptions A-16 (routing confidence threshold) and A-17 (clarification fallback UX). Adds A-31 (mock-contour persistence: only ENTRY persists a `SourceMessage` in the in-memory store). Future durable-storage work (Phase 2) revisits per-route persistence on its own merits; this decision does not bind that.

---

## D-019 — Telegram transport: webhook only

### Decision
Telegram is consumed via webhook in MVP and production. Local development also uses webhook, exposed through a tunnel (e.g. `ngrok`, `cloudflared`). Long-polling is not introduced in MVP.

### Why
Two transports double the surface area (state model, idempotency contract, retry semantics). Webhook is the production target per BuildPlan §Phase 1; using the same transport in dev keeps the contract identical end-to-end.

### Consequence
Closes assumption A-4. The Telegram adapter implements only a webhook receiver. Developers configure a tunnel locally; the runbook and quickstart document the setup. R-2 (idempotent ingest on `(telegram_chat_id, telegram_message_id, edit_seq)`) covers webhook retry semantics.

---

## D-021 — Local SQLite as the thinnest dev-only durable seam

### Decision
Local development with `STORAGE_BACKEND=sqlite` writes through `SqliteDiaryStore` (stdlib `sqlite3`) to a single file at `SQLITE_PATH` (default `./data/diary.db`). Schema is bootstrapped at process start via `CREATE TABLE IF NOT EXISTS`; there is no migration tool in this slice. The default backend remains `memory` (`MockDiaryStore`) for unit tests. Services depend on a new `DiaryRepository` Protocol; both the mock and the SQLite store satisfy it structurally.

### Why
The packet that introduced durable persistence wanted the smallest seam that proves data survives an app restart. A full Postgres-via-docker-compose + SQLAlchemy + Alembic slice was deferred to its own packet so this change stays inspectable and reversible. Routing the services through a Protocol means the Postgres replacement is a single-file swap with no service-layer churn.

### Consequence
Does not displace D-007: PostgreSQL remains the canonical durable source of truth. SQLite is a dev-only transient choice; the next durable-persistence packet replaces `SqliteDiaryStore` with a Postgres-backed implementation behind the same Protocol. Closes nothing in `docs/assumptions.md`; opens A-32 (local SQLite contour). Webhook idempotency (R-2), edit/delete (I-13), parser versioning, and per-record status columns remain out of scope and are unchanged by this packet.

---

## D-022 — Local PostgreSQL as the canonical durable backend behind `DiaryRepository`

### Decision
`STORAGE_BACKEND=postgres` writes through `PostgresDiaryStore` (psycopg3 sync + `psycopg_pool.ConnectionPool`) to a local Postgres provided by `docker-compose.yml`. Schema is bootstrapped at process start by executing `src/diary_rag/storage/postgres/schema.sql` (CREATE TABLE / CREATE INDEX IF NOT EXISTS) loaded via `importlib.resources`. Default backend stays `memory`; `SqliteDiaryStore` remains available as opt-in.

### Why
D-007 names PostgreSQL the canonical durable system of record; D-021 admitted SQLite only as the thinnest dev-only seam. This packet replaces the SQLite durable path with the canonical one behind the same `DiaryRepository` Protocol. No service-layer churn; a single bootstrap file is the smallest change that proves I-2 in a real Postgres.

### Consequence
Closes A-32 (SQLite contour). A-10 (edit/delete), R-2 (idempotent ingest), parser versioning, per-record status columns, embeddings, hybrid retrieval, and any migration tool (e.g. Alembic) remain out of scope and are unchanged. Retrieval semantics are still case-insensitive substring (A-29).

---

## D-023 — Webhook + ingest idempotency keyed on `(external_chat_id, external_message_id, edit_seq)`

### Decision
Repeated delivery of the same Telegram message-state must produce no new persisted state (R-2). The idempotency key is the triple `(external_chat_id, external_message_id, edit_seq)`, where:

- `external_message_id` is `message.message_id` from the Telegram update,
- `edit_seq` is `0` when `edit_date` is absent and `edit_date` (epoch seconds) when present.

Each backend enforces the key via DB-native conflict handling on the `source_messages` table: `UNIQUE (external_chat_id, external_message_id, edit_seq)` plus `INSERT ... ON CONFLICT DO NOTHING` (Postgres) / `INSERT OR IGNORE` (SQLite); `MockDiaryStore` keeps a side index keyed on the same triple. The unique constraint is part of the correctness model, not a safety net layered over a SELECT-then-INSERT race.

`DiaryRepository.get_or_create_source_message(source) -> tuple[SourceMessage, bool]` is the single ingest seam; the boolean is `True` on replay and the returned `SourceMessage` is the row that was already persisted. `DiaryService.ingest` short-circuits parse and chunking on replay and reconstructs the original `IngestResult` from persisted state (`get_diary_entry_by_source_message_id`, `count_event_chunks_for_source`). The webhook returns the same functional `sendMessage` reply on every replay and logs `effective_path=fresh|replay` (R-6 parallel for the ingest path). `QueryService.answer` remains side-effect-free / idempotent-by-default; no code change there.

There is no migration tooling in this packet. Existing local Postgres volumes that pre-date the new columns must be reset (drop the `diary_pg_data` volume) before the new `schema.sql` applies cleanly. SQLite picks up the schema on a fresh DB file. A separate packet may introduce Alembic; this one does not.

### Why
R-2 has been a documented runtime invariant since the toolchain bootstrapped, but it was unenforced — Telegram retries (or any double-POST of the same `update_id`) duplicated `SourceMessage`, `DiaryEntry`, and `EventChunk` rows. D-022 explicitly left R-2 open. The triple `(external_chat_id, external_message_id, edit_seq)` is what the invariant text already names; using `edit_date` as `edit_seq` distinguishes original messages from each edit-state without introducing a DB-managed revision counter (true edit-history semantics remain A-10 / Phase 2.5). DB-native conflict handling is the only correct primary path for an idempotency key — SELECT-then-INSERT races, even in single-process dev, would let the unique constraint surface as an unhandled exception rather than a clean "replay" branch.

### Consequence
- Closes A-30 (mock non-idempotent state).
- Updates A-33 (Postgres contour): R-2 is now enforced under `STORAGE_BACKEND=postgres`.
- Refines R-2 wording in `RUNTIME-INVARIANTS.md` to name the key composition explicitly.
- Adds `external_message_id` and `edit_seq` to TechSpec §5 `SourceMessage` (and to `core/diary/models.SourceMessage`, `core/routing/models.InboundMessage`).
- Opens a new operational note: schema evolution before production needs a real migration story (see `docs/todo.md`); local dev upgrades are destructive (drop volume) until then.
- Out of scope (unchanged): A-10 (edit content semantics — only the *key* dimension is committed here), embeddings (A-5/A-6/A-7/A-8), `/health` boot gates beyond what already exists (R-10), AnswerTrace persistence (Phase 4), per-record stage status columns (Phase 2.6).

---

## D-024 — Quality-first Phase 3.1+3.2 contour: pgvector + `text-embedding-3-large` (3072 dim, f32) + sync indexing on ingest

### Decision
Phase 3.1 (embedding adapter) and Phase 3.2 (indexing pipeline) ship as a single packet under a fixed quality-first contour:

- **Dense vector storage:** pgvector. Local Postgres runs the `pgvector/pgvector:pg16` image; `embedding_records.embedding` is `vector(3072)` at full f32 precision. SQLite stores the same payload as a little-endian f32 `BLOB` for the opt-in dev backend; the mock holds `list[float]` in memory.
- **Embedding model:** `text-embedding-3-large` at **3072 dimensions**. The OpenAI request passes `dimensions=3072` explicitly even though it is the native default — the request contract is self-documenting.
- **Indexing path:** synchronous, inline after `save_event_chunks`. No async queue, no background worker.
- **Provider seam:** `EmbeddingClient` Protocol in `core/embeddings`; concrete adapters live in `adapters/embeddings` (Invariant I-11). The mock client is honestly named `model_name="mock"` — provider provenance in persisted rows and logs must stay observably distinct from production even though the dimension is the same (3072).
- **Per-chunk state:** `event_chunks.embedding_status ∈ {pending, ready, failed}` lands now (the only Slice 2.6 status column added by this packet). Status is observable by plain SQL inspection.
- **Failure semantics:** any exception in the embedding step leaves chunks intact and flips their status to `failed`; zero `embedding_records` are written for that source; the ingest result stays `FallbackMode.NONE` (raw + chunks survived — I-2, I-3); the failure is logged with provider / model / chunk count / exception class. No retry. No dead-letter. Failed chunks become inputs for a future Phase-6 reconciliation job (A-35).
- **Replay (R-2 / D-023) extension:** replay short-circuits before the embedding step, so a previously-failed embedding stays failed on replay. Retry-on-replay is explicitly out of scope.
- **Boot gate (R-10 partial):** `create_app` asserts `settings.embedding_dimension == 3072` (the canonical pgvector column dimension), and when `embedding_backend == "openai"` it also asserts `settings.embedding_model == "text-embedding-3-large"`; when `storage_backend == "postgres"` it probes `pg_extension` to confirm pgvector is installed. Mismatch aborts boot rather than serving partial functionality.
- **Service wiring:** `DiaryService.__init__` gains an optional `embedding_client: EmbeddingClient`; `build_embedding_client(settings)` is the single factory used by both the boot gate and the webhook dispatcher so the two paths cannot disagree.

### Why
D-007 names PostgreSQL as the durable system of record; the Phase-3 BuildPlan entry requires a dense+sparse-capable retrieval seam before grounded answers can land. This packet stands up the *ingest half* of that seam — every committed chunk gets an embedding row keyed on `(chunk_id, model_name)` — without committing to the read path. The full-precision `vector(3072)` keeps every downstream ANN choice open (exact scan, halfvec + HNSW, or other) for the Phase-3.3 retrieval packet; pgvector caps HNSW / IVFFlat at 2000 dim, so the 3072-dim ANN strategy is a separate decision (A-36).

Quality-first is an explicit founder choice: per-token cost for `text-embedding-3-large` is ~6.5× `text-embedding-3-small` and per-vector storage is ~12 KB at f32, but the lift in retrieval quality is worth the cost for a diary-scale corpus. The mock client deliberately reports `model_name="mock"` rather than mirroring production, so SQL inspection alone tells the operator which rows came from which provider.

### Consequence
- Closes A-5 (pgvector chosen for dense storage), A-7 (sync indexing on ingest), A-8 (`text-embedding-3-large` @ 3072).
- Opens **A-35** (sync indexing, no auto-retry: failed embeddings stay failed until a future Phase-6 reconciliation job) and **A-36** (3072-dim ANN-index strategy for Phase 3.3: pgvector's HNSW / IVFFlat cap at 2000 dim, so the read path will pick among exact scan, `halfvec(3072)` + HNSW, or other when 3.3 lands).
- Refines R-10 wording in `docs/RUNTIME-INVARIANTS.md` to name the boot-time dimension and pgvector-presence checks.
- Adds `EmbeddingStatus` to TechSpec §5 (on `EventChunk`); `EmbeddingRecord` materialised against the field set already listed there.
- Docker image swap (`postgres:16-alpine` → `pgvector/pgvector:pg16`) plus the new table / new column means existing local volumes must be reset (`docker compose down -v`) before the bootstrap DDL applies — same destructive-upgrade contour as D-022 / D-023 (A-34 unchanged).
- New runtime dependencies: `openai` (official SDK), `pgvector` (psycopg integration package).
- Out of scope (unchanged): Phase 3.3 hybrid retrieval / `SearchRepository` / sparse FTS / 3072-dim ANN index, Phase 3.4 metadata filters, Phase 3.5 retrieval traces, Phase 6 provider hardening (timeouts, retries, dead-letter), AnswerTrace persistence (Phase 4), schema migrations (A-34), `parse_status` / `index_status` columns (Slice 2.6), edit-content semantics (A-10).

---

## D-025 — Slice 3.3 baseline hybrid retrieval: exact dense scan + Postgres FTS (`simple`) + service-layer RRF

### Decision
Phase 3.3 ships as the **baseline hybrid retrieval** packet, not the final-form search-quality packet. It replaces the case-insensitive substring placeholder (A-29) with one canonical hybrid path on Postgres:

- **Retrieval seam.** New `SearchRepository` Protocol (`src/diary_rag/storage/search_repository.py`) with two methods, `dense_candidates(family_id, query_embedding, model_name, limit) -> list[EventChunk]` and `sparse_candidates(family_id, query_text, limit) -> list[EventChunk]`. The three concrete stores (mock, sqlite, postgres) each satisfy both `DiaryRepository` and `SearchRepository`; the combined `HybridDiaryStore` Protocol names the union for static typing.
- **Dense.** Exact family-scoped sequential scan over the canonical `vector(3072)` column, ordered by `embedding <=> %s::vector` (cosine distance), filtered to `event_chunks.embedding_status='ready'` and the active `embedding_records.model_name`. No halfvec, no HNSW, no ANN migration. A-36 becomes **A-36b** — halfvec/HNSW remains the open question for a future quality-decision packet driven by scale.
- **Sparse.** Generated stored column `event_chunks.chunk_text_tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', chunk_text)) STORED` plus a GIN index. Queries use `websearch_to_tsquery('simple', $q)` and order by `ts_rank_cd`. The `simple` dictionary avoids a language commitment because diary content may mix Russian and English. **BM25 is explicitly not in this packet.**
- **Fusion.** Reciprocal Rank Fusion in the service layer (`src/diary_rag/services/retrieval.py`), `k=60`. Pure function over rank positions; score calibration between cosine distance and `ts_rank` is the bug RRF was designed to avoid. **No reranker, no learned weights, no cross-encoder.**
- **Backends.** Postgres is the only canonical retrieval backend. `SqliteDiaryStore.dense_candidates` / `sparse_candidates` raise `NotImplementedError("sqlite hybrid retrieval not supported; postgres is the canonical retrieval backend (D-022, D-025)")`. `Dispatcher` catches that and returns `FallbackMode.NO_EVIDENCE` with a `retrieval.unavailable` log line. The mock backend is deterministic and useful for unit tests: sparse via lowercased whitespace token-overlap, dense via cosine over the deterministic `MockEmbeddingClient` vectors with a 0.5 distance threshold so unrelated queries don't fabricate matches.
- **Cut-over.** Clean. `search_chunks` is removed from `DiaryRepository` and all three implementations. No `retrieval_mode` setting. No temporary fallback branch. The dispatcher reply trailer changes from `(mock retrieval — substring match)` to `(hybrid retrieval — dense+sparse RRF)`; the no-evidence reply drops the `(no_evidence — mock retrieval only.)` parenthetical.
- **Service wiring.** `QueryService.__init__` now requires both a `SearchRepository` and an `EmbeddingClient`; it computes one query embedding per call, runs both legs, RRF-merges, and logs `retrieval.hybrid family_id=… model=… dense_n=… sparse_n=… merged_n=…` so an operator can confirm both legs ran. Two new `Settings` knobs: `retrieval_top_k` (default 5) and `retrieval_candidate_k` (default 20).
- **Read primitive.** `DiaryRepository.get_event_chunk(chunk_id)` is added as the small chunk-by-id read that supports inspection and test assertions after `search_chunks` is removed.

### Why
D-024 stood up the ingest half of the retrieval seam — every committed chunk has a `vector(3072)` row — but `QueryService` still ran substring `LIKE`. Persisted embeddings did not participate in retrieval and the system was not evaluable. Slice 3.3 closes that loop with the simplest canonical path that respects the I-8 hybrid mandate, retires A-29, and makes the system measurable. BM25, rerankers, and external vector/search systems (Qdrant et al.) are deliberately deferred to the next quality-decision packet so we have a baseline to compare against before paying their complexity cost. Score calibration is the well-known failure mode RRF was designed to avoid; doing anything more is premature optimisation at this scale.

The 3072-dim ANN strategy is left open (A-36b) on purpose: an exact family-scoped scan is correct at diary scale and demands no schema churn, while halfvec/HNSW would be a separate migration with its own precision tradeoff, properly evaluated when corpus size demands it. The `simple` text-search dictionary is the smallest sparse commitment that does not bias against any one language; future multilingual tuning is a follow-up.

### Consequence
- Closes A-6 (hybrid merge location: service-layer RRF) and A-29 (substring placeholder retired).
- Replaces A-36 with **A-36b** — 3072-dim ANN strategy (halfvec / HNSW / other) is deferred to the next quality-decision packet, driven by scale rather than this slice.
- I-8 is now enforced in code, not just declared. `docs/INVARIANTS.md` updated in place.
- Adds `event_chunks.chunk_text_tsv` (generated, stored) plus `idx_event_chunks_chunk_text_tsv` GIN index to `schema.sql`. No migration tool yet (A-34 unchanged); operators upgrading a local volume add the column via `ALTER TABLE … ADD COLUMN IF NOT EXISTS … GENERATED ALWAYS AS (to_tsvector('simple', chunk_text)) STORED;` plus the matching index, or reset the volume.
- Adds `DiaryRepository.get_event_chunk(chunk_id)`. Removes `DiaryRepository.search_chunks` and the substring SQL in mock / sqlite / postgres.
- New runtime dependencies: none. Existing pgvector / psycopg already satisfy the read path.
- New `Settings` knobs: `retrieval_top_k`, `retrieval_candidate_k`. These are tuning placeholders, not quality claims.
- Dispatcher reply text changes; the e2e smoke tests and any external documentation that quoted the old trailer were updated in the same packet.
- Out of scope (unchanged or deferred): **BM25**, **reranker / cross-encoder**, **Qdrant or any external vector/search system**, **halfvec / HNSW migration** (A-36b), Phase 3.4 metadata filters (visibility / child / date), Phase 3.5 retrieval-trace persistence (`RetrievalHit` rows), Phase 4 AnswerTrace persistence, Phase 5 query rewriting / answer modes, Phase 6 provider hardening (A-35 unchanged), multilingual sparse tuning beyond `simple`, query-embedding caching, migration tooling (A-34 unchanged), edit-content semantics (A-10).

---

## D-026 — Portable memory core, many hosts

### Decision
The repository is a **portable memory/journal core**. The functional core — raw capture, parsing, line-level chunking, embedding, hybrid retrieval, grounded answering, provenance — is one consistent subsystem regardless of which system embeds it. Hosts and integrations vary along five adapter axes, each with a single explicit seam:

1. **Event source** — Telegram webhook today; HTTP API, embedded SDK call, CLI, or web form later.
2. **Control surface** — `/entry` and `/ask` in Telegram; UI buttons, endpoints, or app screens in other hosts.
3. **Storage / infrastructure** — `DiaryRepository` and `SearchRepository` Protocols (mock, SQLite dev, local Postgres + pgvector, managed Postgres, or a host's existing database when embedded).
4. **Embedding / LLM providers** — `EmbeddingClient`, `ChatClient` (OpenAI today; self-hosted, on-prem, host-provided gateways, or mocks elsewhere).
5. **Tenant / auth mapping** — host identity (Telegram chat, TheyGrow workspace, OSS single-tenant default) mapped onto the core's opaque scope.

Self-hosted OSS, managed cloud, and embedded-in-TheyGrow are first-class deployment shapes. Telegram is one event-source adapter today; TheyGrow is one future host. The current parents / family / child framing is the **first use case** of the core, not its definition. Journal/topic semantics in the core stay generic; use-case-specific identifiers (`family_id`, child) are carried as opaque scope, not encoded in core types or behavior.

### Why
D-001 (Telegram-first, TheyGrow-later) and D-015 (TheyGrow integration seam) name two specific hosts and one specific migration. As more deployment shapes become realistic (OSS self-host, managed cloud, library embedding), framing the architecture around Telegram-vs-TheyGrow risks encoding host-specific assumptions into the core and use-case vocabulary into types and schemas. This decision generalizes D-001 and D-015 into a single rule with named adapter axes, so future packets evaluate changes against one principle rather than ad-hoc Telegram/TheyGrow comparisons. It also names a drift that already exists (`family_id`, `DiaryEntry`, "family diary" framing) and bounds it: existing names persist; new core code adopts the neutral form; an explicit renaming packet may revisit the existing names later on its own merits.

### Consequence
- Generalizes D-001 and D-015. Both remain valid as specific host instances of the rule; they are not retired.
- New core code does not introduce use-case vocabulary (`family`, `child`, `parent`, "diary" as a type name) where a generic name fits. Existing names — including `family_id` in `event_chunks`, `DiaryRepository`, `DiaryEntry`, and the `diary_rag` package — are out of scope of this decision and continue to mean what they mean. An explicit renaming packet may revisit them.
- No transport types, provider SDKs, raw SQL, or host-runtime assumptions (HTTP-shaped, Telegram-shaped, single-tenant, internet-connected, English-only) appear in core code. This restates and extends I-1 and I-11.
- Future packets must classify their changes as **core**, **adapter**, or **config** in the packet description. Changes that cross axes name the seams they touch.
- `docs/ARCHITECTURE.md` updated in place with the portability principle, adapter axes, and boundary-rule extension.
- `docs/product/PRD.md` and `docs/product/BuildPlan.md` reframed so the parents / family-diary use case is named as the first use case of a generic memory core, not its definition. No product scope change.
- `AGENTS.md` and `CLAUDE.md` gain the core/adapter/config classification rule for future packets.
- No code changes, no schema changes, no new dependencies, no roadmap commitment in this packet. Concrete renames, multi-tenant schema work, new event-source adapters, and a managed-cloud or OSS-distribution story are each separate packets, opened on their own merits when needed.
- Out of scope (unchanged): all open assumptions (A-10, A-34, A-35, A-36b), Phase 3.4+ work, AnswerTrace persistence (Phase 4), Phase 5 query rewriting, Phase 6 provider hardening, Phase 8 privacy/visibility model, Phase 9 TheyGrow integration seam.

---

## D-027 — Target-state architecture extensions: draft-by-default routing, raw-data durability and export, cloud-first deployment

### Decision

The target-state architecture extends D-026 with four behavioral commitments that bind future implementation packets. None of them changes code, schema, or names in this packet; each is a directional rule that future implementation packets implement on their own merits.

1. **Draft-by-default safety (control surface).** Inbound messages enter one of three lifecycle states — **draft**, **note**, or **query**. The user-facing control surface offers three explicit commands:
   - `/note` — canonical note. Triggers the full ingestion pipeline (parse → chunk → embed → index).
   - `/draft` — explicit draft. Persisted as raw `SourceMessage` only; no parse, chunk, embed, or index.
   - `/ask` — query / retrieval.
   - **Absence of an explicit command** is treated as **draft**. Heuristics may layer suggestions on top, but MUST NOT override the draft floor: no path silently discards an inbound message. CLARIFY (D-020) remains valid for cases where heuristics actively conflict with intent; the new floor is "raw always persists" regardless of routing confidence.
   A draft may later be promoted to a note via an explicit user action; promotion is replayable from the persisted raw text (I-12). Specific draft retention, expiry, and promotion mechanics are bracketed as A-38.

2. **Raw-data durability with a daily backup window and stronger-than-nightly recovery.** Raw `SourceMessage` is the system's highest-tier durability surface (I-2, I-3). The target contour requires:
   - a scheduled nightly backup window (target: `03:00–05:00` local time) covering at minimum `source_messages` plus enough relational scaffolding to restore the `SourceMessage → DiaryEntry → EventChunk` lineage,
   - recovery to a point closer to failure than the last nightly snapshot (the mechanism — continuous WAL archiving, PITR, replicas, or a managed-cloud equivalent — is selected per deployment shape),
   - operational policies (retention windows, restore drills) that treat raw retention as the highest tier.
   Derived state (embeddings, indexes, traces) remains reproducible by replay from raw under the active parser/embedding versions. Specific tooling and RPO/RTO targets are bracketed as A-40.

3. **Raw export on demand in JSON or TXT.** The user must be able to export their raw data on demand, in either JSON (stable field names, ISO timestamps) or TXT (one record per block). The export is scope-bounded (R-3) and self-describing (records its own export id, scope, time range, format, requester). Derived state is not in the minimum export contract — raw is sufficient to reconstruct everything else. Per-host delivery channels and the request shape are bracketed as A-39.

4. **Cloud-first deployment as the default shape.** The reference deployment shape is **managed cloud** (managed Postgres, scheduled backups, provider gateways). Self-hosted OSS and embedded-in-host (TheyGrow today as the named first-class case) remain first-class peer shapes — same core, different adapter configurations. None of the three is a rewrite path of the others. The specific managed environment that is the production reference is bracketed as A-41.

### Why

These commitments capture target-state requirements that were implicit or absent in canonical docs:

- D-006 named explicit commands plus heuristic routing, and D-020 named CLARIFY as the safety move for ambiguous plain text. As the system moves toward richer use cases and valuable personal information is being captured, the safety floor for ambiguous input changes from "ask to clarify, drop the message" to "preserve as draft", because absence of an explicit command must never cause silent loss of user data.
- D-007 made PostgreSQL the durable system of record, and D-022 stood up a local Postgres backend, but durability beyond "raw committed before enrichment" (I-3) was unspecified. Daily backup plus stronger-than-nightly recovery plus raw export make raw durability auditable end-to-end.
- D-026 named OSS / managed cloud / embedded as first-class deployment shapes without ranking them. Naming managed cloud as the **default** shape resolves which configuration is the production reference; OSS and embedded remain peers, not derivatives.

The behaviors above are directional commitments. Mechanisms — heuristic semantics under the draft floor, draft retention, backup tooling, RPO/RTO, export delivery channel, the specific managed environment — are bracketed as open assumptions and decided by their respective implementation packets.

### Consequence

- Extends D-026 with four behavioral target-state commitments. D-026 remains the portability rule; D-027 names the behaviors the portable core must support.
- Generalizes D-006 / D-020: the safety floor for ambiguous input is **preserve as draft**, not **clarify and drop**. D-020's CLARIFY UX remains valid for cases where the heuristic actively conflicts with intent.
- Sharpens A-20 (export/delete semantics — export half directionally answered), A-22 (hosting target — managed cloud as default), A-23 (backup strategy — daily window plus stronger recovery).
- Opens new assumptions: **A-38** (draft lifecycle semantics), **A-39** (raw export packaging and delivery), **A-40** (backup tooling and recovery objectives), **A-41** (cloud-first reference environment).
- `docs/ARCHITECTURE.md` updated in place with the message-lifecycle, durability/backup/recovery, and raw-export sections, deployment-shapes naming, and a one-page-view diagram refresh to target-state command names.
- `docs/product/PRD.md` updated to reflect target-state control surface, an added user job (Job 5 — Own my data), expanded product principles (draft-by-default, durability, raw export, generic topic model), in-scope target-state additions, and the integration-direction ranking.
- `docs/product/BuildPlan.md` updated for consistency: target-state shape called out next to Goal; Phase 8 wording now covers raw export and backup/recovery; Phase 9 renamed "Host Integration Seams" with TheyGrow named as one first-class case among peers.
- No code changes, no schema changes, no naming-alignment changes in this packet. Implementing `/note`, `/draft`, the no-command-→-draft default, the export endpoint, the backup/recovery contour, and the cloud-first deployment are each separate implementation packets opened on their own merits. The renaming of the existing `/entry` command to `/note` is part of the broader naming-alignment packet (D-026).
- Out of scope (unchanged): all prior open assumptions (A-9, A-10, A-11, A-12, A-13, A-14, A-15, A-18, A-19, A-21, A-24, A-25, A-26, A-28, A-31, A-33, A-34, A-35, A-36b, A-37); Phase 3.4+ retrieval refinements; Phase 4 grounded-answer pipeline; Phase 5 query rewriting / answer modes; Phase 6 provider hardening; Phase 8 visibility-model implementation; Phase 9 host-integration mechanics; TechSpec.md, INVARIANTS.md, RUNTIME-INVARIANTS.md, RUNBOOK.md, assumption-audit.md (each carries its own follow-up alignment when the corresponding implementation packet lands).

---

## D-028 — Draft-by-default routing floor: `/draft` + no-command-→-draft, lifecycle carried by `detected_route`

### Decision
The first implementation packet after D-027 lands the no-silent-loss floor in code with the smallest safe surface change:

- **Command surface (adapter).** The Telegram adapter adds `/draft` to `COMMAND_TOKENS` (`src/diary_rag/adapters/telegram/commands.py`). `/start`, `/help`, `/entry`, and `/ask` are unchanged. The `/entry` → `/note` rename remains the separate naming-alignment packet (D-026).
- **Heuristic routing (core).** `classify_plain_text` (`src/diary_rag/core/routing/classifier.py`) keeps its high-confidence ENTRY and ASK rules unchanged but routes every other non-empty plain-text message to `RouteKind.DRAFT` (reason `draft_floor_no_signal`). `CLARIFY` only remains as the empty/whitespace branch; the webhook short-circuits empty text before the classifier runs, so CLARIFY is effectively dormant under R-13.
- **Lifecycle representation (core, smallest seam).** `RouteKind` gains a `DRAFT` value and a `lifecycle_for(route)` helper maps `ENTRY → "note"`, `ASK → "query"`, `DRAFT → "draft"`, everything else → `"other"`. The persisted carrier is the existing `SourceMessage.detected_route` column — no new column, no migration. The lifecycle vocabulary is named in code (`Literal["draft","note","query","other"]`) without renaming the underlying route values; the `entry`-vs-`note` naming mismatch is bracketed for the naming-alignment packet (A-38 narrowed accordingly).
- **Persistence (core).** `DiaryService.ingest` handles `RouteKind.DRAFT` by committing the raw `SourceMessage` via `get_or_create_source_message` and returning an `IngestResult` with `fallback=NONE`, `entry_date=None`, `events_count=0`. No parse, no chunk, no embed, no index. The replay path (`_reconstruct_result`) branches on the persisted `detected_route`: drafts return the same `IngestResult` shape on replay; notes look up the `DiaryEntry` as before. R-2 holds for drafts because the idempotency key path is unchanged.
- **Dispatcher (core).** The `DRAFT` branch delegates to `DiaryService.ingest` and replies `Stored as draft[ (replay)]. Send /entry <YYYY-MM-DD> on the first line to commit it as a note, or /ask to query.` No heuristic marker is appended for no-command-default DRAFT — the draft floor is unconditional, so there is no requested-vs-effective divergence to surface (R-6 does not apply). The CLARIFY route handler is preserved but no plain-text path reaches it under the new classifier rules.
- **Schema (adapter).** Postgres `source_messages.detected_route` CHECK constraint extends from `{start, help, entry, ask, clarify, unknown}` to `{start, help, entry, ask, draft, clarify, unknown}` in `src/diary_rag/storage/postgres/schema.sql`. SQLite has no enum constraint on the column. The mock backend has no type-level constraint. Per A-34, existing local Postgres volumes that pre-date this packet must be reset (`docker compose down -v`) before the new CHECK applies; the test fixture truncates but cannot rewrite the constraint, so the Postgres integration tests added for drafts will pass after the next volume reset.
- **Observability (adapter).** The webhook log line gains a `lifecycle=draft|note|query|other` field derived from `lifecycle_for(result.route)`. `DiaryService` logs `draft.persisted source_message_id=… family_id=… effective_path=fresh|replay` when the draft path is taken.
- **Out of scope (unchanged).** `/entry` → `/note` rename; draft retention, expiry, and promotion mechanics; raw export; backup/recovery tooling; tenancy generalization; schema migration tooling.

### Why
D-027 committed the draft-by-default safety floor and named the absence of an explicit command as a draft trigger so no inbound message is silently discarded. That commitment was a directional rule with no code change. This packet enforces it in real code with the smallest seam that respects D-026: a single new `RouteKind` value, one new command token, one new branch in the classifier, one new branch in `DiaryService.ingest`, one new dispatcher branch, and one extended CHECK. The lifecycle representation question opened by A-38 admits the cheapest answer here — the existing `detected_route` column already serves as the carrier; introducing a parallel `lifecycle` column would have meant a destructive schema upgrade for every backend without any new behavior to justify it.

The `Literal["draft","note","query","other"]` vocabulary lets the rest of the code refer to lifecycle states without committing to a rename of `RouteKind.ENTRY` → `NOTE`. That keeps the naming-alignment packet (D-026) cleanly separable.

### Consequence
- Closes the lifecycle-representation slice of **A-38**: `SourceMessage.detected_route` is the lifecycle carrier; no new column. The retention / expiry / promotion mechanics remain open under the same assumption.
- I-14 / R-11 / R-13 are now enforced in code, not just declared in docs.
- `core.routing.RouteKind` adds `DRAFT`; `core.routing.lifecycle_for` is the canonical mapping helper; `core.routing.Lifecycle` is the `Literal` alias.
- The Telegram adapter exposes `/draft` and routes no-command text to `RouteKind.DRAFT`. The dispatcher reply text changes for help / start / unknown to name `/draft`.
- `source_messages.detected_route` CHECK extended; A-34 destructive-upgrade discipline applies to existing local Postgres volumes.
- Webhook log line gains `lifecycle=…`; `DiaryService` emits `draft.persisted` on the draft path.
- Out of scope (unchanged or deferred): A-38 retention/expiry/promotion mechanics, A-39 export packaging, A-40 backup tooling, A-41 cloud-first reference environment, `/entry` → `/note` rename (naming-alignment packet under D-026), raw export endpoint, schema migration tooling, multi-tenancy generalization, AnswerTrace persistence, retrieval refinements (Phase 3.4+).

---

## D-029 — Raw export (minimal first slice): synchronous, family-scoped, JSON/TXT via Telegram `sendDocument`

### Decision
The first implementation packet after D-028 lands the raw-export slice of D-027 with the smallest safe surface that proves I-15 end-to-end on the Telegram adapter:

- **Command surface (adapter).** The Telegram adapter adds `/export` to `COMMAND_TOKENS` (`src/diary_rag/adapters/telegram/commands.py`). Existing tokens are unchanged. The argument is parsed from the existing payload — `json` or `txt`; anything else (including the empty arg) returns a fixed usage reply and does not generate or deliver a document.
- **Repository seam (core / storage).** `DiaryRepository` gains `list_source_messages(family_id: str, *, limit: int | None = None) -> list[SourceMessage]` ordered `(created_at ASC, source_message_id ASC)`. `MockDiaryStore` and `PostgresDiaryStore` implement it; `SqliteDiaryStore` raises `NotImplementedError("sqlite raw export not supported; postgres is the canonical durable backend (D-022, D-029)")` matching the D-025 style. No new schema, no new index — the existing `source_messages.family_id` column is sufficient at diary scale.
- **Core service.** New `src/diary_rag/services/export_service.py` adds `ExportService.export(*, family_id, requester_user_id, format)` returning a channel-neutral `ExportPayload` (bytes, filename, media_type, format, record_count, generated_at, family_id, requester_user_id). `core/export/serializers.py` provides pure `serialize_json` / `serialize_txt` functions; each emits an inline provenance envelope (JSON top-level `export` object, TXT `#`-prefixed header) with `schema_version=1`. No provider SDK, no host identifier, no use-case vocabulary in any new type.
- **Dispatcher (core).** `Dispatcher.__init__` gains a required `export: ExportService` argument. The new `RouteKind.EXPORT` branch parses `json|txt`, calls `ExportService.export`, and returns a `DispatchResult` that carries the bytes via the new optional `DispatchResult.document: ExportPayload | None` field. Invalid/missing arg returns text-only with `fallback=invalid_input`. `lifecycle_for(EXPORT)` returns `"other"` without code change.
- **Outbound delivery (adapter).** A new `TelegramClient` Protocol (`src/diary_rag/adapters/telegram/client.py`) names the outbound surface; `HttpxTelegramClient` performs the multipart `sendDocument` POST to `https://api.telegram.org/bot<token>/sendDocument`. The webhook handler is now FastAPI-injected with a `TelegramClient` (factory `get_telegram_client` mirrors `get_dispatcher`). When `result.document is not None` it calls `send_document`, returns `{}` on success, and logs `export.delivered`; on outbound exception it returns a `sendMessage` error reply and logs `export.delivery_failed` with the exception class.
- **Persistence.** No export-audit row is persisted. No `source_messages` schema or CHECK change (export does not insert any new `detected_route` value).
- **Observability.** `ExportService` logs `export.ok family_id=… format=… count=… bytes=…`. Dispatcher logs `export.usage_error chat_id=… payload=…` on invalid arg. Webhook logs `export.delivered` / `export.delivery_failed`. The existing `telegram.webhook` log line is unchanged; `lifecycle=other` is the natural value for `EXPORT`.
- **Dependencies.** `httpx` moves from dev-only to a runtime dependency in `pyproject.toml`; it is the canonical Python multipart-capable HTTP client and was already transitively present via FastAPI's `TestClient`.

### Why
D-027 committed raw export on demand in JSON or TXT (scope-bounded) as a directional rule, and I-15 already names raw durability and export as the highest-tier surface. D-028 landed the draft-by-default companion. This packet enforces the export half on the Telegram adapter with the smallest seams that work: one new repository method, one new core type cluster (`ExportFormat` / `ExportPayload` / serializers / service), one new optional field on `DispatchResult`, one new outbound HTTP surface in the Telegram adapter. Synchronous single-shot is the minimum that delivers the user-facing capability; async generation, time-range arguments, an audit row, and HTTP / host-app delivery channels remain real questions answered by future packets on their own merits.

A `TelegramClient` outbound seam is unavoidable: the Telegram webhook response body supports `sendDocument` only with a `file_id` or URL, not a binary upload; a freshly-generated raw export requires multipart/form-data. Naming the seam as a Protocol keeps the webhook handler transport-agnostic and lets tests inject a recording fake.

### Consequence
- Closes the Telegram-delivery-channel slice of **A-39** (delivery channel for the Telegram adapter is outbound `sendDocument` via multipart) and the request-shape slice (synchronous, single-shot). Remaining open under A-39: audit-row schema for export provenance, inclusion of derived state as an optional flag, time-range arguments, and delivery channels for non-Telegram hosts (HTTP download, host-app screen).
- I-15 is now enforced in code on the Telegram adapter, not just declared in docs.
- New: `src/diary_rag/core/export/{models,serializers}.py`, `src/diary_rag/services/export_service.py`, `src/diary_rag/adapters/telegram/client.py`, plus four test files (`tests/test_export_serializers.py`, `tests/test_export_service.py`, `tests/test_storage_list_source_messages.py`, `tests/test_telegram_export.py`).
- Changed: `core/routing/models.py` adds `RouteKind.EXPORT` and `DispatchResult.document`; `services/dispatcher.py` adds `ExportService` dependency and the EXPORT branch; `services/__init__.py` exports `ExportService`; `storage/repository.py` extends the Protocol; `storage/mock/store.py` and `storage/postgres/store.py` implement `list_source_messages`; `storage/sqlite/store.py` raises `NotImplementedError`; `adapters/telegram/commands.py` adds `/export`; `adapters/telegram/webhook.py` injects `TelegramClient` and branches on `result.document`. Existing tests that construct a real `Dispatcher` updated to pass `ExportService(...)` as the third argument.
- New runtime dependency: `httpx>=0.27,<0.28` (promoted from dev-only).
- No schema changes (A-34 unaffected — no destructive local-Postgres upgrade required).
- Out of scope (unchanged or deferred): A-38 draft retention/expiry/promotion, A-40 backup tooling and RPO/RTO, A-41 cloud-first reference environment, naming-alignment packet (`/entry` → `/note`, `diary_rag` → neutral name, `family_id` → neutral scope name), the remaining slices of A-39 above, derived-state export, HTTP / host-app delivery channels, AnswerTrace persistence (Phase 4), retrieval refinements (Phase 3.4+), schema migration tooling.

---

## D-030 — Revised draft workflow: remove `/draft`, add `/drafts [N]` recall, no promotion

### Decision
The first implementation packet after D-029 lands the revised draft workflow with three coordinated changes:

- **Remove the explicit `/draft` command surface (adapter).** `/draft` is dropped from `COMMAND_TOKENS` (`src/diary_rag/adapters/telegram/commands.py`). The reply text for `/start`, `/help`, and the unknown-command path is rewritten so the command list shown to users no longer mentions `/draft`. The `RouteKind.DRAFT` value, the dispatcher's DRAFT ingest branch, the classifier's no-command-→-DRAFT path, and the Postgres CHECK constraint on `detected_route` are unchanged: plain text without a recognised command is still preserved as a draft (D-027 / D-028 floor). Existing rows persisted with `detected_route='draft'` remain valid; no migration.
- **Add `/drafts [N]` recall (adapter + core + config).** A new `RouteKind.DRAFTS` value, a `/drafts` command token, and a new dispatcher branch parse the optional `N`. With no payload the dispatcher serves `drafts_default_limit` rows (default `5`); with an explicit positive `N` it serves `min(N, drafts_max_limit)` rows (default cap `20`). `N` that is zero, negative, or non-integer returns the fixed usage reply `"Usage: /drafts [N]. N must be a positive integer."`. `N` above `drafts_max_limit` is **silently clamped** to the cap; the header surfaces the discrepancy via `"Showing the K most recent drafts (you asked for N)."`. If fewer drafts exist than requested, the dispatcher returns all available and surfaces the discrepancy via `"Showing all K drafts (you asked for N)."`. When no drafts exist the header is `"No drafts to show."` and the adapter delivers it via the inline `sendMessage` body with no outbound call.
- **Combined-payload delivery (adapter).** `DispatchResult` gains an optional `drafts: list[SourceMessage] | None` field; the dispatcher populates it with the rows in most-recent-first order alongside the header reply text. The Telegram adapter renders header + ordered draft blocks into a single combined textual payload via a new pure helper `pack_drafts_into_messages(header, blocks)` (`src/diary_rag/adapters/telegram/drafts_packing.py`) and sends as **one** Telegram message by default. Splitting into multiple messages activates only when the combined payload exceeds Telegram's 4096-char cap; splits land on whole-block boundaries. A single oversized draft becomes its own consecutive multipart sequence with `(part k/N)` footers, and no neighbour block shares a message with any of its parts. `TelegramClient` Protocol gains `send_message(chat_id, text)`; `HttpxTelegramClient` calls `POST /bot<token>/sendMessage` without `parse_mode` so raw draft text passes through verbatim.
- **Repository seam (core / storage).** `DiaryRepository` gains `list_recent_drafts(family_id: str, *, limit: int) -> list[SourceMessage]` ordered `(created_at DESC, source_message_id DESC)` filtered to `detected_route == 'draft'`. `MockDiaryStore` and `PostgresDiaryStore` implement it; `SqliteDiaryStore` raises `NotImplementedError("sqlite drafts recall not supported; postgres is the canonical durable backend (D-022, D-030)")` matching the D-029 style. No new schema, no new index — sequential scan filtered by `family_id` is adequate at diary scale (followup if scale demands).
- **Settings (config).** Two new fields on `Settings`: `drafts_default_limit: int = 5` and `drafts_max_limit: int = 20`. Pydantic auto-binds `DRAFTS_DEFAULT_LIMIT` / `DRAFTS_MAX_LIMIT` env vars. `Dispatcher.__init__` now takes a `Settings` argument so the DRAFTS branch can read the two limits.
- **Promotion is cancelled product-wide.** Drafts are not note-candidates. There is no `/promote`, no draft-to-note transition, no shared finalize-note helper invoked from a promotion path. An earlier `/promote` packet draft is abandoned; the recall path is the only first-class operation on a captured draft after this packet.

### Why
D-027 named the draft-by-default safety floor and D-028 landed it in code with `RouteKind.DRAFT` carrying both the explicit `/draft` command and the no-command default. As the product model clarified, the explicit `/draft` command added no value beyond the no-command default — every plain-text message already lands as a draft — and conflated the surface. Removing it cleanly (no alias) keeps the command list minimal. Drafts being not-note-candidates removes a class of mechanics (promotion, retention semantics tied to promotion) that don't pay for the complexity at this stage; `/drafts` recall delivers the user-visible value (find the raw text you sent earlier) without that machinery.

The combined-payload delivery shape (one outbound message by default; multi-message split as transport fallback only) is a deliberate UX choice: the conceptual response is "here are your recent drafts," not "here's one message per draft." Splitting whole blocks across messages only when forced by the 4096-char cap keeps the chat-side UX coherent. Oversized single drafts become their own multipart sequence so that long-content drafts remain whole and inspectable in order, with no neighbour interleaving.

### Consequence
- Closes the **promotion-mechanics** slice of **A-38** by cancellation: promotion is not a planned mechanism. The retention / expiry slice of A-38 remains open as an independent question.
- Closes the **explicit-`/draft`-command** slice of A-38's lifecycle question: the lifecycle carrier remains `source_messages.detected_route='draft'`, written exclusively by the no-command path.
- Adds `RouteKind.DRAFTS`; `lifecycle_for(DRAFTS)` returns `"other"` via the existing fallback (DRAFTS is an action, not a lifecycle state).
- Adds `DispatchResult.drafts: list[SourceMessage] | None`. Mirrors `DispatchResult.document` (D-029); core stays adapter-agnostic.
- Adds `TelegramClient.send_message` to the Protocol and a `HttpxTelegramClient.send_message` implementation; `parse_mode` is omitted to preserve raw text verbatim.
- New: `src/diary_rag/adapters/telegram/drafts_packing.py`, plus four test files (`tests/test_drafts_packing.py`, `tests/test_dispatcher_drafts.py`, `tests/test_storage_list_recent_drafts.py`, `tests/test_telegram_drafts.py`).
- Changed: `core/routing/models.py` adds `RouteKind.DRAFTS` and `DispatchResult.drafts`; `services/dispatcher.py` adds `Settings` dependency, DRAFTS branch, header formatter, rewritten START/HELP/UNKNOWN reply text; `services/diary_service.py` adds `list_recent_drafts`; `storage/repository.py`, `storage/mock/store.py`, `storage/postgres/store.py`, `storage/sqlite/store.py` extend the seam; `adapters/telegram/commands.py` drops `/draft`, adds `/drafts`; `adapters/telegram/client.py` adds `send_message`; `adapters/telegram/webhook.py` injects `Settings` into the dispatcher factory and adds the DRAFTS outbound branch using `pack_drafts_into_messages`; `config.py` adds the two new fields. Existing tests that constructed `Dispatcher` now pass a `Settings` instance as the fourth argument.
- No schema changes (A-34 unaffected). The Postgres CHECK on `source_messages.detected_route` still allows `'draft'`; existing rows written by the now-removed `/draft` command remain valid recall targets.
- No new runtime dependencies.
- Out of scope (unchanged or deferred): A-10 (edit/delete of drafts), A-38 retention/expiry (the remaining open slice), A-39 (export delivery channels beyond Telegram), A-40 backup tooling, A-41 cloud-first reference, naming-alignment packet (`/entry` → `/note`, `diary_rag` → neutral name, `family_id` → neutral scope), drafts filtering/pagination/search, non-Telegram `/drafts` delivery, composite index on `(family_id, detected_route, created_at)` (scale-driven follow-up), AnswerTrace persistence (Phase 4), retrieval refinements (Phase 3.4+).

---

## D-031 — Naming alignment: user-facing `/entry` → `/note`

### Decision
The first implementation packet after D-030 flips the only remaining visible naming mismatch on the Telegram command surface — the historical `/entry` command — to its canonical product name `/note`, with no compatibility alias:

- **Command surface (adapter).** `COMMAND_TOKENS` (`src/diary_rag/adapters/telegram/commands.py`) replaces the `"/entry"` key with `"/note"` mapping to the existing `RouteKind.ENTRY`. No alias for `/entry`: typing `/entry` after this packet falls through to `RouteKind.UNKNOWN`, and the unknown-command reply points the user at `/note`. The "no alias" choice is recorded here as a packet decision and is not promoted to an assumption — the rename is one-shot, not a deprecation window.
- **Reply text (core dispatcher).** Every user-facing string in `services/dispatcher.py` that named `/entry` as the active command now names `/note`: `_REPLY_START`, `_REPLY_HELP`, `_REPLY_UNKNOWN`, `_REPLY_CLARIFY`, the heuristic-marker value (`"(routed as note — send /note next time to be explicit)"`), `_DRAFT_REPLY_HINT`, and the mock invalid-date reply (`"Mock /note needs an ISO date …"`). The constant identifier `_HEURISTIC_MARKER_ENTRY` stays — it is internal-only and renaming it would broaden the packet without behavioural payoff.
- **Internals untouched.** `RouteKind.ENTRY`, persisted `SourceMessage.detected_route='entry'`, the Postgres `detected_route` CHECK constraint, `DiaryEntry` / `entry_date` / `entry_text`, `parse_diary_entry`, `DiaryRepository`, the `diary_rag` package, and `family_id` are all explicitly out of scope. The lifecycle-vocabulary mapping `ENTRY → "note"` already lives in `core.routing.lifecycle_for` since D-028, so the user-facing `/note` and the persisted `detected_route='entry'` continue to converge only at that seam.
- **Tests.** User-facing input strings (`text="/note …"`) and reply-assertion strings flip to `/note`; tests that exercise `RouteKind.ENTRY` as an internal enum value are unchanged. A new negative test pins the "no alias" decision: `parse_command("/entry …")` returns `(RouteKind.UNKNOWN, "/entry …")`, mirroring the existing `/draft`-falls-through-to-UNKNOWN test from D-030.
- **Docs.** PRD, TechSpec, BuildPlan, README, QUICKSTART, AGENTS, ARCHITECTURE, RUNBOOK, execution-map, assumptions, and assumption-audit lose the "`/entry` (the historical name for `/note`)" hedge and present `/note` as the active command. Closed-slice narration in `docs/todo.md` and prior decision-log entries are historical records and stay verbatim.

### Why
D-026 set the portability rule that user-case vocabulary should not leak into the core; the broader naming-alignment was deferred so each rename could land on its own merits. The user-facing command rename is the smallest such slice and the highest-visibility one: every prompt-reply pair the user sees today still says `/entry`, while every canonical doc since D-027 names `/note` as the target. Closing that gap removes a recurring source of cognitive friction and is a pure adapter-layer change — no schema migration, no destructive upgrade, no new dependencies. Dropping `/entry` cleanly (no alias) keeps the command list minimal and avoids carrying a second name through future commits; an unknown-command reply that points at `/note` is enough recovery for any user who types the old token by habit.

### Consequence
- The Telegram adapter exposes `/start`, `/help`, `/note`, `/ask`, `/drafts`, `/export`. `/entry` is no longer a recognised command token.
- The "Naming note" subsection in PRD §5, the "Current command surface" subsection in TechSpec §4, the historical-name annotations in ARCHITECTURE and RUNBOOK, and the BuildPlan Phase-1 command list all drop the `/entry` framing.
- A-28 (mock ISO-only date parsing) updates its wording from `/entry` to `/note`; the rule itself is unchanged. The closed-A-17 line in `assumptions.md` stays — it records the original D-020 resolution, which was anchored on `/entry`, and rewriting historical closure lines would falsify the record.
- No code changes outside the Telegram adapter and the dispatcher; no schema, repository, or storage changes; no new dependencies; no destructive upgrade. Existing `source_messages` rows persisted with `detected_route='entry'` remain valid.
- Out of scope (unchanged or deferred): `RouteKind.ENTRY → NOTE` symbol rename, `detected_route` value migration from `'entry'` to `'note'`, Postgres CHECK constraint migration, `DiaryEntry` / `entry_date` / `entry_text` renames, `parse_diary_entry` rename, `DiaryRepository` rename, `diary_rag` package rename, `family_id` rename, retention/expiry (A-38), backup tooling (A-40), cloud-first reference (A-41), AnswerTrace persistence (Phase 4), retrieval refinements (Phase 3.4+).

---

## D-032 — Slice 3.5: retrieval-trace persistence (Query + RetrievalHit rows)

### Decision
The first implementation packet after D-031 lands the retrieval-side half of R-5 in code. Every `/ask` call writes one `Query` row plus zero-or-more `RetrievalHit` rows with `leg ∈ {dense, sparse, merged}`, so an operator can inspect via plain SQL what each retrieval leg saw and what survived RRF fusion. Answer-side `AnswerTrace` persistence remains deferred to Phase 4.

- **Domain models (core).** `core/diary/models.py` adds three exports following the existing `@dataclass(frozen=True, slots=True)` pattern:
  - `RetrievalLeg` (`StrEnum`: `"dense"`, `"sparse"`, `"merged"`).
  - `Query(query_id, family_id, query_text, model_name, fallback, created_at)`. `query_text` is the normalised payload (whitespace + trailing `?.!,;:` stripped); `model_name` is the embedding client's `model_name` at call time, even on the empty-query early-return; `fallback` mirrors the `AnswerResult` outcome.
  - `RetrievalHit(retrieval_hit_id, query_id, chunk_id, leg, rank, score, model_name, created_at)`. One row per (query, chunk, leg) tuple; `rank` is 1-based within the leg.
- **Tall shape over TechSpec §5's wide shape.** TechSpec §5 names `score_dense`, `score_sparse`, `score_hybrid`, `selected_for_context`, `retrieval_reason` — a wide row per chunk. This packet adopts a **tall** shape (one row per (chunk, leg)) because the packet wording explicitly mandates `leg ∈ {dense, sparse, merged}` and because the tall shape avoids nullable-score ambiguity ("`score_sparse = 0.0` vs sparse-did-not-match"). `selected_for_context` is implicitly encoded by the existence of a `leg='merged'` row. `rerank_score` and `retrieval_reason` are out of scope. Broader TechSpec §5 alignment remains pending under D-026.
- **Scoring = RRF contribution.** Per-leg rows persist `score = 1.0 / (RRF_K + rank)`; merged rows persist the fused RRF score (sum of leg contributions). D-025 explicitly avoided score calibration between cosine distance and `ts_rank_cd` ("RRF uses ranks, not calibrated scores"); persisted traces mirror that stance. Extending `SearchRepository` to surface backend-native scores was considered and rejected — it cross-cuts three backends for a non-load-bearing operator artefact, and the resulting mixed score scales would degrade the operator one-liner rather than improve it.
- **`model_name` semantics on hits.** Dense and merged rows carry the embedding model name (e.g. `"mock"`, `"text-embedding-3-large"`); sparse rows carry the FTS dictionary string `"simple"` (the Postgres `to_tsvector('simple', …)` configuration). This matches the existing `retrieval.hybrid model=…` log field for operator vocabulary.
- **Deferred Query fields.** `source_message_id` and `author_user_id` are intentionally omitted from `Query`. TechSpec §5 names both, but `/ask` does not currently persist a `SourceMessage` for the query message; adding either would require either a parallel ingest seam or a nullable FK — neither justified by this packet. Both fields remain pending under D-026.
- **Repository seam (core / storage).** `DiaryRepository` gains four methods: `save_query`, `save_retrieval_hits`, `get_query`, `get_retrieval_hits_for_query`. `get_retrieval_hits_for_query` orders results by `(leg ASC, rank ASC)` — stable for inspection and tests; the order is implementation-stable, not a product-level guarantee.
- **All three backends implement the full seam.** SQLite is a real implementation here (not `NotImplementedError`) because the trace methods are ingest-shaped, not retrieval-shaped. The existing SQLite retrieval restriction (`dense_candidates` / `sparse_candidates` raise `NotImplementedError`) is unchanged.
- **Postgres schema.** Two new tables in `src/diary_rag/storage/postgres/schema.sql`:
  - `queries(query_id PK, family_id, query_text, model_name, fallback CHECK ∈ {none, no_evidence, invalid_input}, created_at)` plus `idx_queries_family_id`.
  - `retrieval_hits(retrieval_hit_id PK, query_id FK→queries, chunk_id FK→event_chunks, leg CHECK ∈ {dense, sparse, merged}, rank ≥ 1, score DOUBLE PRECISION, model_name, created_at)` plus `idx_retrieval_hits_query_id` and `UNIQUE (query_id, chunk_id, leg)`.
  SQLite mirrors the structure with `REAL` for score and ISO-8601 TEXT for `created_at`.
- **SQLite-unavailable contour.** When `SearchRepository.dense_candidates` / `sparse_candidates` raise `NotImplementedError` (the SQLite contour from D-022 / D-025), the exception propagates out of `QueryService.answer` before any persistence call runs; `Dispatcher` continues to catch it and surface `NO_EVIDENCE` as before. This is an implementation contour, not a new contract — the packet's persistence guarantee is scoped to the two explicit cases below.
- **Persistence guarantees.** Exactly two:
  1. Successful retrieval writes one `Query` row plus per-leg `RetrievalHit` rows (one per chunk in `dense_candidates`, one per chunk in `sparse_candidates`) plus merged rows (one per chunk in the RRF-fused top-k).
  2. `NO_EVIDENCE` (empty normalised query or empty merged set) writes one `Query` row with zero `RetrievalHit` rows.
- **QueryService wiring.** `QueryService.__init__` now takes `(repo: DiaryRepository, search_repo: SearchRepository, embedding_client, *, top_k, candidate_k)`. The three existing concrete stores (`MockDiaryStore`, `SqliteDiaryStore`, `PostgresDiaryStore`) each satisfy both Protocols structurally, so the dispatcher factory passes the same store object twice.
- **Observability.** The `retrieval.hybrid` log line gains `query_id=…` and `fallback=…` fields. The empty-query early-return path also emits the log line so an operator can see that branch fired.
- **RRF function return shape.** `services/retrieval.py` now returns `list[FusedHit]` where `FusedHit(chunk, score)` carries the fused score per chunk. The signature change is the smallest one that exposes the merged-row score for persistence; not a refactor.
- **Operator inspection.** `RUNBOOK.md` adds a "Retrieval traces" subsection with two SQL one-liners (recent traces; failed answers only) plus the standard A-34 destructive-upgrade note.
- **Destructive local upgrade (A-34).** Existing local Postgres volumes that pre-date the new tables must be reset (`docker compose down -v`) before the bootstrap DDL applies cleanly. No migration tool yet; consistent with D-022 / D-023 / D-024 / D-025.

### Why
Slice 3.3 (D-025) stood up baseline hybrid retrieval but nothing about each `/ask` survived past the dispatcher reply: which legs ran, which chunks each returned, which ones survived RRF. R-5 has named `AnswerTrace` as a runtime invariant since the toolchain bootstrapped, but the retrieval-side half — the rows that describe what retrieval saw — was unenforced. This packet enforces it with the smallest seam that respects D-025's "no score calibration" stance and D-026's portability rule: two new tables, four new repository methods, one inline call in `QueryService.answer`. The tall shape and the RRF-contribution score are minimum-surface choices that keep the operator artefact honest without expanding `SearchRepository` or committing to a richer per-leg score model the next quality-decision packet will redo.

### Consequence
- I-9 and R-5 wording in `INVARIANTS.md` and `RUNTIME-INVARIANTS.md` tightened in place to reflect that retrieval-side trace persistence is now enforced; answer-side `AnswerTrace` remains deferred to Phase 4. No new I- or R- numbers.
- `retrieval_hits.chunk_id` FK references `event_chunks.chunk_id` on Postgres and SQLite. The FK is satisfiable in practice because chunks are necessarily known at hit-creation time (they came back from `dense_candidates` / `sparse_candidates`).
- New runtime dependencies: none. Existing psycopg / sqlite3 / dataclasses cover everything.
- New: `tests/test_storage_query_traces.py` (mock + sqlite + postgres parity).
- Changed: `core/diary/models.py` (`Query`, `RetrievalHit`, `RetrievalLeg`); `core/diary/__init__.py` exports; `services/retrieval.py` (return `list[FusedHit]`); `services/query_service.py` (third constructor arg, persistence inline, log line); `storage/repository.py` (four new Protocol methods); `storage/mock/store.py`, `storage/sqlite/store.py`, `storage/postgres/store.py` (implementations); `storage/postgres/schema.sql` (two new tables + indexes + UNIQUE); `adapters/telegram/webhook.py` (pass store twice into `QueryService`). Existing tests that constructed a `QueryService` directly pass the store twice (six call sites updated). `tests/test_retrieval_rrf.py` updated for the new `FusedHit` return shape plus a score-monotonicity assertion. `tests/test_query_service.py` gains three persistence cases. `tests/test_end_to_end_smoke.py` extended with two new assertions on the existing success / no-evidence cases.
- No schema migration tool (A-34 unchanged); A-34 destructive-upgrade discipline applies to the two new tables.
- Out of scope (unchanged or deferred): AnswerTrace persistence (Phase 4); metadata filtering / Slice 3.4; retrieval-quality changes; BM25 / reranker / Qdrant / halfvec / HNSW (next quality-decision packet); user-facing `/trace` command; schema migration tooling (A-34); Telegram adapter wording; the `RouteKind.ENTRY → NOTE` / `DiaryEntry` / `family_id` / `diary_rag` package renames (D-026); broader TechSpec §5 alignment for the deferred `Query` and `RetrievalHit` fields.

## D-033 — Slice 4.2: answer prompt contract (versioned prompt + structured-answer schema with citation grounding)

### Decision
Slice 4.2 lands the channel-neutral contract that every later 4.x packet (chat-client seam, fallback grading, Telegram citation rendering) attaches to. No provider SDK and no LLM call live here — only the deterministic prompt builder and the strict response parser.

- **Prompt builder (core).** `core/diary/answer_prompt.py` adds `PROMPT_VERSION: Final[str] = "v1"` plus `build_answer_prompt(context: AnswerContext) -> AnswerPrompt`. `AnswerPrompt(prompt_version, system_text, user_text, cited_chunk_ids)` is a `@dataclass(frozen=True, slots=True)` — same convention as the rest of `core/diary/models.py`; no Pydantic in core. Output is fully deterministic for a given input. The user-side body lists each chunk in `context.ordered_chunks` with `chunk_id`, ISO `entry_date`, `event_index`, and `chunk_text`; the empty-context path renders an explicit "no diary chunks were retrieved" placeholder so a downstream consumer can still call the LLM (or skip the call) without raising.
- **R-8 enforced in code.** The builder asserts that `{c.family_id for c in context.ordered_chunks}` has cardinality ≤ 1 and raises `CrossFamilyContextError` otherwise. R-8's "asserted in code, not just in policy" wording is now true at the prompt boundary.
- **Structured answer schema (core).** `core/diary/answer_schema.py` adds `StructuredAnswer(answer_text: str, cited_chunk_ids: tuple[str, ...], uncertainty: UncertaintyMarker)` plus `parse_structured_answer(raw: str, *, context: AnswerContext) -> StructuredAnswer`. The parser is strict-by-default: malformed JSON, non-object top-level, missing required fields, unexpected extra fields, wrong types, and unknown `uncertainty` markers each raise a typed `StructuredAnswerError` subclass (`MalformedAnswerJSONError`, `AnswerSchemaMismatchError`, `FabricatedCitationError`).
- **Uncertainty marker shape.** `UncertaintyMarker = Literal["confident", "uncertain", "no_evidence"]`. A minimal three-value set: `"no_evidence"` is the I-9 fallback marker (the only case where `cited_chunk_ids` may be empty); `"uncertain"` lets the LLM signal weak evidence without inventing a confidence score; `"confident"` is the default success path. Slice 4.3 (fallback grading) may extend or rename this marker — that change will be its own decision.
- **Citation grounding enforced in code (I-9).** `parse_structured_answer` requires `set(cited_chunk_ids) ⊆ {c.chunk_id for c in context.ordered_chunks}`; any other chunk_id raises `FabricatedCitationError`. Empty `cited_chunk_ids` is permitted only when `uncertainty == "no_evidence"`. This is the in-code enforcement of I-9 at the contract boundary; previously I-9's grounding rule was carried by `AnswerTrace.context_chunk_ids` wording alone, with no code-level check.
- **Re-exports.** `core/diary/__init__.py` exports `PROMPT_VERSION`, `AnswerPrompt`, `build_answer_prompt`, `CrossFamilyContextError`, `StructuredAnswer`, `parse_structured_answer`, `UncertaintyMarker`, `StructuredAnswerError`, `MalformedAnswerJSONError`, `AnswerSchemaMismatchError`, `FabricatedCitationError`.

### Why
Slice 4.1 plumbed `AnswerContext` through `QueryService.answer` but left no caller for it: the dispatcher's `_format_answer_reply` is still a hardcoded "evidence bullets" string. Three downstream packets (chat-client seam, fallback grading, Telegram citation rendering) all need to agree on the prompt template and on the shape of the LLM's structured response — without that agreement they cannot be built independently. This packet is the smallest validation-driven step that fixes the seam: a deterministic builder, a strict parser, and the I-9 citation-subset rule enforced in code at the contract boundary. Splitting the prompt builder and the parser into separate packets would force one of them to land without a counterparty to validate against; bundling either with the chat-client seam would mix a contract decision with a provider integration.

### Consequence
- I-9 in `INVARIANTS.md` tightened in place to record the parser-enforced citation-subset rule (`StructuredAnswer.cited_chunk_ids ⊆ AnswerContext.ordered_chunks`, fabricated citations raise `FabricatedCitationError`, empty citations only with `uncertainty == "no_evidence"`). No new I- numbers; R-5 / R-8 wording unchanged in this packet (R-8's in-code assertion is now true at the prompt boundary, but the existing R-8 sentence already promises that — no broader wording added).
- New runtime dependencies: none. Stdlib `json` covers the parser.
- New: `src/diary_rag/core/diary/answer_prompt.py`, `src/diary_rag/core/diary/answer_schema.py`, `tests/test_answer_prompt.py`, `tests/test_answer_schema.py`.
- Changed: `src/diary_rag/core/diary/__init__.py` (re-exports). No other source file changed; no `QueryService.answer`, dispatcher, retrieval, repository, or schema changes.
- Out of scope (unchanged or deferred): `ChatClient` Protocol, `MockChatClient`, OpenAI adapter (next packet); `AnswerTrace` schema and persistence (subsequent packet); fallback grading beyond the literal marker shape (Slice 4.3); Telegram citation rendering or dispatcher rewiring (Slice 4.4); search-quality fork (D-025 follow-up); `RouteKind.ENTRY → NOTE` / `DiaryEntry` / `family_id` / `diary_rag` package renames (D-026); schema migration tooling (A-34).

## D-034 — Slice 4.3a: ChatClient seam + AnswerTrace persistence on the success / no-evidence contours

### Decision
Slice 4.3a is the first caller of the D-033 contract. It introduces a channel-neutral `ChatClient` Protocol, a deterministic `MockChatClient`, and the answer-side `AnswerTrace` persistence that closes the answer-side half of R-5 on the two contours that exist today (success and no-evidence/empty-query). Weak-evidence / ambiguous / provider-unavailable grading and the corresponding marker semantics stay deferred to Slice 4.3 proper. Real provider adapters remain deferred.

- **Channel-neutral seam.** `core/answers/client.py` adds the `ChatClient` Protocol (`model_name: str` property, `complete(prompt: AnswerPrompt) -> ChatResponse`) and the frozen-slotted `ChatResponse(raw_text, model_name, token_counts, latency_ms)` dataclass. No provider SDK imports in core (I-11). `ChatResponse.latency_ms` is the single source of truth for chat-call latency; `QueryService` persists it directly and does not re-measure with `time.perf_counter()`.
- **Mock adapter, honest provenance.** `adapters/answers/mock.py` adds `MockChatClient` with `model_name="mock"` (D-024-style provenance applied to the chat seam) and `latency_ms=0` (a mock has no real provider latency to attribute; reporting anything else would be dishonest). The emitted `raw_text` is JSON that round-trips through `parse_structured_answer(..., context=...)`: `cited_chunk_ids = prompt.cited_chunk_ids`, `uncertainty="confident"` (or `"no_evidence"` for empty citations), deterministic answer text.
- **Single factory.** `adapters/answers/factory.py` adds `build_chat_client(settings)`. The literal `Settings.chat_backend` is `Literal["mock"]` for now; real adapters extend the literal in a later packet.
- **Domain model.** `core/diary/models.py` adds `AnswerTrace` (`answer_trace_id`, `query_id`, `prompt_version`, `context_chunk_ids: tuple[str, ...]`, `answer_text`, `fallback_mode`, `model_name`, `token_counts: dict[str, int]`, `latency_ms`, `created_at`). `AnswerResult` gains an optional `answer_text: str | None = None` so the success path can carry the LLM output alongside the existing evidence list; the Telegram reply layer keeps reading `evidence` in this packet (Slice 4.4 switches to `answer_text` + citations).
- **No `confidence_band` field.** TechSpec §5 names `confidence_band` on `AnswerTrace`; this packet does **not** introduce it. Marker semantics richer than `{confident, uncertain, no_evidence}` are a Slice 4.3 contract decision; pre-committing here would force a premature column.
- **Repository seam = two methods.** `DiaryRepository` Protocol gains exactly `save_answer_trace(trace: AnswerTrace) -> None` and `get_answer_trace_for_query(query_id: str) -> AnswerTrace | None`. No test-only helpers on the Protocol. `MockDiaryStore` adds a `len_answer_traces()` helper for parity with `len_queries()` / `len_retrieval_hits()`; this helper is mock-specific (it follows the established test-helper pattern; not part of the Protocol).
- **All three backends implement the seam.** Mock keeps the row in a process-local dict keyed by `query_id`. SQLite adds the `answer_traces` table to its in-file DDL with `context_chunk_ids` and `token_counts` serialised as JSON `TEXT`. Postgres uses a `TEXT[]` for `context_chunk_ids` and `JSONB` for `token_counts`. All three enforce `UNIQUE (query_id)`.
- **Postgres schema.** One new table in `schema.sql`:
  ```sql
  CREATE TABLE IF NOT EXISTS answer_traces (
      answer_trace_id   TEXT PRIMARY KEY,
      query_id          TEXT NOT NULL UNIQUE REFERENCES queries(query_id),
      prompt_version    TEXT NOT NULL,
      context_chunk_ids TEXT[] NOT NULL,
      answer_text       TEXT NOT NULL,
      fallback_mode     TEXT NOT NULL
          CHECK (fallback_mode IN ('none','no_evidence','invalid_input')),
      model_name        TEXT NOT NULL,
      token_counts      JSONB NOT NULL,
      latency_ms        INTEGER NOT NULL CHECK (latency_ms >= 0),
      created_at        TIMESTAMPTZ NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_answer_traces_query_id ON answer_traces(query_id);
  ```
  The `fallback_mode` CHECK reuses the `FallbackMode` value set already in use on `queries.fallback`.
- **QueryService wiring.** `__init__` adds `chat_client: ChatClient` as a required positional parameter (one new constructor arg, mirroring the Slice 3.5 pattern). `answer()` is updated:
  - **Empty-query branch.** Already returns `FallbackMode.NO_EVIDENCE` today (`Query.fallback` semantics unchanged from D-032). After the existing `_persist_trace(...)`, persist an `AnswerTrace` with empty `context_chunk_ids`, empty `answer_text`, `latency_ms=0`, empty `token_counts`, and `fallback_mode=NO_EVIDENCE`. **Not a remap** — the `AnswerTrace.fallback_mode` value mirrors the existing `Query.fallback` value.
  - **No-evidence branch (merged empty after retrieval).** Same shape as the empty-query trace. No LLM call.
  - **Success branch.** Build `AnswerPrompt` from `AnswerContext` (R-8 cross-family guard now actually runs), call `chat_client.complete(prompt)`, parse the response with `parse_structured_answer(raw_text, context=context)` (I-9 citation grounding now hit on every success), persist the `AnswerTrace` with `latency_ms=response.latency_ms` (no independent measurement), and return `AnswerResult` carrying both the existing `evidence` list and the new `answer_text`.
- **Parse-failure handling deferred.** If `parse_structured_answer` raises a typed `StructuredAnswerError` subclass on the success branch, the exception propagates. No retry loop, no repair prompt, no malformed-JSON recovery workflow. The mock always produces valid output; the path exists for the real-provider future and is not exercised in this packet. Slice 4.3 introduces the marker and the grading.
- **Observability.** The `retrieval.hybrid` log line gains `answer_trace_id=…` on all three branches so an operator can pivot from log to trace row in one SQL.
- **Boot gate (R-10) extended.** `app._verify_chat_contour(settings)` instantiates the configured chat client and asserts a non-empty `model_name`. Failure aborts boot, mirroring the embedding contour gate.
- **Settings + .env.** `Settings.chat_backend: Literal["mock"]` is added. The pre-existing `Settings.chat_model: str` placeholder is retained (the mock ignores it; real providers will populate it in a later packet). `.env.example` documents the new `CHAT_BACKEND` knob.
- **Destructive local upgrade (A-34).** Existing local Postgres volumes that pre-date the `answer_traces` table must be reset (`docker compose down -v`) before the bootstrap DDL applies cleanly. No migration tool yet; consistent with D-022 / D-023 / D-024 / D-025 / D-032.

### Why
D-033 left the prompt/parse contract dangling with no caller; D-032 left R-5's answer-side half explicitly deferred. Building the chat seam without the trace would leave the contract called but the runtime invariant still half-satisfied; building the trace without the seam would persist synthetic data the LLM never produced (dishonest provenance). Bundling them mirrors D-032's pattern (it bundled the retrieval seam with its trace rows) and produces the smallest validation-driven step that closes both gaps on the two contours that exist today, without committing to the fallback-grading contract that Slice 4.3 owns.

### Consequence
- I-9 in `INVARIANTS.md` and R-5 in `RUNTIME-INVARIANTS.md` tightened in place to record that answer-side trace persistence is now enforced on the success and no-evidence/empty-query contours. No new I- or R- numbers; weak-evidence / ambiguous / provider-unavailable grading remains deferred to Slice 4.3.
- New runtime dependencies: none. Existing `psycopg.types.json.Jsonb` covers the JSONB binding.
- New: `src/diary_rag/core/answers/__init__.py`, `src/diary_rag/core/answers/client.py`, `src/diary_rag/adapters/answers/__init__.py`, `src/diary_rag/adapters/answers/mock.py`, `src/diary_rag/adapters/answers/factory.py`, `tests/test_chat_client_mock.py`, `tests/test_storage_answer_traces.py`.
- Changed: `src/diary_rag/core/diary/models.py` (`AnswerTrace`; optional `AnswerResult.answer_text`); `src/diary_rag/core/diary/__init__.py` (re-export `AnswerTrace`); `src/diary_rag/storage/repository.py` (two new Protocol methods); `src/diary_rag/storage/mock/store.py`, `storage/sqlite/store.py`, `storage/postgres/store.py` (implementations + new tables); `src/diary_rag/storage/postgres/schema.sql` (one new table); `src/diary_rag/services/query_service.py` (new constructor arg, success + no-evidence wiring, log-line extension); `src/diary_rag/adapters/telegram/webhook.py` (build chat client; pass to `QueryService`); `src/diary_rag/config.py` (`chat_backend` literal); `src/diary_rag/app.py` (`_verify_chat_contour`); `.env.example` (chat stanza). Existing tests that constructed a `QueryService` directly pass `MockChatClient()` as the new fourth positional argument (five call sites updated). `tests/test_query_service.py` gains three answer-trace persistence cases. `tests/test_end_to_end_smoke.py` gains two answer-trace assertions on the existing success and no-evidence cases.
- No schema migration tool (A-34 unchanged); A-34 destructive-upgrade discipline applies to the new table.
- Out of scope (unchanged or deferred): real OpenAI / Anthropic chat adapter; weak-evidence / ambiguous / provider-unavailable grading (Slice 4.3); `confidence_band` semantics (Slice 4.3); Telegram citation rendering / reply rewriting (Slice 4.4); parse-failure repair / retry loops; metadata filtering / Slice 3.4; retrieval-quality changes; BM25 / reranker / Qdrant / halfvec / HNSW; user-facing `/trace` command; schema migration tooling (A-34); the `RouteKind.ENTRY → NOTE` / `DiaryEntry` / `family_id` / `diary_rag` package renames (D-026).

---

## D-035 — Slice 4.3b: answer-side fallback grading (weak-evidence / ambiguous / provider-unavailable / parse-failure)

### Decision
Slice 4.3b closes the answer-side grading contours that Slice 4.3a explicitly deferred. The packet extends the shared `FallbackMode` enum with four new answer-side members, extends the LLM-facing `UncertaintyMarker` with `"ambiguous"`, adds a typed `ChatProviderUnavailableError` in `core/answers/client.py`, and reorganises `QueryService.answer` so every contour writes `Query.fallback` and `AnswerTrace.fallback_mode` from one decision (they always agree). The Dispatcher gains surface-level R-6 signaling per `FallbackMode`, including a sub-branch on `bool(AnswerResult.evidence)` that distinguishes the two `NO_EVIDENCE` effective paths. No real provider adapter, no retry / repair loop, no Telegram answer-text / citation rewrite (Slice 4.4 owns that), no `confidence_band` column.

- **`FallbackMode` extension.** `WEAK_EVIDENCE`, `AMBIGUOUS`, `PROVIDER_UNAVAILABLE`, `PARSE_FAILURE` added to the shared StrEnum. `INVALID_INPUT` continues to belong to ingest-side `DiaryService` and is unaffected. Postgres CHECK constraints on `queries.fallback` and `answer_traces.fallback_mode` widened to admit the four new values (SQLite mirrors the same set in its in-file DDL).
- **`UncertaintyMarker` extension + tightened citation rule.** `UncertaintyMarker = Literal["confident", "uncertain", "no_evidence", "ambiguous"]`. `parse_structured_answer` continues to require `cited_chunk_ids ⊆ AnswerContext.ordered_chunks` and now states explicitly that empty `cited_chunk_ids` is permitted **only** when `uncertainty == "no_evidence"`; `"uncertain"` and `"ambiguous"` therefore require non-empty citations. Marker → `FallbackMode` mapping (applied in `QueryService.answer`): `confident → NONE`, `uncertain → WEAK_EVIDENCE`, `no_evidence → NO_EVIDENCE` (the LLM declared the retrieved chunks not-evidence), `ambiguous → AMBIGUOUS`.
- **`ChatProviderUnavailableError`.** Typed exception added to `core/answers/client.py` (re-exported from `core/answers/__init__.py`). Real provider adapters raise it on timeout / HTTP failure / auth failure in Phase 6. `MockChatClient` never raises naturally; tests use minimal stub chat clients defined inline. `QueryService.answer` catches it **once** and grades the call as `PROVIDER_UNAVAILABLE` — no retry, no repair. Recovery workflows belong to Phase 6.
- **`StructuredAnswerError` propagation is now caught.** `QueryService.answer` wraps `parse_structured_answer` and catches the base `StructuredAnswerError` (covers `MalformedAnswerJSONError`, `AnswerSchemaMismatchError`, `FabricatedCitationError`). The trace preserves `response.raw_text` as `answer_text` for forensics. `CrossFamilyContextError` from `build_answer_prompt` continues to propagate uncaught — it is an R-8 programming-error signal, not a graded fallback.
- **Truthful trace shape per contour** (the contract; tests assert this table verbatim):

  | `fallback_mode` | `answer_text` | `context_chunk_ids` | `token_counts` | `latency_ms` |
  | --- | --- | --- | --- | --- |
  | `NONE` | LLM output | from `AnswerContext` | from response | from response |
  | `NO_EVIDENCE` (empty query) | `""` | `()` | `{}` | `0` |
  | `NO_EVIDENCE` (empty retrieval) | `""` | `()` | `{}` | `0` |
  | `NO_EVIDENCE` (LLM marker) | LLM output | from `AnswerContext` | from response | from response |
  | `WEAK_EVIDENCE` | LLM output | from `AnswerContext` | from response | from response |
  | `AMBIGUOUS` | LLM output | from `AnswerContext` | from response | from response |
  | `PROVIDER_UNAVAILABLE` | `""` | from `AnswerContext` | `{}` | `0` |
  | `PARSE_FAILURE` | `response.raw_text` | from `AnswerContext` | from response | from response |

  `model_name` follows the existing rule: `response.model_name` when a response exists, else `chat_client.model_name` (empty query, empty retrieval, provider unavailable).
- **`Query.fallback` mirrors `AnswerTrace.fallback_mode`.** The `Query` row is the lifecycle view of the `/ask` call; the effective path is the same on both rows by construction. `QueryService.answer` defers Query construction until the grading decision is made; a single `_finalize(...)` helper writes the Query, the retrieval hits, and the answer trace from one set of arguments. The earlier `_persist_no_evidence_answer_trace` generalises to a single `_persist_answer_trace(...)` entry point so the table above is enforced in code.
- **`confidence_band` explicitly deferred.** TechSpec §5 lists a `confidence_band` field on `AnswerTrace`. This packet does **not** introduce a stored column. The truthful surface today is `fallback_mode` plus the LLM marker: a `confidence_band` column would store derived data and widen schema scope (extra CHECK, extra A-34 friction) without adding information. A future packet may introduce it if a richer semantic emerges.
- **Dispatcher reply text per `FallbackMode` (channel-neutral; Telegram wording stays out of core).**
  - `NONE` — evidence list + `(hybrid retrieval — dense+sparse RRF)` trailer (unchanged).
  - `NO_EVIDENCE` with empty `AnswerResult.evidence` (empty query or empty retrieval) — `"No memories matched '…'."` (unchanged).
  - `NO_EVIDENCE` with non-empty `AnswerResult.evidence` (LLM marker) — `"Found possible matches but couldn't ground an answer for '…'. Try refining the question."` (no evidence list, no RRF trailer). The two `NO_EVIDENCE` sub-paths produce byte-distinct replies so the user can tell them apart (R-6).
  - `WEAK_EVIDENCE` — evidence list + new trailer `"(weak evidence — model expressed uncertainty)"`.
  - `AMBIGUOUS` — evidence list + new trailer `"(ambiguous question — refine and ask again)"`.
  - `PROVIDER_UNAVAILABLE` — `"Couldn't generate an answer — chat provider is unavailable. Try again later."` (no evidence list, no trailer).
  - `PARSE_FAILURE` — `"Couldn't generate an answer — provider response was unparseable. Try again."` (no evidence list, no trailer).
  Heuristic-route marker continues to append on the ASK contour for every `FallbackMode`.
- **Log line.** `retrieval.hybrid` already carries `fallback=…` and `answer_trace_id=…`; the new `FallbackMode` values appear in `fallback=…` automatically.
- **Destructive local upgrade (A-34).** Existing local Postgres volumes that pre-date the widened CHECK constraints must be reset (`docker compose down -v`) before the bootstrap DDL applies cleanly. No migration tool yet; consistent with D-022 / D-023 / D-024 / D-025 / D-032 / D-034.

### Why
D-034 deliberately landed only the success and no-evidence/empty-query contours so the chat seam and the trace shape could be validated before the harder grading questions were settled. R-6 lists four fallback conditions (no-evidence, weak-evidence, ambiguous, provider-unavailable) that demand requested-vs-effective signaling; D-033's parse-failure path is the fifth, deferred at the time. Closing all four answer-side contours together produces the smallest validation-driven step that satisfies R-5 and R-6 end-to-end. Bundling them avoids the half-state where the trace records `fallback_mode=NONE` even though the LLM emitted `uncertainty="uncertain"`, and avoids a Slice-4.4 reply rewrite that has to special-case half-graded outcomes.

The `NO_EVIDENCE` sub-branch in the Dispatcher is the load-bearing R-6 detail in this packet: the same enum value covers two meaningfully different effective paths (empty retrieval vs LLM-marker over non-empty retrieval). Rendering both as "No memories matched '…'" would be untruthful for the second path. The Dispatcher disambiguates on `bool(AnswerResult.evidence)` and produces a distinct reply for the LLM-marker path so the user can tell what actually happened.

### Consequence
- I-9 in `INVARIANTS.md` and R-5 + R-6 in `RUNTIME-INVARIANTS.md` tightened in place to record that answer-side trace persistence and surface-level requested-vs-effective signaling are enforced on every `/ask` reply. No new I- or R- numbers.
- New runtime dependencies: none.
- New: `tests/test_dispatcher_retrieval_fallback.py` gains six new cases (one per new contour plus the dedicated LLM-marker `NO_EVIDENCE` distinctness case and a heuristic-marker case); other test files extended in place.
- Changed: `src/diary_rag/core/diary/models.py` (`FallbackMode` + `AnswerTrace` docstring); `src/diary_rag/core/diary/answer_schema.py` (`UncertaintyMarker` extension + docstring); `src/diary_rag/core/answers/client.py` (`ChatProviderUnavailableError`); `src/diary_rag/core/answers/__init__.py` (re-export); `src/diary_rag/services/query_service.py` (grading flow + `_finalize` + `_persist_answer_trace` + module-level marker map); `src/diary_rag/services/dispatcher.py` (`_format_answer_reply` switch + four new module-level reply constants); `src/diary_rag/storage/postgres/schema.sql` and `src/diary_rag/storage/sqlite/store.py` (widened CHECK on `fallback` / `fallback_mode`); `tests/test_query_service.py`, `tests/test_storage_answer_traces.py`, `tests/test_answer_schema.py`, `tests/test_end_to_end_smoke.py`, `tests/test_dispatcher_retrieval_fallback.py` (new cases).
- `MockChatClient` unchanged — honest-provenance discipline preserved.
- No schema migration tool (A-34 unchanged); A-34 destructive-upgrade discipline applies to the widened CHECK constraints.
- `assumptions.md` not touched. Internal contract decisions (the four new `FallbackMode` members, the marker mapping, the trace shape per contour, the `confidence_band` deferral) belong in this decision-log entry, not in open assumptions.
- Out of scope (unchanged or deferred): real OpenAI / Anthropic chat adapter (Phase 6); Telegram answer-text rendering / citation rendering / reply rewrite (Slice 4.4); retry / repair / recovery loops; `confidence_band` column; metadata filtering / Slice 3.4; retrieval-quality changes; BM25 / reranker / Qdrant / halfvec / HNSW; schema migration tooling; the `RouteKind.ENTRY → NOTE` / `DiaryEntry` / `family_id` / `diary_rag` package renames (D-026).

---

## D-036 — Slice 4.4: Telegram default reply switches to `answer_text`; on-demand `/sources` exposes the selected chunks as-is

### Decision
Slice 4.4 splits the Telegram answer surface in two: the normal `/ask` reply renders the LLM-produced `answer_text` as its primary body, and a new `/sources` command exposes the chunks retrieval selected for the chat's most recent `/ask` turn. No retrieval, prompting, schema, or LLM-pipeline change.

- **`/ask` reply body switch.** `Dispatcher._format_answer_reply` now returns `result.answer_text + "\n\n" + <trailer>` for `FallbackMode.NONE`, `WEAK_EVIDENCE`, and `AMBIGUOUS`. Trailers are byte-identical to D-035 (`_RETRIEVAL_TRAILER`, `_TRAILER_WEAK_EVIDENCE`, `_TRAILER_AMBIGUOUS`). `PROVIDER_UNAVAILABLE` and `PARSE_FAILURE` keep their fixed retry-hint replies. The `NO_EVIDENCE` sub-branch on `bool(result.evidence)` (D-035 / R-6) is unchanged: empty → `"No memories matched '<query>'."`; LLM-marker → `"Found possible matches but couldn't ground an answer for '<query>'. Try refining the question."`. The LLM-marker branch deliberately does **not** surface the model's "no_evidence" prose — the model declared its own output a non-answer; rendering it as an answer body would violate R-6's "no silent degradation". The pre-D-036 `_format_evidence_lines` helper is removed.
- **`/sources` semantic contract (no ambiguity).** `/sources` renders the **selected chunks as-is** for the chat's most recent `/ask` turn. "Selected" = the post-RRF top-k chunks that `services/context_assembler.assemble_answer_context` produced and that `build_answer_prompt` fed into the prompt (= `AnswerResult.context.ordered_chunks` = the `chunk_id` list persisted on `AnswerTrace.context_chunk_ids`). "As-is" = the chunk's full `chunk_text` plus its `entry_date` and `chunk_id`, with no excerpt extraction, no per-sentence highlighting, and no quote-span attribution.
  - `/sources` is **not citations** and **not fine-grained attribution**. The packet does not render `StructuredAnswer.cited_chunk_ids` (the LLM-emitted subset), does not produce per-quote spans, and does not link an answer phrase to a source chunk. Any future "the answer's claim X is attributed to chunk Y" surface is a separate packet.
  - `/sources` is **not the full retrieved candidate pool**. The pre-RRF dense and sparse candidates (`dense_n` / `sparse_n`) are larger than the selected set and are not user-facing; they remain inspectable only via the `retrieval_hits` table (D-032).
  - Docs and tests use phrases like "selected chunks", "the chunks retrieval selected for the answer", or "the chunks fed into the prompt." The word "citation" is reserved for any future packet that introduces fine-grained attribution.
- **`RouteKind` + command surface.** `RouteKind.SOURCES` is added; `lifecycle_for(SOURCES)` returns `"other"` via the existing fallthrough (SOURCES is a read-only action, not a lifecycle state). `"/sources"` is added to `COMMAND_TOKENS` (`adapters/telegram/commands.py`). `_REPLY_START`, `_REPLY_HELP`, and `_REPLY_UNKNOWN` in `services/dispatcher.py` are updated to list `/sources` alongside `/note`, `/ask`, `/drafts`, `/export`. A trailing payload after `/sources` is ignored (mirrors the `/drafts` trailing-payload tolerance).
- **Latest-sources cache lifecycle.** A private `Dispatcher._latest_sources: dict[str, tuple[EventChunk, ...]]` keyed by `family_id` (= `external_chat_id`) holds the selected chunks for each chat's most recent `/ask` turn. **Every `/ask` dispatch updates the cache** (no contour skips it):
  - non-empty `answer.context.ordered_chunks` (covers `NONE`, `WEAK_EVIDENCE`, `AMBIGUOUS`, LLM-marker `NO_EVIDENCE`, `PROVIDER_UNAVAILABLE`, `PARSE_FAILURE`) → overwrite the entry with those chunks;
  - empty (empty-query, empty-retrieval `NO_EVIDENCE`, and the `NotImplementedError` retrieval-unavailable contour where `answer.context` is `None`) → clear the entry.

  Non-`/ask` routes (`/note`, `/drafts`, `/export`, `/start`, `/help`, draft no-command, CLARIFY, `/sources` itself) never touch the cache. `/sources` is read-only and idempotent; only the next `/ask` invalidates the cache.
- **Dispatcher lifecycle proof — in-memory state is acceptable.** The FastAPI wiring at `adapters/telegram/webhook.py` makes `Dispatcher` a module-level singleton via `get_dispatcher()`:
  - `_dispatcher: Dispatcher | None = None` is a module-level singleton (`webhook.py:41`);
  - `get_dispatcher()` lazy-initialises and returns the same instance forever (`webhook.py:57-90`);
  - `Depends(get_dispatcher)` (`webhook.py:124`) wires that singleton into the webhook handler — FastAPI calls `get_dispatcher()` per request, but the function returns the same module-level instance.

  Therefore `/ask` and a follow-up `/sources` are served by the same `Dispatcher` instance within one process, and the in-memory cache survives across requests. Restart → `_dispatcher` is `None` again → new instance → empty cache (matches the fail-closed reply contour). **Multi-worker deploys** (uvicorn `--workers N`, multi-pod) hold per-worker singletons, so `/sources` becomes worker-affinity-sensitive: the contract that "the next `/ask` invalidates" requires both calls to hit the same worker. This is a documented known limitation. If the local-dev contour ever flips to multi-worker before a durable seam is added, the cache must be promoted to a durable store (e.g. `DiaryRepository.get_latest_answer_trace_for_family(family_id)` plus a per-chunk `get_event_chunk` lookup); shipping that promotion is the trigger for a follow-up packet.
- **`DispatchResult.source_blocks: list[str] | None`.** A new optional field carries pre-rendered chunk blocks for the adapter; distinct from `drafts: list[SourceMessage] | None` so the typed adapter shape stays honest (chunks are `EventChunk`, not `SourceMessage`). Mirrors the `drafts` / `document` outbound pattern. The webhook (`adapters/telegram/webhook.py`) adds a SOURCES outbound branch after the `drafts` block: calls `pack_drafts_into_messages(header, source_blocks)` and delivers via `telegram_client.send_message`, mirroring the drafts error-handling shape (`sources.delivery_failed` log line; short usage-fallback on outbound failure). The fail-closed reply path returns inline `sendMessage` with no outbound call.
- **Block format.** `Dispatcher._render_source_block(chunk)` returns `f"[{chunk.entry_date.isoformat()}] {chunk.chunk_id}\n\n{chunk.chunk_text}"`. The `chunk_id` is retained for operator forensics; `chunk_text` is rendered verbatim ("as-is"). The block separator and combined-message semantics are inherited unchanged from `pack_drafts_into_messages` (D-030): one Telegram message by default, multi-message split only when the 4096-char cap forces it, on whole-block boundaries, with `(part k/N)` footers for an oversized single chunk.
- **Reply text.** Header for a populated `/sources`: `"Selected chunks for your last /ask (N chunk(s)):"`. Fail-closed reply: `"No selected chunks available — ask a question with /ask first."`.

### Why
Slices 4.2 → 4.3a → 4.3b landed the prompt contract (D-033), the `ChatClient` seam + `AnswerTrace` persistence (D-034), and answer-side fallback grading (D-035). `AnswerResult.answer_text` already carried the LLM reply, and `AnswerTrace.context_chunk_ids` already persisted the chunk-id list each answer was grounded in. The dispatcher's `_format_answer_reply`, however, still hardcoded the pre-D-034 "evidence bullets" body — the LLM-produced text was silently dropped from the user-visible reply. Closing this gap is the smallest validation-driven step that makes the answer surface reflect what the pipeline now actually produces. The on-demand `/sources` half keeps the inspectable "what did retrieval feed the model" view without making the default reply chatty.

The owner's correction on this packet narrowed `/sources` precisely to "selected chunks as-is" — explicitly NOT "citations", NOT fine-grained attribution, and NOT the full retrieved candidate pool. The contract above carries that wording verbatim so future packets do not silently widen `/sources` into a different surface.

### Consequence
- R-6 in `RUNTIME-INVARIANTS.md` is tightened in place to record that the `/ask` reply body is now `answer_text` and that the requested-vs-effective signal is carried by the trailers and the `NO_EVIDENCE` sub-branch text. I-9 wording is unchanged: `/sources` reads from the chunks already covered by `AnswerTrace.context_chunk_ids` (the answer-side persistence invariant landed in D-035).
- New runtime dependencies: none.
- New: `tests/test_dispatcher_sources.py` (full cache-lifecycle coverage including per-family isolation and the read-only-idempotent property of `/sources`); `tests/test_telegram_sources.py` (webhook smoke for combined single-message delivery and the forced multi-message split).
- Changed: `src/diary_rag/core/routing/models.py` (`RouteKind.SOURCES`; `DispatchResult.source_blocks`); `src/diary_rag/adapters/telegram/commands.py` (`/sources` token); `src/diary_rag/services/dispatcher.py` (`_format_answer_reply` rewrite; `_REPLY_SOURCES_NONE`; `_render_source_block`; `Dispatcher._latest_sources` cache and `_update_latest_sources` + `_dispatch_sources` helpers; updated `_REPLY_START` / `_REPLY_HELP` / `_REPLY_UNKNOWN` strings; `_format_evidence_lines` removed); `src/diary_rag/adapters/telegram/webhook.py` (SOURCES outbound delivery branch). Test files extended in place: `tests/test_dispatcher_retrieval_fallback.py` (weak-evidence and ambiguous assertions flipped to assert `answer_text` body, not evidence bullets); `tests/test_end_to_end_smoke.py` (`Found N memory` shapes flipped; new `/sources` smoke tests added; weak-evidence smoke flipped); `tests/test_telegram_reply.py` (help-reply asserts `/sources` is listed); `tests/test_telegram_commands.py` (`/sources` parsing case).
- No schema change. No migration. No new env var. No new runtime dep. A-34 destructive-upgrade discipline does not apply (no DDL change).
- `assumptions.md` not touched. The `/sources` semantic contract, the cache lifecycle, the Dispatcher lifecycle proof, and the multi-worker caveat are internal contract decisions and belong in this entry, not in open assumptions.
- Out of scope (unchanged or deferred): rendering `StructuredAnswer.cited_chunk_ids` (the LLM-emitted subset) as a separate surface; fine-grained / per-sentence / per-quote attribution; cross-restart or cross-worker durability for the latest-sources cache (a durable seam is the follow-up trigger named above); `/sources N` argument parsing; user-facing `/trace` command; real OpenAI / Anthropic chat adapter (Phase 6); retry / repair / recovery loops; metadata filtering / Slice 3.4; retrieval-quality changes (BM25 / reranker / Qdrant / halfvec / HNSW); schema migration tooling (A-34); the `RouteKind.ENTRY → NOTE` / `DiaryEntry` / `family_id` / `diary_rag` package renames (D-026).

---

## D-037 — Slice 4.5: OpenAI chat client adapter + canonical chat-model lock

### Decision
Slice 4.5 stands up the first real chat-provider adapter behind the D-034 `ChatClient` seam, mirroring how D-024 added `OpenAIEmbeddingClient` behind the already-existing `EmbeddingClient` seam. The packet is provider-side only: it does not touch the answer pipeline, the trace shape, the dispatcher, retrieval, or `/sources`. Slice 4.4 (D-036) closed the Telegram-side rendering; this packet closes the provider-side of the same seam.

- **OpenAI adapter.** `adapters/answers/openai_client.py` adds `OpenAIChatClient(api_key, *, model_name)`. Constructor refuses empty `api_key` and empty `model_name`; lazy-imports `openai` inside `__init__` (mirrors `OpenAIEmbeddingClient`). `complete(prompt)` calls `client.chat.completions.create(model=…, messages=[{role:system,…},{role:user,…}], response_format={"type":"json_object"}, temperature=0)`, single attempt, no retries (Phase 6 owns hardening, R-9). Latency is measured client-side with `time.perf_counter()` because the SDK does not expose server-side timing; the measurement is the `ChatResponse.latency_ms` source of truth. `response.usage.{prompt_tokens, completion_tokens}` maps to `{"prompt": …, "completion": …}` (empty dict if `usage is None`).
- **Honest error translation.** `openai.OpenAIError` (the SDK base class) and `TimeoutError` are caught at the SDK boundary and re-raised as `ChatProviderUnavailableError`. The existing D-035 grading path (`FallbackMode.PROVIDER_UNAVAILABLE`) handles the failure with no retry and no repair. Anything outside `openai.*` keeps propagating — programmer errors are not graded fallbacks.
- **Canonical chat model.** `chat_model = "gpt-4.1"` is the canonical Slice 4.5 contour. Quality-first founder choice (same discipline as D-024's `text-embedding-3-large` pick); a future packet may add a second backend or a tier knob.
- **Settings + factory.** `Settings.chat_backend: Literal["mock", "openai"]` (default `"mock"`); `Settings.chat_model` becomes load-bearing for the openai backend (the mock continues to ignore it). `build_chat_client(settings)` adds an `openai` branch that constructs `OpenAIChatClient(api_key=settings.openai_api_key, model_name=settings.chat_model)`; the mock branch is unchanged. The factory is the single point both the boot gate and the webhook dispatcher route through, so the two paths cannot disagree.
- **Boot gate (R-10) extended.** `app._verify_chat_contour(settings)` now asserts, when `chat_backend == "openai"`, that `chat_model == "gpt-4.1"` (else `BootHealthError("chat model mismatch: …")`); the existing `build_chat_client(settings)` call surfaces the missing-API-key `ValueError` through `BootHealthError`; the non-empty `model_name` check from D-034 is unchanged. The boot log line (`app.created`) gains `chat_model=…` so an operator sees which chat model the service booted with.
- **`.env.example`.** The Chat contour stanza documents `CHAT_BACKEND` accepts `mock|openai`; the canonical `CHAT_MODEL=gpt-4.1` ships as the default value. `CHAT_BACKEND` default stays `mock` so a local boot without credentials remains clean.
- **No live calls in CI.** `tests/test_chat_client_openai.py` mirrors `tests/test_embedding_client_openai.py`: gated by `DIARY_RAG_OPENAI_TEST_KEY` and skipped by default. `make check` never makes a real OpenAI call.

### Why
D-034 left the chat seam callable only by the deterministic mock. D-036 closed the Telegram-side rendering of `answer_text`. The remaining gap to a real grounded answer is one concrete chat adapter behind the existing seam. The smallest validation-driven step is to mirror the D-024 pattern verbatim: one adapter file, one factory branch, one boot-gate clause, one canonical model, no quality-tuning knobs. Bundling retries / rate-limit / cost tracking would mix this packet with Phase 6 provider hardening; bundling a second provider would mix it with a tier-knob design.

### Consequence
- Closes **A-9** (canonical `CHAT_MODEL`): `gpt-4.1` locked under `chat_backend=openai`; boot abort on mismatch.
- R-10 in `docs/RUNTIME-INVARIANTS.md` tightened in place with a Slice 4.5 stanza (canonical chat model + `OPENAI_API_KEY` requirement under openai backend); D-034's non-empty `model_name` clause is unchanged.
- New runtime dependencies: none. The `openai` SDK is already pulled in by D-024.
- New: `src/diary_rag/adapters/answers/openai_client.py`, `tests/test_chat_client_openai.py`, `tests/test_boot_chat_gate.py`.
- Changed: `src/diary_rag/adapters/answers/factory.py` (openai branch); `src/diary_rag/adapters/answers/__init__.py` (re-export `OpenAIChatClient`); `src/diary_rag/config.py` (`chat_backend` Literal widening); `src/diary_rag/app.py` (`_verify_chat_contour` extension; `_CANONICAL_OPENAI_CHAT_MODEL`; `app.created` log line); `.env.example` (canonical `CHAT_MODEL`); `docs/decision-log.md`, `docs/RUNTIME-INVARIANTS.md`, `docs/RUNBOOK.md`, `docs/execution-map.md`, `docs/assumptions.md`, `docs/todo.md`.
- No schema change. No migration. A-34 destructive-upgrade discipline does not apply.
- `MockChatClient` unchanged — honest-provenance discipline preserved.
- Out of scope (unchanged or deferred): Telegram answer rendering / `/sources` / dispatcher (D-036, already landed); retries / backoff / circuit breakers (Phase 6); dead-letter / repair loops (Phase 6); rate-limit awareness, request hashing, cost tracking (Phase 6 / Phase 7); streaming, multi-turn, tool-use; Anthropic or any second provider; provider observability expansion beyond the existing `chat_backend` / `chat_model` log fields; `confidence_band` schema work (still deferred per D-035); live OpenAI calls inside `make check` (smoke stays env-gated); `RouteKind.ENTRY → NOTE` / `DiaryEntry` / `family_id` / `diary_rag` package renames (D-026); migration tooling / DDL changes (A-34); metadata filtering / Slice 3.4; search-quality fork (BM25 / reranker / Qdrant / halfvec / HNSW).

---

## D-038 — Retrieval-quality inspection harness against the D-025 baseline (modes: mock + Postgres)

### Decision
Slice 3.6 stands up a hand-curated, operator-runnable inspection harness so the next quality-decision packet ("search-quality fork" in `docs/todo.md`) can pick **one** lever (BM25 via `pg_search` / `bm25_catalog` / app-side BM25, **or** a reranker / cross-encoder, **or** Qdrant / a dedicated vector / search system, **or** multilingual sparse tuning beyond `simple`, **or** A-36b halfvec(3072) + HNSW) on evidence rather than intuition. Per the baseline-vs-quality discipline, this packet is the **baseline-measurement seam** and is separate from the first quality-lever experiment that will follow it.

- **Two modes, one metric shape.**
  - `mock` — offline, deterministic; constructs `MockDiaryStore` + `MockEmbeddingClient` in-process; runs under `make check` as a pure-shape sanity check via `tests/test_retrieval_harness_shape.py`. **No quality thresholds, no quality assertions.**
  - `postgres` — operator-run, env-gated by `DIARY_RAG_PG_TEST_DSN` (mirrors `tests/test_search_repository_postgres.py`); truncates the four ingest tables and re-ingests the fixture corpus through `DiaryService.ingest`; runs `SearchRepository.dense_candidates` + `sparse_candidates` + service-layer RRF exactly the way `QueryService` does.
- **Gold-set handle contract.** Each `expected_handles` entry in `eval/retrieval/gold.json` is `f"{external_message_id}#{event_index}"`. **`event_index` is the 0-based ordinal of the produced `EventChunk` within the source message after canonical `parse_diary_entry` + chunking by `DiaryService.ingest`** — it is not a business event id, not a Telegram message id, and not any external domain identifier. The handle exists only because `chunk_id` is uuid4 at ingest time and so cannot be pinned in the gold file directly; the harness resolves each handle to a live `chunk_id` after ingest.
- **Metric shape (identical across both modes).** Aggregate: `recall_at_5`, `recall_at_10`, `recall_at_20`, `mrr_at_20`, plus `per_leg_recall_at_20.{dense,sparse,fused}` so the report distinguishes "dense is weak", "sparse is weak", or "RRF order is wrong". Per-query: the three legs' top-`candidate_k` chunk-id lists, the three diagnostic per-leg first-relevant-rank fields (`first_relevant_rank_in_{dense,sparse,fused}`), the explicit `reciprocal_rank_in_fused: float` numerator (so the `mrr@20` aggregate is recomputable column-wise), and `recall_at_{5,10,20}`.
- **Pinned query embeddings.** `eval/retrieval/embeddings_cache.json` holds `text-embedding-3-large` @ 3072-dim outputs for every distinct gold-query text plus the `model_name` / `dimension` for honest provenance, checked at load time. The cache makes the Postgres run reproducible without contacting OpenAI on the query side. A separate operator-only `regenerate_embeddings.py` refreshes it; the script refuses to overwrite without `--force` because regenerating invalidates prior baseline snapshots.
- **Inspection, not gate.** No "must beat X" criterion is introduced and the CLI exit code is always `0`. The operator-produced baseline snapshot is captured in the Consequence section below — once the operator runs Postgres mode and pastes the observed numbers. Future quality-lever packets reference this snapshot as observed values for the D-025 contour, not as a threshold.

### Why
D-025 landed the canonical hybrid contour (Postgres dense exact-scan over `vector(3072)` + Postgres FTS `simple` + service-layer RRF) and the system became evaluable, but no measurement seam existed: the top backlog item "search-quality fork" could only be chosen by intuition. The harness is the smallest validation-driven step that produces honest, reproducible numbers against the real D-025 path; bundling a quality lever into the same packet would violate the discipline that baseline measurement and quality experiment are separate decisions.

The two-mode split mirrors the existing opt-in pattern (`DIARY_RAG_PG_TEST_DSN` gating already used by `test_search_repository_postgres.py`, `test_postgres_store.py`, `test_storage_query_traces.py`, `test_storage_answer_traces.py`). Mock mode runs in CI because the plumbing must not silently rot; Postgres mode is operator-deliberate because a real measurement involves live OpenAI corpus embedding and a dedicated eval DB.

### Consequence
- Closes nothing automatically. Opens nothing new in `docs/assumptions.md` — the metric shape, handle scheme, and cache-regenerate policy are packet-level contract decisions captured here.
- `docs/INVARIANTS.md` and `docs/RUNTIME-INVARIANTS.md` are not touched — the harness does not change what code enforces.
- New: `src/diary_rag/eval/__init__.py`, `src/diary_rag/eval/retrieval/__init__.py`, `src/diary_rag/eval/retrieval/harness.py`, `src/diary_rag/eval/retrieval/__main__.py`, `src/diary_rag/eval/retrieval/regenerate_embeddings.py`, `eval/retrieval/gold.json`, `eval/retrieval/corpus.jsonl`, `tests/test_retrieval_harness_shape.py`.
- Changed: `docs/decision-log.md`, `docs/RUNBOOK.md`, `docs/execution-map.md`, `docs/todo.md`. The "search-quality fork" backlog item is narrowed to "pick **one** quality variant and measure against the D-038 baseline; do not bundle more than one".
- New runtime dependencies: none.
- No schema change, no migration, no boot-gate change. A-34 destructive-upgrade discipline does not apply.
- `eval/retrieval/embeddings_cache.json` is **not** committed by this packet — it is produced by the operator-only `regenerate_embeddings.py` ritual against live OpenAI. The Postgres-mode CLI refuses to start if the cache is missing.
- **Baseline snapshot (observed):** *to be filled in by the operator-run Postgres-mode measurement and pasted here verbatim from the CLI's `--json` output. Aggregate fields (`recall_at_5`, `recall_at_10`, `recall_at_20`, `mrr_at_20`, `per_leg_recall_at_20.{dense,sparse,fused}`) plus 2–3 illustrative per-query rows. Framed as observed values for the D-025 contour, not as a must-beat threshold.*
- Out of scope (unchanged or deferred): any retrieval-behavior change in `services/retrieval.py` or `storage/search_repository.py`; live OpenAI calls inside `make check`; hard-threshold assertions or any quality gate; the first quality-decision packet (BM25 / reranker / Qdrant / halfvec / multilingual sparse); Slice 3.4 metadata filtering; schema / DDL / migration changes; nDCG / graded-relevance metrics (gold is binary); multi-snapshot tracking across operator runs; wiring the harness through `QueryService.answer` end-to-end; the `RouteKind.ENTRY → NOTE` / `DiaryEntry` / `family_id` / `diary_rag` package renames (D-026).

---

## D-039 — Language-aware sparse FTS via dual-config tsvector union (russian + english); A-37 resolved

### Decision
The milestone has selected language-aware sparse retrieval as the first quality lever on top of the D-025 baseline contour. This packet is **docs-only**: it records the mechanism and why it wins; the schema/code change lands as the follow-on implementation packet (execution-map Slice 3.7), and only after the operator has captured the D-038 Postgres baseline snapshot.

The sparse leg moves off the `simple` dictionary (A-37) to a **dual-config tsvector union** over the two stock Postgres built-in text-search configurations.

- **Ingest.** The generated stored column becomes `event_chunks.chunk_text_tsv tsvector GENERATED ALWAYS AS (to_tsvector('russian', chunk_text) || to_tsvector('english', chunk_text)) STORED`. The GIN index kind on the column is unchanged.
- **Query.** `SearchRepository.sparse_candidates` builds `websearch_to_tsquery('russian', $q) || websearch_to_tsquery('english', $q)`, matches with `@@`, and ranks with `ts_rank_cd` — the existing ordering and `created_at, event_index` tie-breakers are preserved.
- **Ingest-time language-detection rule: none.** Every chunk is indexed under both configs unconditionally. No `language` / `locale` column, no language detector, no new dependency.
- **Query-side language-matching rule: none.** Every query is parsed under both configs and the two `tsquery` values OR-combined. No per-query language guess.
- **Rejected alternatives.** Keep `simple` — no stemming, so inflected forms miss (`ходил` ↛ `ходить`, `магазины` ↛ `магазин`); fails the milestone's quality goal. Per-chunk detected-language config — needs a language detector, and diary lines are short and frequently script-mixed, so a mis-detection silently indexes a line under the wrong stemmer; also needs a new `chunk_language` column. `pg_trgm` trigram leg — a different mechanism class (trigram similarity, not stemmed lexeme matching), weaker long-form recall, extra extension; not language-aware FTS.

### Why
A-37 deliberately deferred multilingual sparse tuning; D-038 then stood up the baseline measurement seam. `simple` does no stemming, so inflected forms — most visibly in heavily inflected Russian — miss. Language detection is the fragile part of any per-language scheme: diary lines are short and frequently mix Russian and English in one line, so any detector mis-classifies a non-trivial share of them. The dual-config union sidesteps detection entirely — every chunk and every query is processed under both stemmers and the results unioned — while still giving stemmed recall in both languages. `russian` and `english` are stock Postgres 16 built-in text-search configurations, so the mechanism needs no extension, no new column, and no new dependency, consistent with the simple/deterministic preference.

Per the baseline-vs-quality discipline this packet is docs-only and separate from the implementation packet. The operator must record the D-038 Postgres baseline snapshot **first**; only then may the Slice 3.7 implementation packet land and be measured against that snapshot.

### Consequence
- Closes **A-37** (sparse text-search dictionary). A-37 in `docs/assumptions.md` is converted to a `→ D-039` pointer and listed under "Recently closed"; the A-37 row in `docs/assumption-audit.md` is struck and marked `Closed → D-039`. No new assumption is opened — the mechanism contract is recorded here, in the decision log, not in `assumptions.md`.
- No code, no schema, no migration, no new dependency in this packet — docs only. `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` are not touched: nothing code-enforced changes.
- `docs/product/TechSpec.md` and `docs/RUNBOOK.md` are not touched: their "multilingual sparse tuning / A-37 deferred to the next quality-decision packet" wording stays accurate while the sparse-leg behavior in code is unchanged. The Slice 3.7 implementation packet updates TechSpec §9 and the RUNBOOK hybrid-retrieval section when behavior actually changes.
- Names the follow-on implementation packet (execution-map Slice 3.7): it will change the generated-column expression in `src/diary_rag/storage/postgres/schema.sql`; change the `tsquery` construction in `src/diary_rag/storage/postgres/store.py` `sparse_candidates`; preserve mock + sqlite parity (mock deterministic; sqlite `sparse_candidates` still raises `NotImplementedError`); A-34 destructive-upgrade discipline applies (the generated-column expression change requires `docker compose down -v`); re-run the D-038 harness in Postgres mode and compare to the recorded baseline snapshot.
- Accepted costs, to be confirmed by the Slice 3.7 harness re-measurement: the `chunk_text_tsv` column and its GIN index roughly double in size (two configs unioned); rare cross-language stem collisions add minor ranking noise.
- Out of scope (unchanged or deferred): all code / schema / DDL / migration changes (those land in Slice 3.7); the operator-run D-038 baseline capture itself; BM25 via `pg_search` / `bm25_catalog` / app-side BM25; reranker / cross-encoder; Qdrant or any external vector / search system; A-36b halfvec(3072) + HNSW; Slice 3.4 metadata filtering; nDCG / graded-relevance metrics; harness corpus / gold-set changes; `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` changes; the `RouteKind.ENTRY → NOTE` / `DiaryEntry` / `family_id` / `diary_rag` package renames (D-026).

---

## D-040 — Date-range retrieval filter: optional inclusive `entry_date` bound on both hybrid legs (Slice 3.4, metadata-filter dimension 1 of 3)

### Decision
Slice 3.4 layers metadata filtering onto the D-025 baseline `SearchRepository` legs without changing the retrieval shape or the service-layer RRF contract. Slice 3.4 names three filter dimensions beyond the already-enforced family scope — child, visibility, date — and this packet ships **only the date dimension**. `child_id` filtering and `visibility_scope` filtering remain separate follow-on packets; visibility waits on A-15 (visibility-scope enumeration).

- **Value object.** A channel-neutral, frozen/slotted `DateRange(start, end)` in `src/diary_rag/core/diary/models.py` carries an inclusive `entry_date` lower/upper bound. Both bounds are `date | None`; either side may be omitted. A both-`None` range is a valid no-constraint object. `start > end` is contradictory and rejected at construction; equal bounds (a single-day range) are valid.
- **Seam.** `SearchRepository.dense_candidates` and `sparse_candidates` each gain one keyword-only parameter `date_range: DateRange | None = None`. `None` (the default) emits no predicate, so the existing retrieval shape, the RRF inputs, and every current call site are unchanged. Keyword-only keeps the optional refinement off the positional list and leaves room for the child/visibility dimensions to be added the same way.
- **Backends.** Postgres composes a conditional `entry_date >= / <=` SQL fragment with positional params on both leg queries, spliced after the existing `WHERE` predicates and before `ORDER BY`. The mock backend applies the identical deterministic inclusive comparison so mock/Postgres stay at behavioral parity. SQLite updates the signature for `HybridDiaryStore` Protocol parity but still raises `NotImplementedError` (D-022 / D-025).
- **Service.** `QueryService.answer` gains a per-call keyword-only `date_range` parameter threaded to both leg calls. The parameter is present and honored end-to-end; there is no inbound Telegram date syntax / natural-language date parsing yet — the webhook passes no `date_range`. A future inbound-expression packet parses the message and supplies `date_range` here.

### Why
Slice 3.4's three remaining filter dimensions do not share a blocker. Visibility filtering depends on `visibility_scope` semantics that are still an open assumption (A-15); child filtering depends on a yet-unimplemented `Query.child_scope` story. Date has neither: `entry_date` is already present on `EventChunk` and `DiaryEntry`, so the filter needs **zero schema change**, and it directly unlocks a user-facing capability ("what happened last week"). It is also the natural place to establish the optional-filter seam on the two legs so the later child/visibility filters become purely additive packets. A keyword-only parameter defaulting to `None` guarantees the D-025 retrieval shape, the RRF contract, and the eval harness are untouched, matching TechSpec §9 where date constraints are explicitly parked for Phase 3.4. This records a packet-level contract decision (the filter-seam shape), not an open assumption.

### Consequence
- `SearchRepository` Protocol signature widens on both legs (keyword-only, back-compatible). All three concrete backends adopt the identical signature.
- No schema / DDL / migration change. A-34 destructive-upgrade discipline does not apply.
- `services/retrieval.py` (RRF) is untouched — it fuses whatever filtered candidate lists the legs return. The eval harness (`src/diary_rag/eval/retrieval/harness.py`) is unaffected: the new parameter defaults to `None` and the harness never filters by date.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` are not touched — the date filter narrows candidates within an already family-scoped result; it changes no code-enforced invariant. `docs/assumptions.md` is not touched — the filter-seam shape is recorded here as a decision, not opened as an assumption.
- New: `tests/test_diary_models.py` (`DateRange` validation). Changed: `docs/product/TechSpec.md` §9, `docs/execution-map.md` row 3.4, `docs/todo.md`.
- New runtime dependencies: none.
- Out of scope (unchanged or deferred): `child_id` filtering and `visibility_scope` filtering (metadata dimensions 2 and 3; visibility waits on A-15); Telegram-side date syntax / natural-language date parsing for `/ask`; SQLite real retrieval (still `NotImplementedError` per D-025; signature-only here); any schema / DDL / migration change; retrieval-quality tuning and date-diversity reranking (TechSpec §9 "Context policy"); `Query` row schema changes (including `child_scope` and deferred `RetrievalHit` columns); the `RouteKind.ENTRY → NOTE` / `DiaryEntry` / `family_id` / `diary_rag` package renames (D-026).

---

## D-041 — Generic shared-memory core: canonical `community` / `subject` vocabulary

### Decision
The canonical product is a **generic shared-memory / note-grounded answer service**: it captures notes into a durable corpus and answers natural-language questions grounded only in retrieved evidence from that corpus. It serves both an **individual-memory (solo)** use case and a **shared/group** use case under one core model. The family/child diary in Telegram is the **first implemented** use case — the shared/group shape of that model — and TheyGrow is a later **integration host**, not the product's definition.

This packet is **docs-only**: it reframes the top-line product framing and records the canonical core vocabulary. No code, schema, test, or `src/` token change.

- **Canonical core vocabulary.**
  - **community** — the outer scope that owns a note corpus and bounds retrieval and authorship. A community has **one or more** participants, so a single-participant solo memory and a multi-participant shared corpus are the same concept at different sizes; a one-person community is the normal solo case, not a degenerate one.
  - **subject** — a sub-entity within a community that a note can be *about*.
  - These are the destination terms for the "explicit renaming packet" that D-026 promised but left without a named target.
- **First-use-case scope mapping.** In the first implemented use case a `family` is one community and a `child` is one subject. Use-case nouns (`family`, `child`, `parent`) stay in use-case-facing prose; `community` / `subject` are the core terms.
- **D-026 boundary rule extended.** D-026 said new core code must avoid use-case vocabulary "where a generic name fits"; this decision fixes the generic names. New **core** code adopts `community` / `subject` for the outer-scope and sub-entity concepts rather than ad-hoc generic names.
- **Relation to prior decisions.** D-001 (Telegram-first, TheyGrow-later) and D-002 (Standalone Diary Memory Service) remain valid; this decision contextualizes them as, respectively, the first event-source/host pairing and the first surfaced shape of the generic core. They are not retired — the same way D-026 generalized D-001/D-015 without retiring them.

### Why
D-026 separated the use case from the core and named the parents/family-diary framing as the first use case, but it gave no canonical noun for the outer scope or the sub-entity, so its promised "explicit renaming packet may revisit them" had no destination — every later rename would have to re-litigate the target words. Naming `community` / `subject` now fixes that destination once, so subsequent packets rename against a settled target. Defining `community` as one-or-more participants keeps the solo and shared use cases on a single model instead of forking the core. The top-line "Diary RAG Service for TheyGrow" framing in the PRD/BuildPlan titles still presents the first use case and a future host *as* the product; reframing the titles aligns the canonical docs with D-026's own stated intent.

This is the milestone's "Decision + top-tier product reframe" packet (1/3). It defines *what* the product is and *which words* are canonical; it deliberately does not schedule the identifier-level rename roadmap — that is a later packet of the same milestone.

### Consequence
- `docs/product/PRD.md` and `docs/product/BuildPlan.md` reframed: H1 titles and top-line product name describe the generic shared-memory / note-grounded answer service; the family/child diary is named as the first implemented use case and TheyGrow as a later integration host. PRD §1 / §3 state both the solo and shared/group use cases; a short Terminology note defines `community` / `subject`. No product scope change.
- Canonical vocabulary `community` / `subject` recorded. New core code adopts them; this extends, and does not relax, the D-026 boundary rule.
- D-001, D-002, and D-026 are not edited in place — this decision references and contextualizes them.
- `docs/assumptions.md` is not touched: choosing `community` / `subject` is a settled contract decision recorded here, not an open assumption.
- **Deferred to a later packet of this milestone:** the itemized, ordered, non-destructive migration path for internal identifiers — `family_id`, `child_id`, `DiaryEntry`, `entry_date` / `entry_text`, `parse_diary_entry`, `DiaryRepository`, the `diary_rag` package, `RouteKind.ENTRY` / `detected_route='entry'`. This decision names the destination only; it does not rename anything.
- **Deferred:** vocabulary alignment of `docs/ARCHITECTURE.md`, `docs/INVARIANTS.md`, `docs/RUNTIME-INVARIANTS.md`, `docs/product/TechSpec.md`, `AGENTS.md`, `CLAUDE.md`, and `docs/execution-map.md`.
- No code, schema, migration, test, dependency, or `src/` token change. No roadmap or scope commitment. D-026's adapter axes and boundary rules are unchanged, only extended with the named vocabulary.
- Out of scope (unchanged or deferred): all identifier / schema / package renames (own packet); A-14 (community/subject bootstrap) and A-21 (TheyGrow integration surface) stay open; the supporting-doc reframes named above; any code or test change.

---

## D-042 — Identifier-renaming roadmap: non-destructive path to `community` / `subject` identifiers

### Decision
D-026 promised an "explicit renaming packet" for the diary-shaped internal identifiers; D-041 named the destination vocabulary (`community` / `subject` / `participant`) but deferred the itemized, ordered, non-destructive migration path to a later packet of the same milestone. This decision is that packet (3/3).

This packet is **docs-only**: no code, schema, migration, test, or `src/` token change. It records the renaming roadmap and creates `docs/RENAMING-ROADMAP.md` as the detailed design artifact. D-041 is not edited in place.

D-042 fixes, at contract level, **only**:

- **Rename scope and surfaces.** The renaming scope is D-041's deferred identifier set: `family_id`, `child_id` (prospective — not present in code today), `DiaryEntry`, `entry_date` / `entry_text`, `parse_diary_entry`, `DiaryRepository`, the `diary_rag` package, and `RouteKind.ENTRY` / `detected_route='entry'`, together with the directly entailed surfaces enumerated in `docs/RENAMING-ROADMAP.md` (the `diary_entries` table, `diary_entry_id`, `ParsedEntry`, `DiaryService`, the `*DiaryStore` classes, `HybridDiaryStore`, `_family_id_for`, the `core/diary/` module directory, the eval-harness `family_id` keys, and the diary-shaped config keys). `EventChunk` / `event_chunks` / `event_index` are explicitly **out of scope** — `event` is a generic term, not D-026 use-case vocabulary, and is absent from D-041's deferred list. Use-case-facing adapter prose (Telegram reply strings) may retain use-case nouns per the `docs/GLOSSARY.md` rule.
- **Primary migration strategy.** The rename is expected to land **before the first non-local deployment**, while all data is local and disposable. Schema-touching steps therefore use a **destructive local reset** (`docker compose down -v` for Postgres; fresh SQLite file), with data treated as seedable from scratch. The secondary path — an expand-contract dual-read/write migration via migration tooling — applies only if the rename slips past the first non-local deployment.
- **A-34 dependency rule.** A-34 (no migration tool; local schema upgrades are destructive) is **not a hard blocker** for this rename: the schema-touching steps ride the destructive-reset contour A-34 already documents. The *conditional* precondition is that no non-local deployment holding irreplaceable data exists when those steps run. If that precondition fails, the affected steps are blocked until A-34 is resolved with migration tooling and the strategy switches to expand-contract. A-34 stays open and is referenced one-directionally from the roadmap.
- **Definition of "rename complete".** The rename is complete when: (a) no core code, schema, migration, or test references a legacy identifier from the scope above, verified by a `grep` scoped to active surfaces (excluding negative tests and historical decision-log narration); (b) `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` wording names the new identifiers and matches what code enforces; (c) the `docs/GLOSSARY.md` "Identifiers" section lists the legacy names as historical with their live mapping; (d) `make check` is green and a fresh-environment bootstrap succeeds. Use-case-facing adapter prose retaining use-case nouns is explicitly not a blocker.
- **Detailed sequencing lives in `docs/RENAMING-ROADMAP.md`.** D-042 does **not** freeze a specific packet decomposition. It records the sequencing *constraints* and *prerequisites* — concept-by-concept atomicity (each packet renames one concept across all layers, avoiding cross-packet store-layer translation shims); schema-touching steps ride the destructive reset; invariants and canonical-docs alignment come last. The roadmap doc carries the current recommended packet sequence; future implementation planning may refine those packet boundaries provided D-042's scope, migration strategy, prerequisites, and completion bar are preserved, or amends D-042 with a new decision.

### Why
D-026 and D-041 deferred the itemized roadmap with no recorded scope, migration strategy, or completion bar, so each future rename packet would have to re-litigate them. Fixing those four things at the contract level — while leaving the exact packet boundaries to implementation-time planning — gives the future implementation milestone a stable frame without prematurely freezing a decomposition that has not yet been pressure-tested against the code. A concept-by-concept sequence is recommended because layer-by-layer packets would force a temporary store-layer field↔column translation shim between the type-rename and schema-rename steps; concept-by-concept keeps each step atomic and shim-free, and the pre-deployment destructive-reset decision makes per-concept schema resets cheap. Recording the roadmap as a decision, with the detail in a dedicated doc, keeps the decision-log entry stable while the roadmap doc stays a refinable design surface.

### Consequence
- New file `docs/RENAMING-ROADMAP.md`: purpose & status; identifier inventory and target-name mapping; the recommended packet sequence with preconditions and per-packet validation; prerequisites and the A-34 dependency rule; the migration-strategy options; and the "rename complete" definition.
- New D-042 entry. D-041, D-026, D-001, D-002 are not edited in place — D-042 references and builds on them.
- Target-vocabulary strength: `community` / `subject` / `participant` are canonical (D-041). `note` as the replacement for `entry` is the **current recommended target**, not canonized by this packet. The replacement core package name (for `diary_rag`) remains **proposed**, to be confirmed at execution time.
- No code, schema, migration, test, dependency, or `src/` token change. No identifier is renamed by this packet.
- `docs/assumptions.md` and `docs/assumption-audit.md` are not edited: the rename scope and migration strategy are settled contract decisions recorded here, not open assumptions; A-34 stays as-is.
- `docs/GLOSSARY.md`, `docs/INVARIANTS.md`, `docs/RUNTIME-INVARIANTS.md`, `docs/execution-map.md`, `docs/todo.md`, PRD / BuildPlan / TechSpec are **not** touched by this packet.
- Out of scope (deferred to the future implementation milestone): the actual rename of any identifier in code, schema, migrations, tests, configs, or scripts; resolution of A-34 (migration tooling); the INVARIANTS / RUNTIME-INVARIANTS enforcement-wording updates and the GLOSSARY "Identifiers" section update (performed inside the final docs-alignment packet of that milestone); adoption of `subject_id` for child scoping (handled by the deferred D-040 child-filter packet when it lands); any `docs/execution-map.md` / `docs/todo.md` rows for the renaming packets.

## D-043 — Three-stage development sequencing: operationalization gate between product baseline and quality/expansion

### Decision
The canonical build docs let work pass directly from a complete product baseline into quality/expansion work: `docs/product/BuildPlan.md` numbers Phase 5 (Optional AI Quality Boosters) ahead of Phase 6 (Provider Hardening), and the schema-migration gap (A-34), raw-data durability/backup (D-027), and evaluation/observability sit with no rule placing them before expansion. The only sequencing expressed today is fine-grained and local (the D-038 / D-039 baseline-vs-quality discipline inside Phase 3).

This decision adopts an explicit three-stage development sequencing model and records it as a contract. It is **docs-only**: no code, schema, migration, or test change. The model is an *overlay* — it does not renumber the existing Phase 0–9 structure.

D-043 fixes, at contract level, **only**:

- **The three stages.**
  1. **Stage 1 — Product baseline.** The end-to-end note → retrieve → grounded-answer product works.
  2. **Stage 2 — Operationalization / real infrastructure binding.** External provider integrations are production-safe, schema evolution is non-destructive, raw data is durable and recoverable, and system quality is measurable.
  3. **Stage 3 — Quality improvement / expansion.** Optional AI quality boosters, the privacy/visibility controls, and host-integration seams.
- **The stage → phase map.** Phases keep their existing numbers; the map — not the numbers — gives execution order.
  - Stage 1 = Phases 0–4.
  - Stage 2 = Phase 6 (provider hardening) + Phase 7 (evaluation & observability) + the raw-data durability/backup slices of Phase 8 + resolution of A-34 (schema-migration tooling).
  - Stage 3 = Phase 5 (optional AI quality boosters) + the access-control / visibility / audit / retention slices of Phase 8 + Phase 9 (host integration seams).

  Phase 8 deliberately spans Stage 2 and Stage 3; the slice-level split is recorded in `docs/execution-map.md`.
- **The operationalization gate.** No Stage-3 packet may start until Stage-2 exit criteria are met. This is the rule the previous docs lacked.
- **Per-stage exit criteria.**
  - *Stage 1 → 2:* Phase 4 Definition of Done holds — questions are answered from retrieved memory, answers degrade gracefully on weak evidence, no answer is produced without retrieval output.
  - *Stage 2 → 3:* provider failures do not corrupt durable state and retries/fallbacks are bounded and observable (Phase 6 DoD); schema upgrades are non-destructive (A-34 resolved with migration tooling); raw `SourceMessage` data has a backup window and a stronger-than-nightly recovery primitive (Phase 8 durability DoD, D-027); retrieval and answer quality are measurable and regressions are visible (Phase 7 DoD).
- **Phase numbers are documentation identifiers, not execution order.** Where a number and the stage map disagree — Phase 5 precedes Phases 6–8 numerically but follows them in execution — the stage map is the order of record.
- **Relationship to the existing baseline-vs-quality discipline.** The three-stage model is a coarse outer layer. It does **not** replace, rename, or supersede the fine-grained D-038 / D-039 baseline-vs-quality discipline (one quality lever per packet, measured against a recorded baseline). That discipline continues to govern packet-level work *within* a stage — including retrieval-tuning packets inside Phase 3, which remain Stage 1. "Stage 3 quality" names the Optional AI Quality Boosters phase plus the expansion phases; it does not reclassify Phase 3 retrieval work.

### Why
With no explicit gate, a baseline-complete system invites quality/expansion packets while provider integrations are still single-attempt, schema upgrades are still destructive (A-34), raw data has no backup contour, and quality is unmeasurable. Quality boosters layered on unhardened infrastructure produce work that is hard to operate and hard to evaluate. Naming an operationalization stage and gating expansion behind it makes the prerequisite ordering explicit instead of leaving it implied by phase numbers that happen to run the wrong way. Recording it as an overlay — rather than renumbering Phases 0–9 — keeps every existing decision-log, execution-map, and code reference to a phase number stable; the cost is the one-time statement that numbers are doc IDs and the stage map is the order of record. Evaluation/observability is placed in Stage 2 because operationalizing without measurability is not operationalization — Stage 3 decisions need a baseline to measure against.

### Consequence
- New D-043 entry. No earlier decision is edited in place.
- `docs/product/BuildPlan.md` gains a "Development Sequencing" section carrying the three-stage definitions, the stage → phase map, the operationalization gate, and the exit criteria; each `## Phase N` header gains a stage tag.
- `docs/execution-map.md` mirrors the stage tags on its phase headers, states that execution order follows the stage map rather than the phase numbers, annotates the Phase 8 slice-level Stage 2/3 split, and marks Stage-3 slices with the gate.
- `docs/todo.md` "pick next" discipline gains the gate; the "Schema evolution before non-local deployment" (A-34) and "Reconciliation for failed embeddings" items are reframed as Stage-2 operationalization items.
- `docs/RUNBOOK.md` canonical loop references the gate when picking the next item.
- `docs/product/TechSpec.md`, `docs/INVARIANTS.md`, and `docs/RUNTIME-INVARIANTS.md` are **not** touched: TechSpec describes runtime behavior and deployment shapes, not build order; the two invariants files record what the running system enforces, and development-stage sequencing is a process policy, not a system invariant.
- No code, schema, migration, test, or dependency change. A-34 stays open; this decision does not resolve it, only places its resolution in Stage 2.
- Out of scope (deferred): decomposing Stage 2 into concrete operationalization packets (migration tooling, provider-hardening slices, backup/recovery, eval expansion); embedding the gate into `AGENTS.md`'s pick-next / interaction contract; stage-status pointers in `README.md` / `QUICKSTART.md`.

## D-044 — Stage 2 operationalization decomposition: ordered `OP-1`..`OP-5` packet groups

### Decision
D-043 adopted the three-stage development-sequencing model and the operationalization gate, and named Stage 2's scope — Phase 6 (provider hardening) + Phase 7 (evaluation & observability) + the raw-data durability/backup slice of Phase 8 + resolution of A-34 (schema-migration tooling) — but **explicitly deferred** decomposing Stage 2 into concrete packets. Stage 2 is therefore named but unsequenced: five disparate work items (A-34, Phase 6, A-35 failed-embedding reconciliation, the Phase 8 raw-data durability slice, Phase 7) with no ordering, no recorded dependencies, and no per-item completion mapping. No Stage-2 execution packet can be picked deliberately until that decomposition exists.

This decision is that decomposition. It is **docs-only**: no code, schema, migration, infra, deployment, test, or `src/` change. It follows the D-042 precedent — the decision entry fixes the *contract*; the refinable sequence lives in a dedicated roadmap doc, `docs/OPERATIONALIZATION-ROADMAP.md`, created by this packet. D-043, D-042, and D-027 are not edited in place.

D-044 fixes, at contract level, **only**:

- **The five Stage-2 packet groups (prefix `OP-`, parallel to D-042's `R-`).**
  1. **OP-1 — Schema-migration tooling.** Resolves A-34: introduce a migration tool (Alembic or equivalent), capture the current bootstrap DDL as the baseline migration, replace the destructive local-upgrade contour with non-destructive versioned upgrades.
  2. **OP-2 — Provider hardening.** Phase 6 slices 6.1 (timeouts & bounded retries — R-9), 6.2 (dead-letter for failed indexing jobs), 6.3 (rate-limit handling).
  3. **OP-3 — Failed-embedding reconciliation.** Resolves A-35: retry `embedding_status='failed'` chunks with bounded backoff, route exhausted retries to OP-2's dead-letter surface, emit retry-outcome observability. Kept distinct from OP-2 because A-35 itself files it as "a future Phase-6 packet" and it *consumes* OP-2's primitives rather than defining them.
  4. **OP-4 — Raw-data durability & backup.** The Phase 8 raw-data durability/backup slice (D-027): daily backup window, stronger-than-nightly recovery primitive, A-40 mechanism + RPO/RTO selection.
  5. **OP-5 — Evaluation & observability.** Phase 7 slices 7.1 (gold eval set), 7.2 (retrieval & groundedness metrics), 7.3 (cost & latency).
- **The execution order and ordering constraints.** OP-1 → OP-2 → OP-3 → (OP-4 in parallel with OP-2/OP-3) → OP-5. The fixed constraints are: OP-1 ≺ {OP-2, OP-3, OP-4} (OP-2/OP-3 add persistent schema, OP-4 recovers into a schema-versioned database — all need non-destructive migrations first); OP-2 ≺ OP-3 (A-35's reconciliation consumes OP-2's bounded-backoff and dead-letter primitives); OP-5 closes Stage 2 (quality is measured against hardened infrastructure). The dependency rationale is recorded in `docs/OPERATIONALIZATION-ROADMAP.md` §4.
- **Per-group completion criteria, by reference.** OP-1 → A-34 resolved (D-043 Stage-2→3 exit clause "schema upgrades are non-destructive"); OP-2 → Phase 6 Definition of Done; OP-3 → A-35 resolved, governed by the Phase 6 Definition of Done; OP-4 → Phase 8 raw-data durability Definition of Done + A-40 closure (D-027); OP-5 → Phase 7 Definition of Done. D-044 re-authors none of these — every criterion points to the existing `docs/product/BuildPlan.md` heading.
- **What stays refinable.** The internal slice boundaries within each OP group are not frozen. Implementation-time planning may split or merge OP groups provided every resulting packet preserves **both** the OP-group ordering constraints above **and** the D-043 Stage-2 → Stage-3 operationalization gate. The current recommended sequence lives in `docs/OPERATIONALIZATION-ROADMAP.md`; a change that cannot preserve both must amend D-044 with a new decision.
- **The Stage-2 scope boundary.** OP-4 covers only the **Stage-2** raw-data durability/backup slice of Phase 8. The Stage-3 Phase 8 slices — community-scoped access control, the visibility model, export/delete, the audit log, and the retention policy — are **not** decomposed by D-044 and remain Stage 3, gated behind the operationalization gate.

### Why
D-043 deferred the Stage-2 decomposition with no recorded ordering, dependencies, or completion mapping, so each future Stage-2 packet would have to re-derive them. The five Stage-2 items are not independent: A-35's reconciliation is specified in terms of Phase 6's retry and dead-letter primitives, and both Phase 6's dead-letter surface and OP-3's reconciliation add persistent schema that A-34's destructive-upgrade contour makes unsafe to ship before the first non-local deployment. Fixing the packet groups, their ordering constraints, and their completion-by-reference at the contract level — while leaving the internal slice boundaries to implementation-time planning — gives the Stage-2 milestone a stable frame without prematurely freezing a decomposition that has not been pressure-tested against the code. Recording the roadmap as a decision with the detail in a dedicated doc keeps the decision-log entry stable while the roadmap doc stays a refinable design surface, exactly as D-042 did with `docs/RENAMING-ROADMAP.md`.

### Consequence
- New file `docs/OPERATIONALIZATION-ROADMAP.md`: purpose & status; Stage-2 scope and the Stage-3 out-of-scope boundary; the OP-1..OP-5 packet-group inventory; the recommended roadmap table with preconditions, exit-criteria-by-reference, and per-packet validation; the dependency graph and ordering rationale; the exit-criteria → Stage-2-gate mapping; the refinability rule.
- New D-044 entry. D-043, D-042, D-027 are not edited in place — D-044 references and builds on them.
- `docs/execution-map.md`: the Phase 6 and Phase 7 headers and the Phase 8 note gain `OP-` group tags and a roadmap pointer; the reserved Phase 8 Stage-2 raw-data durability slice row is added and mapped to OP-4. No phase is renumbered.
- `docs/todo.md`: the two existing Stage-2 items — "Schema evolution before non-local deployment (A-34)" and "Reconciliation for failed embeddings (A-35)" — are reframed as OP-1 and OP-3 with a roadmap pointer.
- `docs/assumptions.md`: A-34 and A-35 are annotated with the resolving OP group and a roadmap pointer. Both stay **open** — D-044 sequences their resolution, it does not resolve them.
- `docs/product/BuildPlan.md`: the "Development Sequencing" section gains a one-line pointer to `docs/OPERATIONALIZATION-ROADMAP.md` as the Stage-2 decomposition record. The Phase 6/7/8 Definitions of Done are referenced, not edited.
- No code, schema, migration, test, infra, or dependency change. A-34, A-35, and A-40 stay open; this decision only places and orders their resolution within Stage 2.
- `docs/product/TechSpec.md`, `docs/INVARIANTS.md`, `docs/RUNTIME-INVARIANTS.md`, `docs/RUNBOOK.md`, `AGENTS.md`, `README.md`, `QUICKSTART.md` are **not** touched — Stage-2 sequencing is process policy, not a runtime invariant, deployment shape, or vocabulary change.
- Out of scope (deferred): implementation of any OP group; the internal slice-level decomposition of each OP group; decomposition of Stage 3 (Phase 5, the Stage-3 Phase 8 slices, Phase 9); embedding the operationalization gate into `AGENTS.md`'s pick-next contract; stage-status pointers in `README.md` / `QUICKSTART.md`; resolution of A-34, A-35, and A-40.

## D-045 — OP-1.1: Postgres schema-migration tooling foundation (yoyo-migrations baseline + bootstrap rewiring)

### Decision
OP-1.1 is the **foundation packet** of the OP-1 group (D-044). It establishes the schema-migration foundation that every later non-destructive-upgrade packet depends on, and nothing more. It does **not** close OP-1 or resolve A-34: the OP-1 exit criterion requires a non-destructive schema-*changing* upgrade from a prior schema version to be demonstrated, and OP-1.1 introduces no upgrade migration beyond the baseline. OP-1 and A-34 stay open.

This is a packet-level contract decision; it follows the D-042 / D-044 precedent of recording packet-level shape choices in the decision log. It fixes:

- **Migration tool — `yoyo-migrations`.** Raw-SQL versioned migration files, a simple metadata table, an explicit migrate-to-head API/CLI. Chosen over Alembic: Alembic's distinguishing value is its SQLAlchemy-backed autogenerate / ORM surface, which this raw-`psycopg` adapter does not use, so Alembic would add SQLAlchemy as an unused transitive dependency. Chosen over a hand-rolled runner: that would be an implicit in-house migration framework to design, document, and maintain. yoyo's psycopg v3 backend is used (the `postgresql+psycopg` URI scheme), so no second Postgres driver is introduced.
- **Baseline migration.** `src/memory_rag/storage/postgres/migrations/0001.baseline-schema.sql` captures the retired `schema.sql` DDL verbatim. It introduces no schema change — a database created by the old raw-schema bootstrap and one created by applying the baseline are identical.
- **`schema.sql` retired.** The file is deleted and removed from the wheel packaging; it is no longer a runtime artifact or a packaged resource. The versioned migration history is the single canonical Postgres schema source. No parallel reference file replaces it.
- **Bootstrap rewiring.** `PostgresDomainStore.__init__` applies migrations to head via `migrations_runner.apply_migrations` instead of executing raw `schema.sql`. The call is idempotent — a database already at head is left untouched.
- **Adoption path.** A pre-existing local Postgres volume created from the old raw-schema bootstrap is brought into the versioned world by one explicit, documented, data-safe `stamp` step (`migrations_runner.stamp_baseline` / `python -m memory_rag.storage.postgres.migrations_runner stamp`), which marks only the baseline migration as applied without running its DDL. This is the **only** supported adoption path: the bootstrap performs no auto-detection of un-stamped volumes.

### Why
D-044 sequenced OP-1 as the lead Stage-2 group: OP-2's dead-letter surface and OP-3's reconciliation both add persistent schema, and OP-4 recovers into a schema-versioned database — all need non-destructive migrations first, and the destructive `docker compose down -v` contour (A-34) must be gone before the first non-local deployment. Landing the tool, capturing the current schema as the baseline, and rewiring the bootstrap is the smallest autonomous step that unblocks those packets without OP-1.1 itself having to design a real upgrade migration. Retiring `schema.sql` outright — rather than keeping it as a non-canonical reference — removes a confusable second schema surface during the very packet whose purpose is to establish a single source of truth; a generated schema snapshot, if ever wanted, is a separate later artifact derived from the migrations.

### Consequence
- New: `src/memory_rag/storage/postgres/migrations/0001.baseline-schema.sql` (baseline migration); `src/memory_rag/storage/postgres/migrations_runner.py` (`apply_migrations`, `stamp_baseline`, migration discovery, an `apply` / `stamp` CLI); `tests/test_postgres_migrations.py` (offline discovery + PG-DSN-gated fresh-bootstrap / idempotency / adoption-stamp / store-constructor tests).
- Changed: `src/memory_rag/storage/postgres/store.py` (bootstrap rewired to `apply_migrations`; the two-phase boot pool and `_load_schema_sql` removed); `pyproject.toml` (`yoyo-migrations` runtime dependency; wheel `force-include` switched from `schema.sql` to the `migrations/` directory; `yoyo.*` mypy override); `uv.lock`.
- Deleted: `src/memory_rag/storage/postgres/schema.sql`.
- Docs: this D-045 entry; `docs/assumptions.md` (A-34 reframed — still open; A-33 bootstrap clause corrected); `docs/RUNBOOK.md` (the destructive-upgrade section replaced with the versioned-migration + `stamp` adoption flow); `docs/execution-map.md` (Slice 2.0 artifacts + a new OP-1 section); `docs/OPERATIONALIZATION-ROADMAP.md` (OP-1.1 recorded as the landed OP-1 foundation); `docs/todo.md` (OP-1 reframed to record OP-1.1 done).
- **OP-1 and A-34 remain open.** The OP-1 exit criterion — a fresh bootstrap *and* a non-destructive schema-changing upgrade from a prior schema version both succeeding without a destructive reset — is only half-exercised: OP-1.1 has no upgrade migration beyond the baseline. A later packet that introduces and validates a real upgrade migration completes OP-1 and resolves A-34.
- SQLite is unchanged: it is not migration-managed; its embedded DDL still bootstraps on a fresh DB file (out of scope per D-044 and this packet).
- Out of scope (deferred): any schema-changing upgrade migration; new tables / columns / indexes / constraints; auto-detection / auto-adoption of un-stamped volumes; a generated human-readable schema snapshot; a schema-version boot health check (R-10's promissory wording is left untouched); SQLite migration handling.

## D-046 — OP-1.2: first non-destructive schema-changing upgrade migration (0002 — `event_chunks` `embedding_status` index)

### Decision
OP-1.2 is the **completing packet** of the OP-1 group (D-044). It adds the first versioned migration that changes the Postgres schema beyond the D-045 baseline and validates that the upgrade is non-destructive over populated data. With this packet's validation passing, **OP-1 is complete and A-34 is resolved**: a fresh-environment bootstrap and a non-destructive schema-*changing* upgrade from a prior schema version both succeed without a destructive volume reset. It fixes:

- **Upgrade migration `0002`.** `src/memory_rag/storage/postgres/migrations/0002.index-embedding-status.sql` carries a single additive, non-destructive change — `CREATE INDEX IF NOT EXISTS idx_event_chunks_embedding_status ON event_chunks(embedding_status)`. Plain (not `CONCURRENTLY`), so it runs inside yoyo's per-migration transaction; the index name follows the `idx_event_chunks_*` convention of the baseline. No `ADD COLUMN`, no new table, no data read/rewrite/drop — applying it leaves every existing row untouched.
- **Index purpose.** The index backs the already-documented A-35 / RUNBOOK operator probe (`SELECT ... FROM event_chunks WHERE embedding_status = 'failed'`), which otherwise performs a sequential scan. No application logic consumes the index in this packet; the failed-embedding reconciliation scan that would query it is an OP-3 concern.
- **Non-destructive upgrade proof.** `tests/test_postgres_migrations.py` exercises the upgrade end-to-end against a live Postgres: 0001 applied on a clean DB with realistic `source_messages` / `notes` / `event_chunks` data, then 0002 applied — the index appears and all pre-existing rows survive; the same proof is repeated for a stamp-adopted (pre-OP-1.1) volume; `PostgresDomainStore` bootstrap is confirmed to bring a DB to 0002.

### Why
D-045 landed the migration tooling foundation but shipped no schema-changing migration, so the OP-1 exit criterion — a non-destructive upgrade from a prior schema version succeeding without a volume reset — was only half-exercised, and OP-1 / A-34 stayed open. OP-1.2 closes that half with the smallest meaningful additive change. An index on `event_chunks(embedding_status)` was chosen because it is genuinely additive and reversible-by-omission, needs no data backfill, and serves a real operator query that already exists in the RUNBOOK — so the first upgrade migration both proves the mechanism and earns its keep, without pulling forward OP-2/OP-3 scope (dead-letter surface, reconciliation job) or touching SQLite.

### Consequence
- New: `src/memory_rag/storage/postgres/migrations/0002.index-embedding-status.sql` (the upgrade migration).
- Changed: `tests/test_postgres_migrations.py` (discovery tests expect 0001 + 0002; new gated tests for the non-destructive 0001→0002 upgrade over populated data, the stamp-adopted-volume upgrade, and store-constructor bootstrap to 0002).
- No change to `migrations_runner.py`, `store.py`, or `pyproject.toml` — the runner already discovers and applies the whole `migrations/` directory, the bootstrap already migrates to head, and the wheel `force-include` already packages the directory.
- Docs: this D-046 entry; `docs/assumptions.md` (A-34 closed); `docs/assumption-audit.md` (A-34 row struck through → D-046); `docs/RUNBOOK.md` (schema-migrations section gains a worked 0002 upgrade example); `docs/OPERATIONALIZATION-ROADMAP.md` and `docs/execution-map.md` (OP-1 marked complete, OP-1.2 recorded); `docs/todo.md` (OP-1.2 done, OP-1 closed).
- **OP-1 is complete and A-34 is resolved.** The destructive `docker compose down -v` upgrade contour is fully retired for Postgres.
- SQLite is unchanged: it is not migration-managed; its embedded DDL still bootstraps on a fresh DB file (out of scope per D-044, D-045, and this packet).
- **A-35 stays open** — it is resolved by OP-3, not by this packet. OP-1.2 only adds the index that a future reconciliation scan can use.
- Out of scope (deferred): any application logic consuming the index (OP-3); `ADD COLUMN`, new tables, a dead-letter surface, reconciliation/retry jobs, backup/recovery (OP-2/OP-3/OP-4); down/rollback migrations and reversibility tests; SQLite or other non-Postgres migrations; Slice 2.6 `parse_status` / `index_status` columns.

## D-047 — OP-2.1 / Slice 6.1: explicit timeouts, bounded retries, and error classification on the OpenAI provider adapters (R-9)

### Decision
Slice 6.1 is the **foundation packet** of the OP-2 group (D-044). Within OP-2 the roadmap orders 6.1 → 6.2 → 6.3; 6.1 enforces R-9 (*"Provider calls have explicit timeouts and bounded retries. There is no unbounded wait or unbounded retry loop in any handler."*) for every external provider call, so 6.2's dead-letter surface and 6.3's rate-limit policy have a bounded-retry primitive to build on. Before this packet both OpenAI adapters were single-attempt with no explicit timeout (and the SDK's own default `max_retries=2` silently applied), so R-9 was declared but not enforced. This is a packet-level contract decision; it follows the D-045 / D-046 precedent of recording packet-level shape choices in the decision log. It fixes:

- **Shared adapter-side primitive — `src/memory_rag/adapters/resilience.py`.** `RetryPolicy` (frozen dataclass: `timeout_seconds`, `max_attempts`); `OutcomeClass` (`StrEnum`: `success` / `retryable_failure` / `non_retryable_failure`); `classify_openai_error` (OpenAI-aware classifier); `run_with_retries` (a provider-agnostic bounded loop — OpenAI specifics enter only through the injected `classify` callable). It lives under `adapters/` because importing the provider SDK is an adapter concern (Invariant I-11); core code never sees it.
- **Error classification.** Retryable: request timeouts (`openai.APITimeoutError`, builtin `TimeoutError`), connection errors (`openai.APIConnectionError`), 5xx (`openai.InternalServerError`), and rate limits / 429 (`openai.RateLimitError`). Non-retryable: every other `openai.OpenAIError` (auth, bad request, other 4xx) and any unrecognized exception — fail fast rather than retry blind.
- **No specialized waiting in 6.1.** A retryable failure is retried immediately; there is no inter-attempt delay. 429 is *classified* retryable but rate-limit-aware backoff (exponential delay, jitter, honoring `Retry-After`) is Slice 6.3. Worst-case bounded wall time for one call is `timeout_seconds * max_attempts`.
- **Two `Settings` knobs.** `provider_timeout_seconds` (float, default `30.0`, per-attempt wall-clock budget) and `provider_max_attempts` (int, default `3`, total attempts including the first — `1` disables retries). Shared by both OpenAI adapters; the `.env.example` stanza is kept in sync. The mock backends ignore both.
- **SDK `max_retries=0`.** Both adapters build the SDK client with the explicit per-attempt `timeout` and `max_retries=0`, so the adapter's own bounded loop is the single retry authority. This is an intentional behavior change: the SDK previously retried up to 2 extra times invisibly, which R-9 did not bound by config.
- **Preserved failure contracts.** Embedding-call exhaustion (or a non-retryable failure) re-raises the *original* SDK exception — `embed` introduces no exception type of its own — so `DomainService` still flips `embedding_status='failed'` (A-35). Chat-call exhaustion (or a non-retryable failure) still surfaces as `ChatProviderUnavailableError` → `FallbackMode.PROVIDER_UNAVAILABLE` (D-035), now only after bounded retries are exhausted; the exception message names the configured attempt bound.
- **Observability is logs-only.** Each attempt logs `provider.attempt` (label, attempt number, outcome class, latency); a distinct `provider.exhausted` line is logged on exhaustion (the R-6 effective-vs-requested signal). No new schema, no new DB column.
- **Test seam.** Both adapter constructors gain a keyword-only `retry_policy: RetryPolicy` parameter and a private keyword-only `_client` injection parameter; the factories never pass `_client`, so the public adapter contract is unchanged. Offline tests use injected fake SDK clients.

### Why
D-044 sequenced OP-2 after OP-1: 6.2's dead-letter surface consumes exhausted bounded retries and 6.3 specializes retry policy for rate limits, so the bounded-retry/timeout primitive must exist first. Enforcing R-9 is the smallest autonomous step that closes the declared-but-unenforced gap and unblocks the rest of OP-2. Putting the primitive behind an adapter seam — generic loop, injected classifier — keeps core code free of provider-SDK knowledge (D-026 / I-11) and lets a future non-OpenAI provider reuse the loop with its own classifier. Disabling the SDK's own retry makes the config-bounded loop the single, observable retry authority instead of leaving an invisible second retry layer that R-9 cannot see.

### Consequence
- New: `src/memory_rag/adapters/resilience.py` (`RetryPolicy`, `OutcomeClass`, `classify_openai_error`, `run_with_retries`); `tests/test_provider_resilience.py`, `tests/test_openai_embedding_retry.py`, `tests/test_openai_chat_retry.py` (all offline — retry-then-succeed, retry-then-exhaust, non-retryable-fails-fast, classification mapping, timeout/`max_retries=0` wiring).
- Changed: `src/memory_rag/adapters/embeddings/openai_client.py` and `src/memory_rag/adapters/answers/openai_client.py` (build the SDK client with `timeout` + `max_retries=0`; wrap the API call in `run_with_retries`; new `retry_policy` + private `_client` constructor params); `src/memory_rag/adapters/embeddings/factory.py` and `src/memory_rag/adapters/answers/factory.py` (build a `RetryPolicy` from `Settings` for the `openai` branch); `src/memory_rag/config.py` (`provider_timeout_seconds`, `provider_max_attempts`); `tests/test_embedding_client_openai.py` and `tests/test_chat_client_openai.py` (live smoke tests pass the new `retry_policy` arg — still env-gated, still out of `make check`).
- Docs: this D-047 entry; `docs/RUNTIME-INVARIANTS.md` (R-9 records it is enforced for the OpenAI adapters as of Slice 6.1); `.env.example` (`PROVIDER_TIMEOUT_SECONDS` / `PROVIDER_MAX_ATTEMPTS` stanza); `docs/RUNBOOK.md` (provider-resilience operational note); `docs/execution-map.md` (Slice 6.1 artifacts); `docs/todo.md` (6.1 done, 6.2 surfaced as next); `docs/OPERATIONALIZATION-ROADMAP.md` (Slice 6.1 recorded as the landed OP-2 foundation).
- The mock embedding / chat clients are unchanged — they have no provider to retry; only the `openai` factory branch threads the policy.
- **OP-2 stays open.** Slice 6.1 enforces R-9 but does not close OP-2: the dead-letter surface (6.2) and rate-limit handling (6.3) remain. The Phase 6 Definition of Done — provider failures do not corrupt durable state; retries are bounded and visible; fallback behavior is explicit and logged — is only partly met.
- Out of scope (deferred): the dead-letter surface and any persistent dead-letter schema (6.2 / OP-2); rate-limit-specific backoff — exponential backoff, jitter, honoring `Retry-After` (6.3 / OP-2); failed-embedding reconciliation (OP-3 / A-35); retry/timeout hardening for non-provider calls (Postgres, internal RPC); circuit breakers, request hashing, cost/token aggregation (Phase 7 / OP-5); any schema/migration change; the D-026 `diary_rag` / `family_id` / `Note` renames.

## D-048 — OP-2.2 / Slice 6.2: persistent dead-letter surface for failed indexing jobs

### Decision
Slice 6.2 is the **dead-letter packet** of the OP-2 group (D-044), ordered after Slice 6.1 (D-047) and before Slice 6.3. Before this packet a failed embedding call during ingest left only two traces: the per-chunk `embedding_status='failed'` flips (A-35) and one `embedding.failed` log line — there was no durable, structured, queryable record of the failed indexing job. Slice 6.2 adds that surface. This is a packet-level contract decision; it follows the D-045 / D-046 / D-047 precedent of recording packet-level shape choices in the decision log. It fixes:

- **Core entity — `IndexingDeadLetter`.** A channel-neutral frozen/slotted dataclass in `core/domain/models.py`, opaque string identifiers only, no provider or transport types. Seven fields: `dead_letter_id`, `source_message_id`, `community_id`, `chunk_ids` (`tuple[str, ...]` — every chunk the failed call covered), `model_name`, `error_class`, `created_at`. **`error_class` is the exception class name only** — the same provenance the `embedding.failed` log line already carries; no `error_detail` / free-text exception payload is persisted. The record is **append-only**: it has no status / resolved column. `attempt_count` is intentionally out of scope — the actual attempts-used value is internal to `run_with_retries` and surfacing it would require a `resilience.py` change.
- **Storage — additive, non-destructive.** New Postgres migration `0003.indexing-dead-letter-table.sql` adds the `indexing_dead_letters` table (`chunk_ids` as `TEXT[]`; no FK on the array element, mirroring `answer_traces.context_chunk_ids`) plus two indexes (`community_id`, `source_message_id`). SQLite gets the equivalent table in its embedded DDL (`chunk_ids` as JSON `TEXT`). The mock store gets a process-local dict. No existing table, row, or column is touched.
- **Repository seam.** `DomainRepository` gains `save_indexing_dead_letter`, `list_indexing_dead_letters` (community-scoped, `(created_at DESC, dead_letter_id DESC)` order, optional `limit`), and `get_indexing_dead_letter`, implemented with full parity across mock / sqlite / postgres. The surface is operational inspection, so SQLite implements the reads too — unlike the D-029 raw-export seam.
- **Best-effort write, strictly additive to A-35.** On an embedding-call failure, `DomainService._embed_chunks` runs the per-chunk `embedding_status='failed'` marking **first and unchanged**, then attempts one `save_indexing_dead_letter` wrapped in its own `try/except`. A failure of that write logs a distinct `dead_letter.write_failed` warning and is swallowed — it never propagates and never suppresses the failure marking. `event_chunks.embedding_status='failed'` stays the authoritative failure signal; the dead-letter row may be absent if its own persistence failed. The existing `embedding.failed` log line gains a `dead_letter_id` field.

### Why
D-044 sequenced OP-2 as 6.1 → 6.2 → 6.3, and A-35's OP-3 reconciliation is specified to consume a dead-letter surface. Slice 6.1 landed the bounded-retry primitive and the exhausted-retry signal but routed failures only to a per-chunk column and a log line; an operator could not list failed indexing jobs as structured rows, and OP-3 had no work list to drain. Adding the durable surface is the smallest autonomous step that closes that gap and unblocks OP-3. Capturing `error_class` only — rather than free-text exception payloads — keeps the packet tightly bounded and avoids persisting unbounded provider text durably; richer diagnostics, if ever needed, are a separate later decision. Making the write best-effort and ordering it after the failure marking guarantees the new surface can never regress the pre-existing A-35 behavior: a dead-letter persistence problem degrades observability, not durability.

### Consequence
- New: `src/memory_rag/storage/postgres/migrations/0003.indexing-dead-letter-table.sql` (the dead-letter table migration); `tests/test_storage_dead_letter.py` (mock + sqlite offline parity tests, PG-DSN-gated postgres tests).
- Changed: `src/memory_rag/core/domain/models.py` (`IndexingDeadLetter`); `src/memory_rag/core/domain/__init__.py` (re-export); `src/memory_rag/storage/repository.py` (three Protocol seams); `src/memory_rag/storage/mock/store.py`, `src/memory_rag/storage/sqlite/store.py` (embedded DDL + methods), `src/memory_rag/storage/postgres/store.py` (methods); `src/memory_rag/services/domain_service.py` (best-effort dead-letter write in the `_embed_chunks` failure branch; `embedding.failed` log line gains `dead_letter_id`); `tests/test_domain_service.py` (dead-letter recorded on failure; write-failure swallowed; success path writes none); `tests/test_postgres_migrations.py` (discovery covers 0003; gated non-destructive 0002→0003 upgrade proof).
- Docs: this D-048 entry; `docs/RUNBOOK.md` (a dead-letter inspection note under "Failed embeddings", incl. the best-effort caveat); `docs/product/TechSpec.md` (`IndexingDeadLetter` added to the §5 data model); `docs/execution-map.md` (Slice 6.2 artifacts); `docs/todo.md` (6.2 done, 6.3 surfaced as next); `docs/OPERATIONALIZATION-ROADMAP.md` (Slice 6.2 recorded as landed).
- SQLite is unchanged as a migration model: it is still not migration-managed; the new table bootstraps via `CREATE TABLE IF NOT EXISTS` and is kept in hand-parity with the Postgres migration.
- **OP-2 stays open.** Slice 6.2 adds the dead-letter surface but does not close OP-2: rate-limit handling (6.3) remains. The Phase 6 Definition of Done is closer but not fully met.
- **A-35 stays open** — it is resolved by OP-3, which consumes this surface; Slice 6.2 only creates and populates it, with no retry, drain, or reconciliation behavior.
- Out of scope (deferred): retry / drain / reconciliation of dead-letter rows or failed chunks (OP-3 / A-35); any status / `resolved` / `attempt_count` column on `indexing_dead_letters`; rate-limit-specific backoff (6.3 / OP-2); any change to `resilience.py`, retry policy, or the OpenAI adapters; chat/query-time failure handling; metrics, dashboards, circuit breakers (Phase 7 / OP-5); the D-026 `diary_rag` / `family_id` / `Note` renames; SQLite real retrieval.

## D-049 — OP-2.3 / Slice 6.3: rate-limit backoff — exponential delay, jitter, and `Retry-After` honoring (R-9)

### Decision
Slice 6.3 is the **rate-limit packet** of the OP-2 group (D-044), ordered after Slice 6.1 (D-047) and Slice 6.2 (D-048); it is the last slice in OP-2. Slice 6.1 classified 429 (`openai.RateLimitError`) as retryable but retried it — like every retryable failure — immediately, with no inter-attempt delay; retrying a rate-limited provider back-to-back wastes the bounded attempt budget and provokes more 429s. Slice 6.3 adds the inter-attempt wait. This is a packet-level contract decision; it follows the D-045 / D-046 / D-047 / D-048 precedent of recording packet-level shape choices in the decision log. It fixes:

- **Inter-attempt backoff in `run_with_retries`.** After a retryable failure that is not the final attempt, the loop now waits before the next attempt. `compute_backoff` sizes the wait: an exponential term `backoff_base_seconds * 2 ** (attempt - 1)` clamped to `backoff_cap_seconds`, then **full jitter** (the AWS strategy — scale by a uniform draw in `[0, 1)`). The loop stays provider-agnostic: backoff knobs come from `RetryPolicy`, OpenAI specifics enter only through injected callables.
- **`Retry-After` honoring, clamped to the cap.** A new `extract_retry_after_seconds` reads a server-supplied delay from `openai.RateLimitError` (`retry-after-ms` preferred over `retry-after`). When present it **takes precedence** over computed backoff — but is **clamped to `backoff_cap_seconds`**, so total wall time stays bounded and a server-supplied value can never make the wait server-controlled. Only the numeric header form is parsed; an HTTP-date `Retry-After`, a malformed value, or a negative value is treated as absent and the call falls back to computed backoff. `run_with_retries` gains an optional injected `retry_after` callable carrying this extractor; `None` keeps a pure computed-backoff loop.
- **Injected `sleep` seam.** `run_with_retries` gains a `sleep` parameter (default `time.sleep`) so offline tests exercise backoff without blocking on real time.
- **Two more `Settings` knobs.** `provider_backoff_base_seconds` (float, default `0.5`, `gt=0`) and `provider_backoff_cap_seconds` (float, default `8.0`, `gt=0`). Production config keeps the `gt=0` floor; zero values are used only in direct `RetryPolicy` construction inside tests, to keep retry-wiring tests instant. `RetryPolicy` gains matching `backoff_base_seconds` / `backoff_cap_seconds` fields (defaulted, so existing two-arg constructors are unaffected); both factories thread the two settings into the `openai` branch. The mock backends ignore all four provider knobs.
- **Worst-case bound.** Bounded wall time for one provider call is now `timeout_seconds * max_attempts + backoff_cap_seconds * (max_attempts - 1)` — `90s + 8s × 2 = 106s` at defaults. The `RetryPolicy` docstring and R-9 are updated to this formula.
- **Observability on the existing log surface.** The retryable `provider.attempt` warning line that is followed by a wait gains two fields: `delay_ms` and `delay_source` (`computed` | `retry_after`). The **final** retryable attempt — which is *not* followed by a wait — keeps the pre-6.3 field set (no `delay_ms=0` noise), and `provider.exhausted` is unchanged. No new log family, so the RUNBOOK `grep` pattern is unchanged.

### Why
D-044 sequenced OP-2 as 6.1 → 6.2 → 6.3; with the bounded-retry primitive (6.1) and the dead-letter surface (6.2) landed, the immediate-retry gap on rate limits is the last open item before OP-2 is a coherent milestone and before OP-3 reconciliation builds on the provider-hardening surface. Adding backoff is the smallest autonomous step that closes it. Clamping `Retry-After` to `backoff_cap_seconds` — rather than honoring it verbatim — is the load-bearing choice: it preserves a *computable, documented* R-9 worst-case bound and keeps total wait operationally predictable instead of server-controlled. Parsing only the numeric `Retry-After` form keeps the packet tightly bounded; the clamped-cap bound holds regardless of the header form, so the date-form fallback to computed backoff is safe. Surfacing the wait as fields on the existing `provider.attempt` line — rather than a new `provider.backoff` line — keeps per-attempt observability on one log surface and avoids widening operational `grep` patterns.

### Consequence
- New (within `src/memory_rag/adapters/resilience.py`): `compute_backoff`, `extract_retry_after_seconds`, the private `_resolve_delay` helper.
- Changed: `src/memory_rag/adapters/resilience.py` (`RetryPolicy` gains `backoff_base_seconds` / `backoff_cap_seconds` + worst-case docstring; `run_with_retries` gains the `retry_after` and `sleep` params, the inter-attempt wait, and the `delay_ms` / `delay_source` log fields); `src/memory_rag/config.py` (`provider_backoff_base_seconds`, `provider_backoff_cap_seconds`); `src/memory_rag/adapters/embeddings/factory.py` and `src/memory_rag/adapters/answers/factory.py` (thread the two new knobs into `RetryPolicy`); `src/memory_rag/adapters/embeddings/openai_client.py` and `src/memory_rag/adapters/answers/openai_client.py` (pass `retry_after=extract_retry_after_seconds`); `tests/test_provider_resilience.py` (backoff, jitter, cap, `Retry-After`, sleep-seam, and log-field tests); `tests/test_openai_chat_retry.py` and `tests/test_openai_embedding_retry.py` (pin a zero-backoff `RetryPolicy` so the wiring tests stay instant).
- Docs: this D-049 entry; `docs/RUNTIME-INVARIANTS.md` (R-9 records backoff is enforced and the updated worst-case formula); `.env.example` (`PROVIDER_BACKOFF_BASE_SECONDS` / `PROVIDER_BACKOFF_CAP_SECONDS` added to the provider stanza); `docs/RUNBOOK.md` (provider-resilience note: the two knobs, the worst-case formula, the `delay_ms` / `delay_source` fields, and the numeric-only `Retry-After` limitation); `docs/execution-map.md` (Slice 6.3 artifacts; Phase 6 header); `docs/todo.md` (6.3 done, OP-2 complete); `docs/OPERATIONALIZATION-ROADMAP.md` (Slice 6.3 landed, OP-2 complete).
- The mock embedding / chat clients are unchanged — they have no provider to retry; only the `openai` factory branch threads the policy.
- **OP-2 closes.** Slice 6.3 is the last OP-2 slice; with 6.1 / 6.2 / 6.3 landed, the Phase 6 Definition of Done is met — provider failures do not corrupt durable state, retries are bounded and visible, fallback behavior is explicit and logged.
- **A-35 stays open** — failed-embedding reconciliation is OP-3; Slice 6.3 changes only how retries *wait*, not whether failed chunks are ever retried after exhaustion.
- Known limitation: a date-form `Retry-After` header is not parsed this slice — it falls back to computed backoff. This is bounded behavior (the clamp still applies) and is recorded here rather than as an open assumption.
- Out of scope (deferred): failed-embedding reconciliation (OP-3 / A-35); circuit breakers; any change to the dead-letter surface or `indexing_dead_letters` schema; retry/backoff for non-provider calls (Postgres, internal RPC); cost/token/latency aggregation (Phase 7 / OP-5); live OpenAI calls in `make check`; any schema/migration change; the D-026 `diary_rag` / `family_id` / `Note` renames.

## D-050 — OP-3.1: failed-embedding discovery query + read-only reconciliation entrypoint

### Decision
OP-3.1 is the **discovery packet** of the OP-3 group (D-044), the first slice of failed-embedding reconciliation. OP-2 hardened provider calls and added the `indexing_dead_letters` surface (D-048), but a chunk stuck at `embedding_status='failed'` (A-35) is still found only by a hand-run `psql` probe (`docs/RUNBOOK.md` "Failed embeddings"). OP-3.1 establishes the discovery seam and a read-only operator entrypoint **before** any retry, backoff, status-transition, or dead-letter-routing behavior — those land in a later OP-3 slice. This packet does **not** resolve A-35. This is a packet-level contract decision; it follows the D-045 / D-046 / D-047 / D-048 / D-049 precedent of recording packet-level shape choices in the decision log. It fixes:

- **Discovery seam — one new repository method.** `DomainRepository` gains `list_failed_event_chunks(community_id, *, limit=None) -> list[EventChunk]`, returning chunks whose `embedding_status` is `EmbeddingStatus.FAILED` within `community_id`. Order is `(created_at ASC, chunk_id ASC)` — **oldest failure first**, the FIFO order a future retry job consumes; the `chunk_id` tie-break keeps it deterministic when chunks from one ingest share `created_at`. **Community scoping is mandatory** (I-7, R-3) — signature parity with `list_indexing_dead_letters`, not the global form of the retired probe. Validation mirrors the sibling `list_*` methods: empty `community_id` raises; negative `limit` raises; `limit=None` means no cap. Implemented with full parity across mock / sqlite / postgres. No new schema or migration — the Postgres `WHERE embedding_status='failed'` filter is already served by `idx_event_chunks_embedding_status` (OP-1.2 / `0002`).
- **Reconciliation service — discovery only.** New `src/memory_rag/services/reconciliation.py` adds `ReconciliationService(store)` with `discover_failed_chunks(community_id, *, limit=None) -> FailedEmbeddingReport`. The service calls the repository seam and wraps the result; it emits a `reconciliation.discovered` log line. `FailedEmbeddingReport` is a channel-neutral frozen/slotted dataclass (`community_id`, `chunks`; `count` property). It performs no retry, no `failed → ready` transition, and no dead-letter write.
- **Operator entrypoint — read-only CLI.** The module is runnable: `python -m memory_rag.services.reconciliation --community <id> [--limit N]`. It targets the canonical durable backend — it builds a `PostgresDomainStore` from `Settings`, mirroring `storage.postgres.migrations_runner` — because failed chunks persist durably only in Postgres and the probe it replaces is a Postgres `psql` probe. `--limit` defaults to a bounded `DEFAULT_DISCOVERY_LIMIT = 100`. It prints the rendered report and exits `0`. This replaces the raw SQL probe as the documented inspection surface for failed chunks.

### Why
D-044 sequenced OP-3 after OP-2 and A-35 specifies reconciliation "retries `failed` chunks with bounded backoff and a dead-letter strategy". Retry behavior is the riskiest part — it re-invokes a provider and mutates `embedding_status`. Splitting the discovery seam into its own slice lands the work list (which chunks are failed, in what order) and the operator inspection surface first, fully tested, with zero mutation risk; the retry slice then builds on a stable, parity-tested seam instead of inventing the query and the retry loop in one packet. Mandatory community scoping — over the global form of the retired probe — keeps the seam consistent with I-7 / R-3 and with `list_indexing_dead_letters`; an operator sweeps per community, the same shape every other `list_*` query already has. Oldest-first ordering anticipates the retry consumer: the longest-waiting failure should be retried first. Targeting the CLI at Postgres — rather than honoring `STORAGE_BACKEND` — avoids coupling a reconciliation entrypoint to the Telegram adapter's private store factory and matches the `migrations_runner` precedent; the discovery *method* still has full three-backend parity.

### Consequence
- New: `src/memory_rag/services/reconciliation.py` (`ReconciliationService`, `FailedEmbeddingReport`, `render_report`, the `_main` CLI); `tests/test_storage_failed_chunks.py` (mock + sqlite offline parity, PG-DSN-gated postgres parity — ordering, limit, empty, community scoping, only-`failed`, validation); `tests/test_reconciliation.py` (service discovery, read-only assertion, `render_report`, `_main` wiring via an injected store, PG-DSN-gated end-to-end).
- Changed: `src/memory_rag/storage/repository.py` (one new Protocol method); `src/memory_rag/storage/mock/store.py`, `src/memory_rag/storage/sqlite/store.py`, `src/memory_rag/storage/postgres/store.py` (the method, with parity); `src/memory_rag/services/__init__.py` (re-export `ReconciliationService` / `FailedEmbeddingReport`).
- Docs: this D-050 entry; `docs/RUNBOOK.md` ("Failed embeddings" — the CLI presented as the inspection surface, superseding the hand-run probe; `embedding_status='failed'` stays the authoritative signal); `docs/execution-map.md` (new OP-3 section, OP-3.1 row); `docs/todo.md` (OP-3.1 done, OP-3.2 scope restated); `docs/OPERATIONALIZATION-ROADMAP.md` (OP-3.1 recorded as landed).
- No schema, migration, boot gate, scheduler, background worker, or Telegram surface. No new runtime dependency. A-34 destructive-upgrade discipline does not apply.
- `count` on `FailedEmbeddingReport` is the size of the returned slice — when it equals `limit`, more failed chunks may exist beyond the cap. A separate total-count query is intentionally out of scope (the packet authorizes exactly one new method).
- **A-35 stays open** — OP-3.1 only finds and reports failed chunks; it retries nothing. A-35 is resolved by the later OP-3 retry slice that consumes this seam.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` not touched — a read-only discovery query enforces no new invariant. `docs/assumptions.md` not touched — A-35 stays open and the packet-level contract choices (method signature, ordering, community scoping, Postgres-targeted CLI) are recorded here, not as open assumptions.
- Out of scope (deferred to a later OP-3 slice): any retry loop re-invoking `EmbeddingClient`; any `failed → ready` transition; bounded backoff during reconciliation; dead-letter write routing during reconciliation; any scheduler / background worker / boot gate / Telegram surface; retry-outcome metrics beyond the discovery report; a total-failed-count query; A-35 resolution; the D-026 `diary_rag` / `family_id` / `Note` renames.

## D-051 — OP-3.2a: failed-embedding retry execution & failed → ready transition

### Decision
OP-3.2a is the first packet of the OP-3.2 retry slice (D-044; OP-3 group). OP-3.1 (D-050) landed the read-only discovery seam — `list_failed_event_chunks` plus a `ReconciliationService` / CLI that finds and reports chunks stuck at `embedding_status='failed'` (A-35) — but retried nothing. OP-3.2a adds the smallest behaviour-changing slice on top: it retries the discovered failed chunks and transitions the ones that succeed `failed → ready`. Routing exhausted retries to the dead-letter surface and the formal A-35 closure are split into a follow-up packet, **OP-3.2b**. This packet does **not** resolve A-35. This is a packet-level contract decision; it follows the D-045 / D-046 / D-047 / D-048 / D-049 / D-050 precedent of recording packet-level shape choices in the decision log. It fixes:

- **Retry entrypoint on the existing service — no new repository method.** `ReconciliationService.__init__` gains an optional `embedding_client: EmbeddingClient | None` parameter; discovery-only callers (including the OP-3.1 CLI path) omit it and are unchanged. A new `retry_failed_chunks(community_id, *, limit=None) -> RetryOutcomeReport` consumes the OP-3.1 `list_failed_event_chunks` seam — the same mandatory community scoping and `limit` semantics as `discover_failed_chunks` — and reuses the existing `save_embedding_records` / `set_chunk_embedding_status` storage primitives. It raises `RuntimeError` when the service was built without a client.
- **Per-`source_message_id` grouping.** Discovered failed chunks are grouped by `source_message_id`, replaying the per-source batching ingest uses; each group is retried with a single `EmbeddingClient.embed` call, so a group's chunks succeed or fail together. Group order follows the discovery oldest-failure-first order.
- **Bounded retry stays inside `embed()`.** OP-2's bounded retry / backoff / `Retry-After` loop is internal to `OpenAIEmbeddingClient.embed`; `retry_failed_chunks` issues one `embed` call per group and adds no second loop. On exhaustion the client re-raises the original exception, which the retry method catches.
- **Records before status; honest provenance.** On a succeeding group, `EmbeddingRecord` rows — carrying the live client's `model_name` / `dimension` and the retry run's timestamp — are persisted *before* the chunks transition `failed → ready`, so a chunk is never `ready` without its record. Mock retries record `model_name='mock'` (D-024).
- **No state regression on failure.** A group whose `embed`, record write, or status flip raises is left at `embedding_status='failed'`, caught under one per-group `except Exception`, and reported with the exception class name only (no message). Groups are independent — one failure does not stop the others.
- **Retry-outcome report + renderer.** New channel-neutral frozen/slotted `RetryGroupOutcome` (per `source_message_id`) and `RetryOutcomeReport` (community-scoped; derived chunk / group counts), the report re-exported from `services/__init__.py`; a pure `render_retry_report`. Logs: `reconciliation.retry.group.ok` / `reconciliation.retry.group.failed` per group plus one `reconciliation.retry.summary`.
- **CLI retry mode.** The `python -m memory_rag.services.reconciliation` entrypoint gains a `--retry` flag; without it the discovery path is byte-for-byte unchanged. `--retry` builds an `EmbeddingClient` via `build_embedding_client(Settings())` alongside the Postgres-targeted store, runs `retry_failed_chunks`, and prints `render_retry_report`.

### Why
D-044 sequenced OP-3 after OP-2, and A-35 specifies reconciliation "retries `failed` chunks with bounded backoff and a dead-letter strategy". OP-3.1 split discovery off as the zero-mutation slice. The remaining retry work has two separable risks: re-invoking the provider and mutating `embedding_status` (the core behaviour), and routing exhausted retries into the dead-letter surface (which touches OP-2.2's `indexing_dead_letters` and the formal A-35 contract). OP-3.2a lands the first, fully tested, on the stable OP-3.1 seam; OP-3.2b adds dead-letter routing and closes A-35 on top. Keeping the embedding client optional on the constructor preserves the OP-3.1 discovery CLI untouched. Grouping by `source_message_id` keeps each retry call shaped like the ingest call it replays. Records-before-status mirrors `DomainService._embed_chunks`, so the durable ordering guarantee is identical on the ingest and retry paths.

### Consequence
- Changed: `src/memory_rag/services/reconciliation.py` (`ReconciliationService` gains the optional `embedding_client` and `retry_failed_chunks`; new `RetryGroupOutcome` / `RetryOutcomeReport` dataclasses and `render_retry_report`; `_main` gains `--retry`); `src/memory_rag/services/__init__.py` (re-exports `RetryOutcomeReport`).
- New tests in `tests/test_reconciliation.py`: retry success (`failed → ready`, records persisted, honest provenance), exhausted-failure (`failed` stays `failed`, no records), per-`source_message_id` grouping, mixed group outcomes, empty-set no-op, `limit` parity, records-before-status ordering, `UNIQUE`-collision group failure, missing-client `RuntimeError`, `render_retry_report`, `_main --retry` offline wiring, and a PG-DSN-gated end-to-end retry.
- Docs: this D-051 entry; `docs/RUNBOOK.md` ("Failed embeddings" gains a retry subsection); `docs/execution-map.md` (OP-3 section, OP-3.2 row split into OP-3.2a landed / OP-3.2b open); `docs/todo.md` (OP-3.2a done, OP-3.2b restated as next); `docs/OPERATIONALIZATION-ROADMAP.md` (OP-3.2 refined into OP-3.2a landed / OP-3.2b open).
- No new repository Protocol method, no `EmbeddingClient` Protocol change, no schema or migration, no scheduler / background worker / boot gate / Telegram surface. `make check` makes no live OpenAI call — retry tests use the mock client.
- **A-35 stays open** — OP-3.2a retries failed chunks and clears the ones that succeed, but chunks whose retry is exhausted stay `failed` with no dead-letter routing; A-35 is resolved by OP-3.2b. `docs/assumptions.md` is not touched.
- Known limitation: a group whose `EmbeddingRecord` rows are persisted but whose `set_chunk_embedding_status` flip then raises leaves the chunk `failed` with a `ready`-shaped record; a re-run collides on `UNIQUE (chunk_id, model_name)` and reports the group failed rather than double-writing. This is bounded, observable behaviour recorded here; OP-3.2b may harden it.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` not touched — the retry path enforces no new invariant; it reuses the I-3 / R-1 chunk-intact guarantee and the records-before-status ordering the ingest path already holds.
- Out of scope (deferred to OP-3.2b): dead-letter routing for exhausted retries; any new dead-letter schema / column / migration; A-35 closure in `docs/assumptions.md`; scheduler / background worker / boot gate / Telegram surface; the D-026 `diary_rag` / `family_id` / `Note` renames.

## D-052 — OP-3.2b: failed-embedding retry dead-letter routing & A-35 closure

### Decision
OP-3.2b is the second and final packet of the OP-3.2 retry slice (D-044; OP-3 group). OP-3.2a (D-051) landed retry execution — `retry_failed_chunks` re-embeds discovered failed chunks and transitions the ones that succeed `failed → ready` — but left exhausted-retry groups `failed` with no durable routing, so A-35 stayed open. OP-3.2b adds the remaining slice: an exhausted retry group is now also routed to the OP-2.2 `indexing_dead_letters` surface, which satisfies A-35's documented closure criterion (a `failed` chunk is retried, succeeds *or* lands in the dead-letter surface, and the outcome is observable) and **resolves A-35**. This is a packet-level contract decision; it follows the D-048 / D-050 / D-051 precedent of recording packet-level shape choices in the decision log. It fixes:

- **Exhausted retry routes to the existing dead-letter surface — no new repository method.** In `retry_failed_chunks`, a group whose retry fails now builds one `IndexingDeadLetter` (a fresh `uuid4` id; the group's `source_message_id`, `community_id`, `chunk_ids`; the live client's `model_name`; the exception class name only; the retry run's timestamp) and persists it via the existing `DomainRepository.save_indexing_dead_letter` seam (D-048). No new Protocol method, no schema, no migration, no dead-letter column.
- **Best-effort, append-only, never gating.** The group is already `failed` before the write is attempted. The write runs *after* that outcome is decided; a failure of its own is logged (`dead_letter.write_failed`, the same log shape `DomainService._embed_chunks` uses on the ingest path) and swallowed, so it can never regress the `failed` outcome or make `retry_failed_chunks` raise. The success path writes no dead letter. Each exhausted retry appends one row — the original ingest failure already wrote one (D-048); the append-only table carries one row per failed indexing *attempt*, with no `resolved` / `status` / counter columns.
- **Dead-letter identity surfaced.** `RetryGroupOutcome` gains an optional `dead_letter_id: str | None`, set iff the group failed *and* its dead-letter write succeeded (`None` for succeeded groups and for failed groups whose write itself failed). The `reconciliation.retry.group.failed` log line gains a `dead_letter_id=` field (`none` when the write failed); `render_retry_report` appends `dead_letter_id=` to a failed group's line when one is present. The `--retry` CLI surfaces it for free — it already prints `render_retry_report`.

### Why
D-051 split the OP-3.2 retry work along its two separable risks: re-invoking the provider and mutating `embedding_status` (OP-3.2a), and routing exhausted retries into OP-2.2's `indexing_dead_letters` plus the formal A-35 contract (OP-3.2b). OP-3.2b lands the second on the stable OP-3.2a seam. Reusing the OP-2.2 dead-letter surface keeps one dead-letter contract for both the ingest and reconciliation failure paths; mirroring the ingest path's best-effort discipline (status/outcome decided first, dead-letter write after, write failure logged and swallowed) keeps `embedding_status='failed'` the single authoritative failure signal. A-35's open clause sequenced reconciliation as OP-3 and named "a dead-letter strategy"; with discovery (OP-3.1), retry (OP-3.2a), and exhausted-retry dead-letter routing (OP-3.2b) all landed, the assumption is fully met and closes.

### Consequence
- Changed: `src/memory_rag/services/reconciliation.py` (`retry_failed_chunks` failure path writes a best-effort `IndexingDeadLetter`; `RetryGroupOutcome` gains `dead_letter_id`; `render_retry_report` and the `reconciliation.retry.group.failed` log surface it; `IndexingDeadLetter` imported).
- New tests in `tests/test_reconciliation.py`: exhausted-group dead-letter write (row fields + outcome identity), dead-letter write failure swallowed (no raise, no state regression, `dead_letter.write_failed` logged, `dead_letter_id` `None`), success path writes no dead letter, `render_retry_report` shows / omits `dead_letter_id`, and a PG-DSN-gated end-to-end exhausted-retry producing an inspectable `indexing_dead_letters` row.
- Docs: this D-052 entry; `docs/RUNBOOK.md` ("Failed embeddings" — exhausted retries now route to the dead-letter surface); `docs/execution-map.md` (OP-3.2b row landed, OP-3 narrative); `docs/todo.md` (OP-3.2b done, OP-3 complete); `docs/OPERATIONALIZATION-ROADMAP.md` (OP-3.2b landed, OP-3 done, A-35 resolved); `docs/assumptions.md` and `docs/assumption-audit.md` (**A-35 closed**).
- No new repository Protocol method, no `EmbeddingClient` Protocol change, no schema or migration, no scheduler / background worker / boot gate / Telegram surface. `make check` makes no live OpenAI call — retry tests use the mock client.
- **A-35 is resolved.** OP-3 (discovery OP-3.1, retry OP-3.2a, dead-letter routing OP-3.2b) is complete.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` not touched — the dead-letter write enforces no new invariant; it reuses the OP-2.2 append-only, best-effort dead-letter discipline.
- Out of scope: any new dead-letter schema / column (`resolved`, `status`, retry counters) / migration; dead-letter dedup; scheduler / background / periodic retry; any bounded-attempt policy beyond OP-2's client-internal retry; OP-4 / OP-5 work; the D-026 `diary_rag` / `family_id` / `Note` renames.

## D-053 — OP-4.1: resolve A-40 — backup mechanism, RPO/RTO targets, and recovery contour

### Decision
OP-4.1 is the **decision packet** of the OP-4 group (D-044) — the first OP-4 slice, ordered before any backup/restore implementation. D-027 committed the raw-data durability *contract* (a daily backup window targeting `03:00–05:00` local, plus a recovery primitive stronger than the last nightly snapshot) but deliberately left the *mechanism*, the formal RPO/RTO targets, retention windows, and restore-drill cadence bracketed as A-40. OP-4.1 resolves A-40 and decomposes OP-4. It is **docs-only**: no scripts, no scheduler / WAL-archiving configuration, no `docker-compose` change, no schema or migration change, no `src/` change, and no executed restore drill. It follows the D-044 / D-045 precedent of recording packet-level shape choices in the decision log. It fixes:

- **Recovery primitive — nightly base backup + continuous WAL archiving → PITR.** For the current reference/local Postgres deployment (`docker-compose.yml`, `pgvector/pgvector:pg16`), the selected "stronger-than-nightly" primitive is a nightly physical base backup (`pg_basebackup`) combined with continuous WAL archiving (`archive_command`), enabling point-in-time recovery to any moment between the last base backup and the failure. This was chosen over a streaming hot-standby replica: a replica needs a second always-on Postgres node even for the single-node reference deployment, whereas base backup + WAL archiving is single-node-friendly and maps cleanly onto every deployment shape. Per deployment shape, provider-agnostic: **managed cloud** uses the provider's equivalent managed PITR — no vendor is named (A-41 stays open); **self-hosted OSS** runs the same base-backup + WAL-archiving contract, operator-owned. The contour is reusable / open-source-friendly and names no vendor.
- **RPO ≤ 5 minutes, RTO ≤ 1 hour for raw `SourceMessage` data.** The recovery point objective — the maximum acceptable loss of raw data — is at most ~5 minutes; the recovery time objective — the maximum acceptable time to restore raw data — is at most 1 hour. Considered and rejected: a looser RPO ≤ 15 min / RTO ≤ 4 h contour (larger acceptable loss and downtime) and a tighter RPO ≤ 1 min / RTO ≤ 30 min contour (aggressive WAL shipping, higher operational cost). RPO ≤ 5 min / RTO ≤ 1 h is the balanced target for a Stage-2 service approaching its first non-local deployment.
- **Backup window and retention — proposed contract values recorded here.** The nightly base-backup window stays the D-027 `03:00–05:00` local target (unchanged — D-053 only restates it). WAL is archived continuously; `archive_timeout` ≈ 5 minutes is proposed to bound RPO at the ≤ 5 min target. Base backups are retained 30 days; archived WAL is retained long enough to cover the oldest retained base backup, so PITR is possible to any point in the trailing ~30-day window. The 30-day retention and the ≈ 5 min `archive_timeout` are conventional values this packet records as the contract — they are open to revision by a later OP-4 packet without re-opening A-40.
- **Backup scope.** The logical minimum that must survive to rebuild the diary graph is raw `source_messages` plus the `notes` / `event_chunks` lineage scaffolding and the non-derivable, append-only `indexing_dead_letters` audit surface. The chosen mechanism is *physical* (base backup + WAL), so it is cluster-wide — it captures every table, including the derivable `embedding_records`, `queries`, `retrieval_hits`, and `answer_traces`, in one consistent image. Derived state therefore restores with the physical backup and needs no replay step, which is what makes RTO ≤ 1 h achievable; replay from raw (I-12) remains available as a fallback recovery path.
- **Restore-drill cadence.** A restore drill — recovering raw `SourceMessage` data from a base backup and exercising PITR from archived WAL — is run once before the first non-local deployment, then quarterly thereafter.
- **OP-4 decomposition.** OP-4 is decomposed into three ordered packets: **OP-4.1** (this decision — docs-only); **OP-4.2** — backup automation: base-backup + WAL-archiving configuration, `archive_command`, and scheduler wiring; **OP-4.3** — an executed restore drill validating the RPO/RTO targets. The recommended sequence and per-packet detail live in `docs/OPERATIONALIZATION-ROADMAP.md`.

### Why
D-044 sequenced OP-4 as a Stage-2 group but left it undecomposed, with an explicit unresolved "A-40 mechanism + RPO/RTO selected" exit criterion; no OP-4 implementation packet (backup automation, restore drill) can be picked deliberately until that fork is settled. Base backup + continuous WAL archiving is the lightest primitive that genuinely beats nightly-only on a single-node reference deployment — it needs no second always-on node — and it maps onto managed-cloud and self-hosted shapes as "the same contract, provider- or operator-owned" without naming a vendor, keeping A-41 open. Resolving A-40 with concrete RPO/RTO targets and a decomposition, while leaving the implementation to OP-4.2 / OP-4.3, gives the OP-4 milestone a stable, reviewable contract before any infrastructure work begins.

### Consequence
- New D-053 entry. D-027 and D-044 are not edited in place — D-053 references and builds on them.
- `docs/assumptions.md`: **A-40 closed** — moved from the open "Target-state architecture forks" section to "Recently closed" as `A-40 → D-053 (...)`. A-23's "remaining open" pointer to A-40 is updated to record the resolution by D-053. A-41 stays **open** and provider-agnostic — D-053 names no managed-cloud vendor.
- `docs/assumption-audit.md`: the A-40 row is struck through → D-053; the A-23 row's pointer to A-40 is updated.
- `docs/OPERATIONALIZATION-ROADMAP.md`: the "Status" paragraph records OP-4.1 landed; the OP-4 packet-group inventory row (§2) and the OP-4 roadmap row (§3) record the resolved mechanism / RPO / RTO contour and the OP-4.1 / OP-4.2 / OP-4.3 decomposition.
- `docs/RUNBOOK.md`: the "Raw-data durability and recovery" section is rewritten from A-40-bracketed to the concrete D-053 contour (operator-facing description only — backup automation commands land with OP-4.2).
- `docs/execution-map.md`: Phase 8 slice 8.0 cites D-053; a new `## OP-4` section with an OP-4.1 / 4.2 / 4.3 sub-packet table is added, parallel to the `## OP-1` and `## OP-3` sections.
- `docs/todo.md`: a new OP-4 block records OP-4.1 done (D-053) and OP-4.2 / OP-4.3 as the next packets.
- `docs/ARCHITECTURE.md` and `docs/product/TechSpec.md`: one-line factual de-bracketing each — the "remain bracketed as open assumptions" and "mechanism bracketed as A-40" clauses now point to D-053.
- No code, schema, migration, infra, scheduler, or `src/` change; no executed restore drill. `docs/PRD.md`, `docs/INVARIANTS.md`, `docs/RUNTIME-INVARIANTS.md`, and `docs/CHECKLIST.md` are deliberately **not** touched — their wording (a recovery story stronger than the next nightly backup; I-15's "stronger-than-nightly recovery primitive"; the Phase 8 "backup/restore drill executed" gate) is the D-027 contract and stays true after D-053.
- **A-40 is resolved. OP-4 is decomposed but not complete** — OP-4.1 lands the decision; OP-4.2 (backup automation) and OP-4.3 (executed restore drill) remain open, and the Phase 8 raw-data durability Definition of Done is met only when OP-4.3's drill recovers raw data within the D-053 RPO/RTO.
- Out of scope (deferred): all backup/restore implementation — base-backup + WAL-archiving configuration, `archive_command`, scheduler/cron wiring, `docker-compose` changes (OP-4.2); the executed restore drill (OP-4.3); the production managed-cloud provider choice (A-41); any schema/migration or `src/` change; OP-5 and all Stage-3 Phase-8 work (access / visibility / audit / retention); the D-026 `diary_rag` / `family_id` / `Note` renames.

## D-054 — OP-4.2: backup automation — WAL archiving + nightly base backup for the reference Postgres shape

### Decision
OP-4.2 is the first **implementation** packet of the OP-4 group (D-044) — it turns the D-053 backup contract into a runnable mechanism for the reference/local Postgres shape (`docker-compose.yml`, `pgvector/pgvector:pg16`). It implements only what D-053 already specified; it does not re-open the mechanism, the RPO/RTO targets, retention, or the restore-drill cadence. It is **infra + config + docs**: no schema, no migration, no `src/` change, and no executed restore drill (OP-4.3). It fixes:

- **WAL archiving — always-on on the `postgres` service.** The `postgres` service `command:` passes `-c` flags setting `wal_level=replica`, `archive_mode=on`, `archive_timeout=300` (~5 min, bounding RPO at the D-053 ≤ 5 min target), and an `archive_command` that copies each completed WAL segment into the archive volume idempotently (`test -f … ||` skips an already-archived segment) and atomically (`cp` to a `.tmp` name, then `mv` into place). Archiving runs on a plain `docker compose up` — it is part of the durable contract and must be continuous to meet the RPO.
- **A separate durable archive volume.** A new named volume `memory_rag_pg_archive`, mounted at `/archive` (layout `/archive/wal`, `/archive/base`), distinct from `memory_rag_pg_data` so the archive survives loss of the data volume. A profile-less one-shot `pg_archive_init` service creates the layout and `chown`s it to the postgres OS user (UID 999) before Postgres starts archiving.
- **Replication access for the backup runner.** An initdb-time hook, `configs/postgres/initdb-replication-hba.sh` (mounted into `/docker-entrypoint-initdb.d/`), appends a `host replication` rule to `pg_hba.conf` so the `pg_backup` sidecar's `pg_basebackup` can open a physical-replication connection over the Compose network. It runs only at first cluster bootstrap — enabling OP-4.2 on a pre-existing local volume needs a `docker compose down -v` reset (the same precedent as A-34).
- **Base-backup runner — opt-in via the `backup` Compose profile.** A new `pg_backup` sidecar (reusing `pgvector/pgvector:pg16`, `restart: unless-stopped`) runs exactly one long-running `scheduler.sh` process. Once per calendar day, when the local hour (`TZ`) is within `[BACKUP_WINDOW_START, BACKUP_WINDOW_END)` (default `03`–`05`), it runs `pg_basebackup` (`--format=tar --wal-method=none --gzip --checkpoint=fast`) into `/archive/base/base-<UTC-ISO8601>`, then retention pruning. A plain `docker compose up` leaves the runner down; `docker compose --profile backup up -d` enables it.
- **Retention.** `prune.sh` drops base backups older than `BASE_RETENTION_DAYS` (default 30), then runs `pg_archivecleanup` over `/archive/wal` keyed on the oldest *retained* base backup's recorded `START_WAL` segment — implementing the D-053 "WAL covering the oldest base backup" rule. With no retained base backup it prunes no WAL (fail-safe).
- **Single-run protection.** `backup.sh` and `prune.sh` share an exclusive non-blocking `flock` on `/archive/.backup.lock`; a second run — manual or scheduled — finds the lock busy, logs `pg_backup.lock.busy`, and exits 0. A prune can never run while a backup is in progress, and overlapping invocations never compete.
- **Success/failure evidence.** A clean cycle writes `/archive/last_success.json` (UTC timestamp, base-backup directory, prune summary) and removes `/archive/last_failure.json`; a failed cycle writes `/archive/last_failure.json` (UTC timestamp, failing stage, short error). Scheduler logs mark cycles with `pg_backup.cycle.ok` / `pg_backup.cycle.error`.
- **Operator surface.** `make backup-up` / `backup-run` / `backup-prune`; `BACKUP_WINDOW_START` / `BACKUP_WINDOW_END` / `BASE_RETENTION_DAYS` / `TZ` in `.env.example`; a new OP-4.2 "Backup automation" subsection in `docs/RUNBOOK.md`. Restore commands stay with OP-4.3.

### Why
D-053 fixed the backup contract but was docs-only and deferred every line of implementation; OP-4.3's restore drill is hard-blocked until real backup artifacts exist. OP-4.2 is the smallest step that produces inspectable WAL segments and base backups. A sidecar container running a shell scheduling loop keeps all orchestration inside the single `docker-compose.yml` and assumes no host cron/systemd — consistent with the D-026 portability rule and the "no hidden orchestration" guidance. Profile-gating the runner keeps a plain `docker compose up` behaviourally unchanged for ordinary development, while WAL archiving — which must be continuous to bound the RPO — stays on.

### Consequence
- New D-054 entry. D-027 / D-044 / D-053 are not edited in place — D-054 references and builds on them.
- New files: `configs/postgres/initdb-replication-hba.sh`; `scripts/pg_backup/scheduler.sh`, `backup.sh`, `prune.sh`.
- `docker-compose.yml`: the `postgres` service gains the WAL-archiving `command:` `-c` flags, the `memory_rag_pg_archive` mount, and the `initdb-replication-hba.sh` initdb-hook mount; new `pg_archive_init` one-shot and `pg_backup` (profile `backup`) services; new `memory_rag_pg_archive` volume.
- `.env.example`: `BACKUP_WINDOW_START` / `BACKUP_WINDOW_END` / `BASE_RETENTION_DAYS` / `TZ`. `Makefile`: `backup-up` / `backup-run` / `backup-prune`.
- `docs/RUNBOOK.md`: an OP-4.2 "Backup automation" subsection (enablement, manual commands, the `last_success.json` / `last_failure.json` markers, the `pg_backup.*` log markers, the unbounded-WAL / `archive_mode`-restart / `down -v` warnings). `docs/execution-map.md`: the OP-4.2 row is filled. `docs/todo.md`: OP-4.2 recorded done, OP-4.3 next. `docs/OPERATIONALIZATION-ROADMAP.md`: the "Status" paragraph and the §2 / §3 OP-4 rows record OP-4.2 landed.
- `docs/PRD.md`, `docs/INVARIANTS.md`, `docs/RUNTIME-INVARIANTS.md`, `docs/CHECKLIST.md`, `docs/ARCHITECTURE.md`, `docs/product/TechSpec.md`, `docs/assumptions.md`, and `docs/assumption-audit.md` are deliberately **not** touched — OP-4.2 implements the D-053 contract without changing it; **A-40 stays closed, A-41 stays open**.
- **OP-4.2 is complete. OP-4 is not** — the Phase 8 raw-data durability Definition of Done is met only when OP-4.3's executed restore drill recovers raw data within the D-053 RPO/RTO.
- Out of scope (deferred): the executed restore drill and any RPO/RTO measurement (OP-4.3); managed-cloud / self-hosted shape backup automation and the managed-cloud provider choice (A-41); off-box / remote archive storage (bind-mounting `/archive` to external storage stays an operator choice); any schema/migration or `src/` change; OP-5 and all Stage-3 Phase-8 work; the D-026 `diary_rag` / `family_id` / `Note` renames.

## D-055 — OP-4.3: executed restore drill and measured RPO/RTO for raw SourceMessage data

### Decision
OP-4.3 is the closing **implementation** packet of the OP-4 group (D-044) — it executes the restore drill the D-053 contract requires and turns the OP-4.2 backup automation into a *validated* recovery path for the reference/local Postgres shape (`docker-compose.yml`, `pgvector/pgvector:pg16`). It implements only the restore side of the D-053 contract; it does not re-open the mechanism, the RPO/RTO targets, retention, the restore-drill cadence, or the OP-4.2 backup automation. It is **adapter + config + docs**: no schema, no migration, no `src/` change. It fixes:

- **Restore tooling — `scripts/pg_restore/restore.sh` + a `pg_restore` Compose service.** `restore.sh` is an operator-grade tool that prepares a recovered Postgres 16 data directory from an OP-4.2 base backup (`base-<ts>/base.tar.gz`) plus the archived WAL stream (`/archive/wal`): it extracts the base backup, writes a `restore_command` (and, for PITR, `recovery_target_time` + `recovery_target_action=promote`) into `postgresql.auto.conf`, and creates the `recovery.signal` file. It takes explicit `--backup-dir` and `--target=latest` / `--target-timestamp=ISO8601` parameters, prints the plan (source backup, recovery target, destination) before any write, supports a `--dry-run` plan mode (validate the backup + WAL, write nothing), requires an explicit `--yes` for a real restore, refuses to run against an apparently-live cluster (a `postmaster.pid` in the destination), and writes per-run logs + a `last_restore.json` marker under `/archive/restore_logs/`. It only ever operates on the dedicated, throwaway `memory_rag_pg_restore_data` scratch volume — never the live `memory_rag_pg_data`. The opt-in `pg_restore` Compose service (profile `restore`) runs the recovered cluster on a separate host port (`RESTORE_PORT`, default `5433`) so it never clashes with the live `postgres`; the recovered cluster has `archive_mode` off, so it never writes WAL back into the archive.
- **Executed restore drill (reference/local shape).** On a fresh local stack: a base backup was taken, then three synthetic `source_messages` batches (5 rows each, `community_id='op43-drill'`) were ingested *after* the backup so recovery depended on archived-WAL replay — batches 1 and 2 forced a WAL switch, batch 3 did not. A **full restore** (`--target=latest`) and a **PITR restore** (`--target-timestamp` between batch 1 and batch 2) were executed; recovered raw rows were verified after each.
- **Measured RPO/RTO — recorded as inspection observations, not a hard gate.** The full restore recovered all 15 rows in **5 s**; the PITR restore recovered exactly batch 1 (5 rows), correctly excluding batches 2–3, in **3 s** — both far inside the D-053 RTO ≤ 1 h target (**RTO: met**). RPO: a forced `pg_switch_wal()` archives a segment immediately (loss window → 0); an un-switched write is force-archived within `archive_timeout=300` — the drill observed batch 3's segment archived ~290 s after commit, bounding worst-case raw-write loss at ≤ 5 min, the D-053 RPO ≤ 5 min target (**RPO: met**). The drill values and met/not-met verdicts are recorded in `docs/op4-drill/op4.3-20260519-evidence.json`.
- **Phase 8 raw-data durability Definition of Done — met.** Raw `SourceMessage` data is recoverable from the prior backup window (full restore) and to a tighter-than-nightly recovery point (PITR), both within the D-053 RPO/RTO. OP-4.3 closes OP-4.

### Why
D-053 fixed the recovery contract and D-054 produced real backup artifacts, but every canonical doc held OP-4 open until a drill *demonstrated* recovery — the Phase 8 DoD asks for raw recoverability "from at least the prior nightly window plus a tighter recovery point than nightly-only", which is an executed result, not a configured target. A reusable `restore.sh` (rather than a one-off RUNBOOK command sequence) was chosen so the same tool serves the executed drill, the quarterly rerun cadence, and ad-hoc operator restores; the drill is treated as an inspection harness, not a `make check` gate, so an honest miss would be recorded as `not-met`/`mixed` rather than softening a target. The measured values met both targets with wide margin.

### Consequence
- New D-055 entry. D-027 / D-044 / D-053 / D-054 are not edited in place — D-055 references and builds on them.
- New files: `scripts/pg_restore/restore.sh`; `docs/op4-drill/op4.3-20260519-evidence.json`.
- `docker-compose.yml`: a new `pg_restore` service (profile `restore`) and a new `memory_rag_pg_restore_data` volume. The `pg_restore` service mounts `memory_rag_pg_archive` read-write (not read-only) so `restore.sh` can write `/archive/restore_logs/`; the recovered cluster runs with `archive_mode` off, so it cannot corrupt OP-4.2 base backups or WAL.
- `.env.example`: `RESTORE_PORT`. `Makefile`: `restore-plan` / `restore-run` (non-gated; not part of `make check`).
- `docs/RUNBOOK.md`: the "Raw-data durability and recovery" section's "target, not a measured result" caveat is replaced with the measured outcome; a new "Restore drill (OP-4.3 / D-055)" subsection documents the drill and operator restores as `restore.sh` + `pg_restore`-profile invocations and how to read `/archive/restore_logs/` and the evidence file. `docs/execution-map.md`: the OP-4.3 row is filled and OP-4 → done. `docs/todo.md`: OP-4.3 recorded done, OP-4 milestone closed. `docs/OPERATIONALIZATION-ROADMAP.md`: the "Status" paragraph and the §2 / §3 OP-4 rows record OP-4.3 landed and OP-4 complete.
- `docs/RUNTIME-INVARIANTS.md` is deliberately **not** touched — RPO/RTO are operational-policy targets (D-027 / D-053), not runtime-enforced invariants; the drill demonstrated nothing that needs new invariant wording.
- **Coupling.** `restore.sh` is coupled to the OP-4.2 backup format and `/archive` layout (`base-<ts>/{base.tar.gz,backup_manifest,START_WAL}`, flat `/archive/wal`). A future packet that changes either must update `restore.sh` in the same packet and refresh D-055 / `RUNBOOK.md`.
- **Cadence.** Per D-053, the drill is rerun once before the first non-local deployment and quarterly thereafter; each rerun records a new evidence file under `docs/op4-drill/`, with D-055 and `RUNBOOK.md` pointing at the latest.
- **OP-4.3 is complete. OP-4 is complete** — the Phase 8 raw-data durability Definition of Done is met.
- Out of scope (deferred): managed-cloud and self-hosted / cross-host restore tooling (A-41 stays open); automated continuous restore verification and a CI-gated restore check; off-box / remote archive storage; restore of enrichment-derived data (embeddings, `event_chunks`, indexes — OP-4 covers raw `SourceMessage` durability only); any schema/migration or `src/` change; OP-5 and all Stage-3 Phase-8 work; the D-026 `diary_rag` / `family_id` / `Note` renames.

## D-056 — OP-5.1: OP-5 observability gold eval set, sitting beside the frozen D-038 baseline set

### Decision
OP-5.1 is the opening **implementation** packet of the OP-5 group (Evaluation & observability) and the entry point BuildPlan Phase 7.1 names: a curated gold eval set extending the D-038 retrieval harness. It is **config + docs** on the D-026 axes — it adds two fixture files plus a mock-mode shape test, and changes no `src/` production code, no retrieval behavior (`services/retrieval.py`, `storage/search_repository.py` untouched), and no schema. It fixes:

- **The OP-5 gold set sits *beside* the D-038 set; it does not supersede it.** The D-038 12-query fixture pair (`eval/retrieval/gold.json` + `eval/retrieval/corpus.jsonl`) stays **frozen** as the D-025 baseline-measurement set, because the D-038 Postgres baseline snapshot is still uncaptured and growing that set in place would silently change what the eventual operator capture (a precondition for D-039) measures against. OP-5.1 instead adds a separate, durably-named **observability** fixture pair: `eval/retrieval/observability/gold.json` + `eval/retrieval/observability/corpus.jsonl`. The two sets are kept distinct through naming, docs semantics, and harness-selection clarity only — no schema or governance layer.
  - **Frozen baseline set** — `eval/retrieval/{gold.json,corpus.jsonl}`. Role: the D-038 D-025-baseline measurement. Workflow: the still-pending D-038 Postgres baseline capture and later baseline-vs-quality comparisons (D-039).
  - **OP-5 observability set** — `eval/retrieval/observability/{gold.json,corpus.jsonl}`. Role: the expanded evaluability/observability set the rest of OP-5 builds on (retrieval/groundedness metrics, cost/latency).
- **Invocation contract — default vs explicit.** The harness CLI (`__main__.py`) and `regenerate_embeddings.py` already accept `--gold` / `--corpus` / `--embeddings-cache` path arguments, so no harness code change is needed. The **default** mock invocation (`python -m memory_rag.eval.retrieval --mode mock`, no path flags) continues to load the **frozen D-038 baseline** pair. The **observability** pair must always be selected via explicit `--gold eval/retrieval/observability/gold.json --corpus eval/retrieval/observability/corpus.jsonl`; an operator Postgres run over it points its `--embeddings-cache` at `eval/retrieval/observability/embeddings_cache.json`, and the matching `regenerate_embeddings` invocation points `--gold` / `--cache` at the observability paths.
- **Modest expansion, coverage-axes contract.** The observability set is ~21 queries over a 19-message corpus (`obs-msg-1`…`obs-msg-19`, a distinct id prefix so its handles never collide with `corpus-msg-N`; `community_id_default` = `eval-community`, a fresh opaque canonical-vocabulary value chosen for the new file — not a D-026 rename of the frozen `eval-fam` set). It is curated for coverage diversity, not raw count. The minimum coverage axes are part of the OP-5.1 contract (also recorded in `gold.json`'s `_coverage_axes` key): at least 2 negative queries (empty `expected_handles`); at least 2 multilingual (Russian) queries tied to Russian corpus lines; at least 3 paraphrase queries whose wording meaningfully diverges from the corpus event text; and a mix of single-hit and multi-hit queries. This is the **initial** expanded observability set, not the final coverage target.
- **Handle contract unchanged.** `expected_handles` entries use the same D-038 scheme — `"{external_message_id}#{event_index}"`, `event_index` the 0-based ordinal of the `EventChunk` produced by `DomainService.ingest` after `parse_note` + chunking. The `_handle_contract` string is copied verbatim into the observability `gold.json`.
- **Mock-mode shape coverage only.** `tests/test_retrieval_harness_shape.py` is parametrized over **both** fixture pairs; the end-to-end mock run resolves every observability handle (a mistyped handle or wrong `event_index` fails `make check` with the existing `KeyError`). Shape assertions only — **no quality-value assertions** (`[[feedback_harness_is_inspection_not_gate]]`).

### Why
OP-1…OP-4 are complete and OP-5 is the only open Stage-2 group and the gate for Stage 3; the gold eval set is OP-5's entry point because every downstream OP-5 slice needs a curated question set to measure against. The beside-not-supersede split is the smallest honest resolution of a real tension: the D-038 baseline-vs-quality discipline depends on a stable 12-query set whose Postgres baseline has not yet been captured, while OP-5 needs a broader set; freezing one and adding the other keeps both intact without a versioning or governance layer. The expansion is kept modest and coverage-driven so the OP-5.1 diff stays reviewable and OP-5.1 does not turn into a corpus program.

### Consequence
- New D-056 entry. D-038 is referenced, **not edited in place** — its frozen fixtures and its still-open "Baseline snapshot (observed)" placeholder are untouched.
- New files: `eval/retrieval/observability/gold.json`, `eval/retrieval/observability/corpus.jsonl`.
- Changed: `tests/test_retrieval_harness_shape.py` (parametrized over both fixture pairs, mock mode, shape-only); `.gitignore` (narrow entries for the D-038 and observability operator-produced `embeddings_cache.json` — D-038 had left this implicit); `docs/decision-log.md`, `docs/execution-map.md` (row 7.1 filled, → OP-5.1), `docs/OPERATIONALIZATION-ROADMAP.md` (OP-5 in progress, OP-5.1 landed), `docs/RUNBOOK.md` (harness subsection gains a fixture-set / invocation note), `docs/todo.md` (OP-5.1 done, OP-5.2/5.3 next).
- No `src/` change, no harness code change, no schema/DDL/migration, no boot-gate change. A-34 destructive-upgrade discipline does not apply. `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` are not touched — the gold set changes nothing code enforces. No `docs/assumptions.md` entry — set relation, naming, and coverage-axes are packet-level contract decisions captured here.
- New runtime dependencies: none.
- Out of scope (deferred): the operator-run D-038 Postgres baseline capture (unchanged precondition for D-039); a Postgres-mode capture over the observability set and its embeddings-cache regeneration (operator-deliberate, deferred like the D-038 baseline); retrieval/groundedness metric computation beyond the harness's existing recall/MRR, and cost/token/latency aggregation (OP-5.2 / OP-5.3); hard thresholds, quality gating, nDCG, graded relevance; live OpenAI inside `make check`; any retrieval-behavior change; richer/broader coverage (larger corpus, more languages, near-exhaustive eval — later OP-5 packets); D-026 renames; schema/DDL/migration changes.

## D-057 — OP-5.2a: retrieval hit-rate & empty-rate metrics on the eval harness

### Decision
OP-5.2a is the first **implementation** packet of OP-5.2 (BuildPlan Phase 7.2, "retrieval & groundedness metrics"). Phase 7.2 names two surfaces that do not share code: retrieval hit/empty rates are a tightly bounded extension of the harness's existing `AggregateMetrics` / `run_harness`, while a groundedness check is the `QueryService.answer` / `AnswerContext` (I-9 citation-subset) surface. OP-5.2a is scoped to the **retrieval-only** half; the groundedness check is split out as **OP-5.2b**. On the D-026 axes this is a `core` change confined to the inspection-only `src/memory_rag/eval/` subsystem — it adds no production retrieval behavior (`services/retrieval.py`, `storage/search_repository.py` untouched), no answer-path wiring, no schema, no live API. It fixes:

- **Two new aggregate metrics, computed from existing harness outputs.** `run_harness` already builds a `PerQueryResult` per gold query; OP-5.2a adds two pure helper functions (`hit_rate`, `empty_rate` in `harness.py`) over those rows and two `float` fields on `AggregateMetrics`. No new external dependency, no new per-query field, no change to the retrieval calls themselves.
- **`hit_rate` uses a non-empty-gold denominator (owner-confirmed).** `hit_rate` = fraction of gold queries that have >=1 expected chunk **and** surfaced >=1 of them in the fused result list, divided by the count of gold queries with a non-empty `expected_handles`. Negative queries (empty `expected_handles`) are excluded from the denominator — they cannot produce a hit, so counting them would only dilute the rate. This non-empty-gold denominator is what keeps `hit_rate` numerically distinct from the existing `per_leg_recall_at_20.fused`, which divides by *all* queries. The denominator semantics are made explicit at every user-facing surface: the CLI human report annotates the line `(denominator: non-empty-gold queries only)`, and `RUNBOOK.md` states it in prose.
- **`empty_rate` divides by all queries (proposed default, this packet).** `empty_rate` = fraction of all gold queries whose fused result list came back empty — retrieval returned zero candidates (both the dense and sparse legs empty). It counts every query, answerable or negative, since "retrieval returned nothing" is independent of whether the query had expected chunks. The CLI line is annotated `(denominator: all queries)`.
- **Inspection only, no gate.** Both metrics are observed values rendered in the harness report (human + JSON); the CLI exit code stays `0` regardless. No thresholds, no `make check` gating. `tests/test_retrieval_harness_shape.py` gains shape-only assertions (`isinstance` + `[0.0, 1.0]` bounds) for the two new fields over both fixture pairs; `tests/test_retrieval_harness_metrics.py` is a new pure-function test pinning the metric semantics on constructed inputs (`[[feedback_harness_is_inspection_not_gate]]`).

### Why
OP-5.1 (D-056) landed the OP-5 observability gold set but added no metrics over it; `docs/todo.md` and execution-map row 7.2 both name retrieval hit-rate / empty-rate as the next item. Splitting OP-5.2 into 5.2a (retrieval) and 5.2b (groundedness) keeps each packet on a single surface and the diff reviewable — hit/empty rate need only the harness's existing per-query outputs, whereas groundedness needs the answer path. The non-empty-gold denominator for `hit_rate` is the owner-confirmed resolution of a real redundancy: an all-queries denominator would make `hit_rate` numerically identical to `per_leg_recall_at_20.fused`.

### Consequence
- New D-057 entry. D-056 and D-038 are referenced, not edited.
- Changed `src/`: `src/memory_rag/eval/retrieval/harness.py` (`AggregateMetrics` gains `hit_rate` + `empty_rate`; new `hit_rate` / `empty_rate` helper functions; `run_harness` populates the two fields), `src/memory_rag/eval/retrieval/__main__.py` (`_format_human` renders both, with explicit denominator annotations; JSON output picks them up via `asdict`).
- Changed tests: `tests/test_retrieval_harness_shape.py` (shape-only assertions for the two fields, both fixture pairs); new `tests/test_retrieval_harness_metrics.py` (pure-function semantics).
- Changed docs: `docs/decision-log.md`, `docs/execution-map.md` (row 7.2 filled, → OP-5.2a), `docs/todo.md` (OP-5.2a done, OP-5.2b / OP-5.3 next), `docs/OPERATIONALIZATION-ROADMAP.md` (OP-5.2a landed within OP-5), `docs/RUNBOOK.md` (harness subsection documents hit-rate / empty-rate and the non-empty-gold denominator).
- No production retrieval-behavior change, no schema/DDL/migration, no boot-gate change, no live API in `make check`. `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` untouched — the metrics enforce nothing. No `docs/assumptions.md` entry — the `hit_rate` denominator (owner-confirmed) and the `empty_rate` definition (proposed default) are packet-level contract decisions captured here.
- New runtime dependencies: none.
- Observed on the mock harness (inspection only, not a threshold): the D-038 baseline set reports `hit_rate` over its non-empty-gold queries; the observability set reports `hit_rate` over its 19 non-empty of 21 total gold queries.
- Out of scope (deferred): the groundedness check / any routing through `QueryService.answer`, `AnswerContext`, or the I-9 citation-subset path — **OP-5.2b**; cost / token / latency aggregation — **OP-5.3**; the operator-run D-038 Postgres baseline capture (unchanged precondition for D-039); quality thresholds, gating, nDCG, graded relevance, any CI gate over the metrics; live OpenAI inside `make check`; any retrieval-behavior change in production `src/` outside the eval harness; schema/DDL/migration changes; D-026 renames.

## D-058 — OP-5.2b: groundedness-proxy metric on the answer-path eval harness

### Decision
OP-5.2b is the second **implementation** packet of OP-5.2 (BuildPlan Phase 7.2, "retrieval & groundedness metrics") and the companion of OP-5.2a (D-057). Phase 7.2 names two surfaces that do not share code; D-057 closed the retrieval half, and OP-5.2b closes the groundedness half. On the D-026 axes this is a `core` change confined to the inspection-only `src/memory_rag/eval/` subsystem — it adds no production retrieval or answer-path behavior (`services/query_service.py`, `core/domain/models.py`, `core/answers/`, `storage/` untouched outside the inspection harness's truncate ritual), no schema, and no change to the core answer contract. It fixes:

- **Groundedness is a fallback-derived proxy, not a citation-coverage or factuality score (owner-confirmed).** `cited_chunk_ids` is computed and I-9-validated inside `parse_structured_answer` (`core/domain/answer_schema.py`) but then discarded — `AnswerResult` carries only `fallback` / `answer_text` / `context` / `evidence`. Rather than widen the core answer contract for an inspection metric, OP-5.2b derives groundedness from `AnswerResult.fallback`, which by D-035 (one decision per call) is a faithful projection of the I-9 enforcement outcome. The documented mapping is `{NONE, WEAK_EVIDENCE, AMBIGUOUS}` → grounded — the three contours that by the D-035 parse contract carry a **non-empty** `cited_chunk_ids` ⊆ `AnswerContext.ordered_chunks`. `NO_EVIDENCE` (empty retrieval or LLM-declared no_evidence), `PROVIDER_UNAVAILABLE` (no answer produced), and `PARSE_FAILURE` (which catches `FabricatedCitationError` — the I-9 citation-subset violation contour) are intentionally **not** grounded; pure-function tests pin this mapping for every `FallbackMode` member, and the limit is named at every surface (CLI section title carries "proxy" + "fallback-derived" verbatim; RUNBOOK subsection title matches verbatim; `GroundednessMetrics` docstring opens with the explicit disclaimer "Proxy groundedness metric derived from `AnswerResult.fallback`; not a factuality or citation-coverage score").
- **`groundedness_rate` uses a non-empty-gold (answerable) denominator (owner-confirmed, mirrors D-057 `hit_rate`).** Denominator = gold queries with a non-empty `expected_handles`; numerator = those whose graded answer is grounded. Negatives correctly returning `NO_EVIDENCE` are excluded so they do not dilute the rate. Returns `0.0` when there is no answerable query (mirrors `hit_rate`). The CLI human report annotates the line `(proxy: fallback-derived; denominator: non-empty-gold queries only)`; the RUNBOOK states it in prose.
- **`fallback_mode_counts` is a complete breakdown over all queries.** Counts every row including negatives, summing to the total query count, so an operator can read the full distribution of answer-path outcomes at a glance. Inspection only.
- **Eval-only wiring through `QueryService.answer`.** `src/memory_rag/eval/retrieval/harness.py` adds `PerAnswerResult` / `GroundednessMetrics` / `GroundednessReport` dataclasses, pure helpers (`is_grounded`, `groundedness_rate`, `fallback_mode_counts`), and a `run_answer_harness` loop that for each gold query builds an `InboundMessage` (`RouteKind.ASK`), calls `query_service.answer(...)`, and records one `PerAnswerResult` from `AnswerResult.fallback` + `AnswerResult.context`. `HarnessReport` gains an optional `groundedness: GroundednessReport | None = None` field — `run_harness` leaves it `None` (retrieval only); `__main__.py` builds a `QueryService` over the already-ingested store (mock mode: `MockChatClient`; Postgres mode: `build_chat_client(settings)`, operator-selected `CHAT_BACKEND` — defaults to mock, no live API forced) and attaches the groundedness report via `dataclasses.replace`. The JSON output stays a single top-level `HarnessReport` object — adding the nested `groundedness` key is purely additive on top of the OP-5.2a / D-057 shape.
- **Inspection only, no gate.** The CLI exit code stays `0` regardless of `groundedness_rate`. `tests/test_retrieval_harness_shape.py` gains shape-only assertions over both fixture pairs (and the `_run_mock_end_to_end` helper now drives the answer harness too); new `tests/test_retrieval_harness_groundedness.py` is a pure-function test pinning the `is_grounded` mapping for every `FallbackMode` member, the `groundedness_rate` non-empty-gold denominator, and the `fallback_mode_counts` shape (`[[feedback_harness_is_inspection_not_gate]]`, `[[feedback_metric_denominator_explicit]]`).

### Why
D-057 closed the retrieval half of execution-map row 7.2 and explicitly named OP-5.2b as the answer-path-wired companion that completes the slice. The 5.2a / 5.2b split was for reviewability only; landing 5.2b here makes row 7.2 a complete deliverable and keeps OP-5 a coherent Stage-2 milestone. The fallback-derived proxy was the owner-confirmed choice over exposing `cited_chunk_ids` on `AnswerResult`: the risks of the proxy (interpretation drift, reduced granularity) are real but moderate, while widening the core answer contract for an inspection metric would raise the architectural weight of OP-5.2b more than the current milestone needs. `cited_chunk_ids` exposure is recorded as a deferred follow-up. The non-empty-gold denominator mirrors D-057's owner-confirmed `hit_rate` denominator and keeps the answerable / negative split consistent across both 7.2 metrics.

### Consequence
- New D-058 entry. D-035, D-056, D-057 are referenced, not edited.
- Changed `src/`: `src/memory_rag/eval/retrieval/harness.py` (`PerAnswerResult` / `GroundednessMetrics` / `GroundednessReport` dataclasses; `_GROUNDED_FALLBACKS` + `is_grounded` + `groundedness_rate` + `fallback_mode_counts` helpers; `run_answer_harness` loop; optional `groundedness` field on `HarnessReport`), `src/memory_rag/eval/retrieval/__main__.py` (mock + Postgres modes build a `QueryService` over the ingested store and attach the groundedness report; `_format_human` renders the "Groundedness proxy (answer-path, fallback-derived, inspection only)" section with proxy + denominator annotation; `_TRUNCATE_TABLES` extended with `answer_traces`, `retrieval_hits`, `queries` so an operator Postgres answer-harness run starts clean).
- Changed tests: `tests/test_retrieval_harness_shape.py` (the mock end-to-end helper now also drives `run_answer_harness`; new shape-only assertions for the groundedness report over both fixture pairs); new `tests/test_retrieval_harness_groundedness.py` (pure-function semantics — `is_grounded` mapping for every `FallbackMode` member, `groundedness_rate` denominator, `fallback_mode_counts` shape).
- Changed docs: `docs/decision-log.md`, `docs/execution-map.md` (row 7.2 closed — → OP-5.2a + OP-5.2b), `docs/todo.md` (OP-5.2b done, OP-5.3 next), `docs/OPERATIONALIZATION-ROADMAP.md` (OP-5.2b landed within OP-5), `docs/RUNBOOK.md` (new "Groundedness proxy (answer-path, fallback-derived, inspection only)" subsection — title matches the CLI section verbatim).
- No production retrieval or answer-path behavior change, no `AnswerResult` / `QueryService` / `parse_structured_answer` change, no schema/DDL/migration, no boot-gate change, no live API in `make check`. `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` untouched — the metric enforces nothing; I-9 enforcement remains where D-033 placed it (`parse_structured_answer`). No `docs/assumptions.md` entry — the proxy framing and the non-empty-gold denominator are packet-level contract decisions captured here.
- New runtime dependencies: none.
- Observed on the mock harness (inspection only, not a threshold): on the D-038 baseline set (12 queries, 11 non-empty-gold) `groundedness_rate` ≈ 0.727 with `fallback_mode_counts = {none: 8, no_evidence: 4}`; on the OP-5 observability set (21 queries, 19 non-empty-gold) `groundedness_rate` ≈ 0.684 with `fallback_mode_counts = {none: 14, no_evidence: 7}`. The proxy reads ≥ `hit_rate` in mock mode whenever retrieval surfaces *any* chunk (even an irrelevant one): the mock cites confidently and grades `NONE`, which is exactly the proxy's documented limit — it cannot tell relevant from irrelevant citations. Real discriminating signal appears with a real provider under Postgres mode (`[[feedback_honest_mock_provenance]]`).
- Out of scope (deferred): exposing `cited_chunk_ids` on `AnswerResult` for true citation-coverage metrics (recorded follow-up); cost / token / latency aggregation — **OP-5.3**; the operator-run D-038 Postgres baseline capture (unchanged precondition for D-039); quality thresholds, gating, factuality classification, any CI gate over the metric; live OpenAI inside `make check`; any answer-path or retrieval-behavior change in production `src/` outside the eval harness; schema/DDL/migration changes; D-026 renames.

## D-059 — OP-5.3: cost & latency aggregation on the eval harness (closes OP-5)

### Decision
OP-5.3 is the closing **implementation** packet of the OP-5 group (D-044) — it adds token and wall-clock latency aggregation to the inspection-only eval harness, completes execution-map row 7.3, and closes Stage 2 (OP-5 is the last Stage-2 group; OP-1..OP-4 already landed). On the D-026 axes this is a `core` change confined to the inspection-only `src/memory_rag/eval/` subsystem — no production retrieval / answer-path / provider behavior change (`AnswerResult`, `QueryService`, `parse_structured_answer`, `core/answers/`, `services/retrieval.py`, `storage/` untouched outside the harness), no schema/migration, no boot-gate or Telegram surface, no live OpenAI in `make check`. It fixes:

- **Two pure aggregate dataclasses + one wrapper, derived from existing rows.** `CostMetrics` carries `total_prompt_tokens` / `total_completion_tokens` / `total_tokens` / `answer_calls_with_tokens` / `mean_total_tokens_per_call`; `LatencyMetrics` carries `mean_retrieval_ms` / `p50_retrieval_ms` / `max_retrieval_ms` and the same three for `answer_ms`; `CostLatencyMetrics` bundles both. `HarnessReport` gains an optional `cost_latency: CostLatencyMetrics | None = None` field — additive on top of OP-5.2a / OP-5.2b shape. Per-row carriers: `PerQueryResult.retrieval_latency_ms: float` and `PerAnswerResult.{answer_latency_ms, prompt_tokens, completion_tokens}` (defaults `0.0` / `0`).
- **`RecordingChatClient` shim — single-call / single-consumer with read-and-consume contract.** The shim wraps the operator-selected chat client, implements the `ChatClient` Protocol structurally, and stores the most recent `ChatResponse` in a one-slot buffer. `consume_last()` returns the response *and clears the slot* — clear-on-read semantics guarantee that a previous response's tokens **cannot be misattributed** to a later answer-path contour (`NO_EVIDENCE` / empty-query / `PROVIDER_UNAVAILABLE` — D-035) that short-circuits without invoking the chat client: on those rows `consume_last()` returns `None` and per-row tokens stay at `0`. The shim lives in the eval surface and is not used by production code. The `tests/test_retrieval_harness_cost_latency.py::test_recorder_no_misattribution_across_calls` test pins this contract.
- **Wall-clock latency, two boundaries, query-embedding lookup intentionally excluded.** `run_harness` measures `time.perf_counter` around the dense + sparse + RRF block per query; `run_answer_harness` measures `time.perf_counter` around `query_service.answer(...)` per query. The **query-embedding lookup is intentionally outside** the retrieval-latency boundary because mock mode obtains query embeddings via a live `MockEmbeddingClient.embed` call while Postgres mode reads from the pinned `embeddings_cache.json` — including the lookup would contaminate the metric with that mode-asymmetric cost. Documented in the `PerQueryResult.retrieval_latency_ms` docstring and the RUNBOOK subsection. Aggregate latency is **wall-clock only** — provider-attributed `ChatResponse.latency_ms` remains the canonical chat-call latency persisted on `AnswerTrace` (D-034 / D-035) and is **trace-level provenance, not an aggregate metric in this report**.
- **Mean + p50 + max; p95 intentionally omitted at this sample size.** Both retrieval and answer latency expose mean / p50 / max. `p50` (via `statistics.median`) is included as a small-sample robustness check at the current ~20-21 query gold-set size — a single slow outlier pulls the mean but not the median. `p95` is intentionally **omitted** because at ~20 samples it would be noisy and misleading. The denominator for every latency stat is **all queries** (each row contributes one sample). The cost mean denominator (`answer_calls_with_tokens`) excludes zero-token rows so the no-chat-call contours do not pull the per-call mean down.
- **Inspection only, no gate.** CLI exit stays `0` regardless of any observed value (`[[feedback_harness_is_inspection_not_gate]]`). No thresholds, no CI gating, no production telemetry change, no live OpenAI in `make check`. `_TRUNCATE_TABLES` is **not** extended — OP-5.2b already covers the answer-path tables (`answer_traces` / `retrieval_hits` / `queries`); OP-5.3 adds no persistence.
- **CLI rendering with explicit, named denominators (`[[feedback_metric_denominator_explicit]]`).** `_format_human` appends a new section after the groundedness block. Title verbatim: `Cost & latency (wall-clock + provider-reported tokens, inspection only):`. "provider-reported" is the honest framing — the harness reports whatever the chat client returned in `ChatResponse.token_counts`, and the mock client approximates from character counts (`[[feedback_honest_mock_provenance]]`). The per-call mean line carries `(denominator: answer-path calls with non-empty token_counts, n=<int>)`; both latency blocks carry `(denominator: all queries)`. The RUNBOOK subsection title matches the CLI section verbatim.
- **Tests.** A new pure-function file `tests/test_retrieval_harness_cost_latency.py` pins `cost_metrics`, `latency_metrics`, `_latency_stats`, and the `RecordingChatClient` read-and-consume / no-misattribution contract on constructed inputs (12 tests, including the empty-report → 0 contract). `tests/test_retrieval_harness_shape.py` gains: a new `test_mock_mode_includes_cost_and_latency_shape` parametrized over both fixture pairs (D-038 baseline + OP-5 observability), shape-only `isinstance` + `>= 0` assertions over every new field, an arithmetic sanity check `total_tokens == total_prompt + total_completion`, and a distributional sanity check `max >= mean` and `max >= p50` on each latency block; and a per-row `retrieval_latency_ms` / `answer_latency_ms` / `prompt_tokens` / `completion_tokens` shape check in the existing per-query and groundedness shape tests.

### Why
OP-5.1 (D-056) landed the OP-5 observability gold set; OP-5.2a (D-057) landed retrieval `hit_rate` / `empty_rate`; OP-5.2b (D-058) landed the groundedness proxy; row 7.3 ("cost & latency") is the last unfilled Phase 7 row and OP-5.3 is the last unfinished packet of OP-5. BuildPlan Phase 7 explicitly names "indexing latency" and "cost tracking" as Phase 7 Build items; `AnswerTrace` already persists `token_counts` and `latency_ms` (D-034 / D-035) — OP-5.3 does not add new persistence, it aggregates the same signals on the eval harness, parallel to how OP-5.2a/b aggregated retrieval/groundedness. The `RecordingChatClient` was chosen over modifying `AnswerResult` because token counts are not on `AnswerResult` today (only on `ChatResponse` and on the persisted `AnswerTrace`), and widening the core answer contract for an inspection-only metric would raise the architectural weight more than the milestone needs. The read-and-consume slot (rather than an ever-growing list) was the owner-confirmed correction during planning: it makes "no chat call → zero tokens on that row" structurally enforced, not merely a code-path coincidence, so the per-row token field cannot misattribute across mixed contours.

### Consequence
- New D-059 entry. D-034 / D-035 / D-038 / D-044 / D-056 / D-057 / D-058 are referenced, not edited.
- Changed `src/`: `src/memory_rag/eval/retrieval/harness.py` (new `CostMetrics` / `LatencyMetrics` / `CostLatencyMetrics` dataclasses; new `RecordingChatClient` shim with read-and-consume `consume_last`; new pure helpers `_latency_stats` / `cost_metrics` / `latency_metrics`; new per-row fields `retrieval_latency_ms` / `answer_latency_ms` / `prompt_tokens` / `completion_tokens` with `0` defaults; `run_harness` wraps dense+sparse+RRF in `time.perf_counter` and populates `retrieval_latency_ms`; `run_answer_harness` gains `chat_recorder: RecordingChatClient | None = None`, wraps `query_service.answer(...)` in `time.perf_counter`, reads tokens via `consume_last`), `src/memory_rag/eval/retrieval/__main__.py` (mock + Postgres modes wrap their chat client in `RecordingChatClient` before passing to `QueryService` and forward the recorder to `run_answer_harness`; both modes compute `CostLatencyMetrics` via `cost_metrics` / `latency_metrics` and attach via `dataclasses.replace`; `_format_human` renders the new "Cost & latency (wall-clock + provider-reported tokens, inspection only)" section with explicit denominator annotations; JSON output picks up the new fields via `asdict`).
- Changed tests: `tests/test_retrieval_harness_shape.py` (the mock end-to-end helper wraps the mock chat client in `RecordingChatClient` and computes `cost_latency`; new `test_mock_mode_includes_cost_and_latency_shape` parametrized over both fixture pairs; new per-row latency/token type+non-negativity assertions on the existing per-query and groundedness shape tests); new `tests/test_retrieval_harness_cost_latency.py` (12 pure-function tests covering empty-report → 0, sum / mean correctness with zero-token-row exclusion, `_latency_stats` mean / p50 / max correctness on fixed inputs, the `RecordingChatClient` read-and-consume contract, and the misattribution guardrail across sequential chat-call / no-chat-call answer rows).
- Changed docs: `docs/decision-log.md`, `docs/execution-map.md` (row 7.3 filled, → OP-5.3), `docs/RUNBOOK.md` (new "Cost & latency (wall-clock + provider-reported tokens, inspection only)" subsection — title matches the CLI section verbatim), `docs/OPERATIONALIZATION-ROADMAP.md` (Status flipped to OP-5 *(complete)*; §2 and §3 OP-5 rows updated; OP-2 ↔ OP-5.3 cross-cut prose in present tense), `docs/todo.md` (OP-5.3 closed; OP-5 header flipped to *(complete)*; "Still open before Stage 3" reduced to the operator-run D-038 Postgres baseline capture).
- No production retrieval / answer-path / provider behavior change, no `AnswerResult` / `QueryService` / `parse_structured_answer` / `core/answers/` change, no schema/DDL/migration, no boot-gate or Telegram surface, no live OpenAI in `make check`. `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` / `docs/assumptions.md` untouched — the metrics enforce nothing; the aggregates are inspection observables. No `docs/assumptions.md` entry — the read-and-consume `RecordingChatClient` contract, the wall-clock-only aggregate scope (provider-attributed `ChatResponse.latency_ms` remains trace-level provenance only), the query-embedding-lookup exclusion from the retrieval-latency boundary, the `answer_calls_with_tokens` denominator for the per-call mean, and the deliberate p95 omission at ~20-21 sample size are packet-level contract decisions captured here (`[[feedback_contract_decisions_in_decision_log]]`).
- New runtime dependencies: none (`statistics.median` is stdlib).
- Observed on the mock harness (inspection only, not a threshold; `[[feedback_honest_mock_provenance]]`):
  - **D-038 baseline set (12 queries, 11 non-empty-gold; 8 chat calls = 8 `NONE` + 4 `NO_EVIDENCE`):** `total_prompt_tokens = 7534`, `total_completion_tokens = 3048`, `total_tokens = 10582`, `answer_calls_with_tokens = 8`, `mean_total_tokens_per_call ≈ 1322.75`. These cost numbers are deterministic in mock mode because `MockChatClient` derives `token_counts` from character counts (per `ChatResponse` docstring) — they are character-derived approximations, **not** real-tokenizer counts. Latency: `retrieval_latency_ms` mean ≈ 5-6 ms (mock store); `answer_latency_ms` mean ≈ 6-8 ms (whole `QueryService.answer` call). Latency numbers are **machine-dependent and not deterministic** — they reflect the host running the harness and should not be read as regression targets.
  - **OP-5 observability set (21 queries, 19 non-empty-gold; 14 chat calls = 14 `NONE` + 7 `NO_EVIDENCE`):** `total_prompt_tokens = 11889`, `total_completion_tokens = 4398`, `total_tokens = 16287`, `answer_calls_with_tokens = 14`, `mean_total_tokens_per_call ≈ 1163.36`. Latency: order-of-magnitude similar to the baseline set; machine-dependent.
- Out of scope (deferred): exposing `cited_chunk_ids` on `AnswerResult` for true citation-coverage metrics (stays D-058's recorded follow-up); the operator-run D-038 Postgres baseline capture (unchanged precondition for Slice 3.7 / D-039); quality thresholds, gating, regression budgets, CI gates, factuality classification; live OpenAI inside `make check`; any production cost/latency telemetry / log-line / dashboard emission; any change to `AnswerResult` / `RetrievalTrace` / `QueryService` / `parse_structured_answer` / retrieval-path code outside the eval-harness surface; schema/DDL/migration changes; surfacing the provider-attributed `ChatResponse.latency_ms` as an aggregate metric (it stays trace-level provenance on `AnswerTrace`); aggregating `chat_model_name` per-row (already persisted on `AnswerTrace`); distributional latency stats beyond mean / p50 / max (p95 deferred until a larger sample size); D-026 renames.

## D-060 — DEPLOY-1.1: self-hosted VPS deployment shape + roadmap (opens DEPLOY-1)

### Decision
DEPLOY-1.1 re-sequences the deployment-shape build order set by D-027 without revoking the D-026 / D-027 peer parity across self-hosted OSS, managed cloud, and embedded shapes. **DEPLOY-1 — self-hosted VPS + Telegram is the first implemented reference deployment shape**; **DEPLOY-2 — managed cloud is the deferred second peer** (resolves A-41 when it lands). Only the implementation order changes; peer parity is preserved. It is **docs-only** — no code, schema, migration, infra, scheduler, or `src/` change. It fixes:

- **DEPLOY-1 invariants — cannot change without a new decision packet.**
  - **OS family:** Debian / Ubuntu LTS for the self-hosted reference environment.
  - **Tenancy:** single-community / single-tenant default for the first pilot deployment.
  - **Reachability:** public DNS + HTTPS required (not optional) for the self-hosted production-like contour.
  - **Raw-data durability:** off-box backup destination required (S3-compatible or equivalent); a local-only backup is **not** a sufficient DEPLOY-1 contour.
  - **Operator model:** an operator-facing, idempotent install/upgrade script that can bring a clean VPS from zero to a working deployment and upgrade it later with a clear status outcome.

- **DEPLOY-1 current defaults — revisable in DEPLOY-1.x as long as the invariants above remain intact.** Each revision must surface itself either as a small follow-up decision-log note or as the revising DEPLOY-1.x packet's docs update explicitly naming the default it revises (not an invariant).
  - **Reverse proxy / TLS terminator** (candidate set: Caddy / nginx / other ACME-capable proxy) — pinned in the DEPLOY-1.x packet that ships the proxy contour.
  - **Backup tool** (candidate set: restic / custom scripts around rclone / `pg_dump` / `pg_basebackup`) — pinned in the DEPLOY-1.x packet that wires the off-box sink.
  - **Installer implementation** (bash vs Python CLI; interactive vs non-interactive UX) — pinned in the DEPLOY-1.x packet that ships the install/upgrade script.

- **Roadmap doc.** `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` is the refinable-sequence companion to this decision — it carries the DEPLOY-1.x packet sequence, dependency notes, exit criteria, and the DEPLOY-2 forward pointer. This mirrors the D-042 / `RENAMING-ROADMAP.md` and D-044 / `OPERATIONALIZATION-ROADMAP.md` precedent: the decision entry carries the stable contract, the roadmap doc carries the refinable sequence.

- **A-22 closed; A-41 stays open, deferred.** A-22 (hosting target) is closed by this entry — the first implemented reference shape is the self-hosted VPS contour; managed cloud is the deferred second peer (DEPLOY-2). A-41 (which specific managed environment is the production reference) stays open and is explicitly **deferred until DEPLOY-2** so the original cloud-reference intent stays visible and pointed at that milestone.

### Why
DEPLOY-1 is the next non-local deployment the owner is bringing up — a real single-community Telegram-bound pilot on a VPS. Managed cloud has no near-term operator pulling it; resolving A-41 inside DEPLOY-1 would force a vendor choice for a shape no one is shipping. Locking only the invariants (not the tool choices) keeps DEPLOY-1.x packets bounded and lets tool decisions land alongside the code that depends on them (`[[feedback_packet_scope_discipline]]`, `[[feedback_separate_confirmed_from_proposed]]`). Explicitly deferring (not erasing) A-41 keeps the managed-cloud peer-shape expectation visible — peer parity is preserved as a property of the architecture, not deleted by this packet (`[[feedback_contract_decisions_in_decision_log]]`).

### Consequence
- New D-060 entry. D-026 / D-027 are referenced, **not edited in place**.
- New: `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` — invariants and current defaults mirrored from this entry (this entry stays authoritative), the DEPLOY-1.x packet sequence, dependency notes, exit criteria, and the DEPLOY-2 forward pointer.
- Changed: `docs/assumptions.md` — A-22 moved to "Recently closed" pointing at D-060; A-41 prose updated to mark deferred until DEPLOY-2; new A-42 (DEPLOY-1 invariants, closed by D-060) and A-43 (observability scope for the first VPS contour, open — pinned by the DEPLOY-1.x packet that ships observability).
- Changed: `docs/assumption-audit.md` — A-22 row struck through → D-060; new A-42 / A-43 rows.
- Changed: `docs/execution-map.md` — a new "Deployment-shape rollout" section after Phase 9 with DEPLOY-1.x placeholder rows pointing at `SELF-HOSTED-DEPLOYMENT-ROADMAP.md` and a single DEPLOY-2 deferred row.
- Changed: `docs/todo.md` — a new "DEPLOY-1 — Self-hosted VPS reference deployment" section listing DEPLOY-1.x packets in roadmap order with DEPLOY-1.1 marked landed; a trailing DEPLOY-2 deferred line.
- Changed: `docs/RUNBOOK.md` — a new "Self-hosted VPS reference shape (DEPLOY-1 / D-060)" section; invariant-level only (public DNS + HTTPS required; off-box backup destination required; operator-facing idempotent install/upgrade script; single-community / single-tenant default for the first pilot; Debian / Ubuntu LTS), with a pointer to the roadmap doc — no tool-specific runbook steps yet.
- Changed: `docs/OPERATIONALIZATION-ROADMAP.md` — "See also" section gains a pointer to `SELF-HOSTED-DEPLOYMENT-ROADMAP.md`. The Stage-2 §1..§5 body is **not** retrofitted; OP-1..OP-5 remain closed as-is.
- Changed: `docs/product/BuildPlan.md` — one bullet added to the "Target-state shape" list noting that D-060 fixes the implementation order (DEPLOY-1 self-hosted first, DEPLOY-2 managed cloud second peer) while preserving D-026 / D-027 peer parity.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` are deliberately **not** touched — the DEPLOY-1 invariants are deployment-level expectations and live here + in the roadmap doc until DEPLOY-1.x ships code that enforces them (`[[feedback_invariants_match_enforcement]]`). `docs/ARCHITECTURE.md`, `docs/product/PRD.md`, `docs/product/TechSpec.md`, `AGENTS.md`, `README.md`, `QUICKSTART.md`, and `docs/GLOSSARY.md` are also not touched — the D-026 / D-027 peer-parity framing in those docs is unchanged.
- **DEPLOY-1.1 is complete; DEPLOY-1 is in progress.** Every DEPLOY-1.x packet must cite "operates within DEPLOY-1 invariants — A-22 updated by D-060" in its own implementation plan.
- **Mitigation for the invariant-vs-default split.** The DEPLOY-1.x packet that ships the installer must design a configuration-versioning seam and a documented upgrade path so a later DEPLOY-1.x packet can swap a default (proxy / backup tool / installer implementation) within the invariant set without rewriting the installer. Recorded as a packet-design constraint here and in the roadmap doc; not work performed by DEPLOY-1.1.
- Out of scope (deferred to DEPLOY-1.2..DEPLOY-1.x or DEPLOY-2): Dockerfile, docker-compose VPS profile, reverse-proxy config + ACME automation, install/upgrade scripts and their UX, Telegram webhook registration automation, off-box backup sink implementation (integrates with the OP-4 WAL/base-backup primitives), observability sinks beyond a logs-first contour, end-to-end smoke for a clean-VPS → running-pilot run, the managed-cloud reference deployment (DEPLOY-2 reopens A-41); any schema / migration or `src/` change; any unrelated cleanup or refactor.

## D-061 — DEPLOY-1.2: VPS runtime shape (Dockerfile + docker-compose `vps` profile)

### Decision
DEPLOY-1.2 lands the first runnable VPS runtime contour. Operates within DEPLOY-1 invariants — A-22 updated by D-060. It adds:

- A `Dockerfile` for the application, built from the repo's `pyproject.toml` + `uv.lock` against `python:3.11-slim` (matches the `>=3.11,<3.12` interpreter requirement) using `uv sync --frozen --no-dev`. The image runs as a non-root user (UID 10001). The Dockerfile carries no `CMD`; each docker-compose service supplies its own command.
- A `.dockerignore` to keep the build context small and to prevent operator secrets (`.env`) and local caches (`.venv`, `.ruff_cache`, …) from leaking into the image.
- Two new docker-compose services, both gated by `profiles: ["vps"]` so a bare `docker compose up` is byte-equivalent to today (postgres + pg_archive_init only):
  - **`app_init`** — one-shot caller of `python -m memory_rag.storage.postgres.migrations_runner apply`. `depends_on: postgres: { condition: service_healthy }`; `restart: "no"`. Mirrors the existing `pg_archive_init` one-shot precedent. On a fresh volume this is what creates `CREATE EXTENSION vector` and the baseline schema, so the `_verify_pgvector` boot gate in `create_app()` succeeds once `app` starts.
  - **`app`** — uvicorn behind FastAPI. `depends_on: app_init: { condition: service_completed_successfully }`. Host port bound to `127.0.0.1:8000:8000` only — public exposure + TLS land in DEPLOY-1.3. `STORAGE_BACKEND=postgres` and `POSTGRES_HOST=postgres` are set at the compose level (compose-network/contour-specific overrides, not new knobs in `src/memory_rag/config.py`).

**User-confirmed choices for this packet (per `[[feedback_separate_confirmed_from_proposed]]`):**
- A separate one-shot compose service `app_init` is the migration bootstrap shape (not an entrypoint script inside the app image).
- Both new services are gated by `profiles: ["vps"]` (opt-in compose profile, mirroring the existing `backup` / `restore` profiles); the single canonical bring-up path is `docker compose --profile vps up -d --build`.
- The bounded runtime-shape validation is a docs-only manual smoke in `docs/RUNBOOK.md`; no new Make target.

**Runtime-shape choices made in this packet (revisable in later DEPLOY-1.x as long as DEPLOY-1 invariants hold):**
- Base image: `python:3.11-slim`.
- Dependency install: `uv sync --frozen --no-dev` (matches the repo's UV-based workflow; consumes `uv.lock`).
- Non-root runtime user: UID 10001.
- Host port binding: `127.0.0.1:8000:8000` (loopback only) until DEPLOY-1.3 fronts the app with a reverse proxy.

**Bounded runtime-shape validation evidence (per `[[feedback_harness_is_inspection_not_gate]]`).** "Smoke was run" is not a sufficient claim. The inspection evidence captured for DEPLOY-1.2 is:
1. `docker compose --profile vps ps` shows `postgres` running (healthy), `app_init` exited (0), `app` running.
2. `docker compose --profile vps logs app_init` contains the line `Postgres migrations applied to head.` (the migrations runner prints this on success).
3. `docker compose --profile vps logs app` contains the `app.created env=... version=... embedding_backend=...` line emitted by `create_app()` at startup.
4. `curl -fsS http://127.0.0.1:8000/health` returns HTTP 200 with the JSON `{"status":"ok","version":"<pkg-version>","env":"local"}`.

### Why
DEPLOY-1.1 fixed the contract (D-060 invariants + roadmap). The next dependency-ordered step is to produce something runnable: DEPLOY-1.3 (proxy), DEPLOY-1.4 (installer), DEPLOY-1.5 (webhook automation), and DEPLOY-1.6 (off-box backup sink) all need a runnable VPS runtime to terminate against — DEPLOY-1.2 is that termination point. Keeping the new services behind a `vps` profile preserves the current "docker compose up = postgres-only local dev" behavior, so DEPLOY-1.2 imposes no new burden on existing Stage-2 workflows (the OP-4 `backup` / `restore` profiles continue to work unchanged). Separating migration bootstrap into the `app_init` one-shot keeps the app image free of orchestration concerns and mirrors the existing `pg_archive_init` precedent (`[[feedback_packet_scope_discipline]]`).

### Consequence
- New: `Dockerfile`, `.dockerignore`.
- Changed: `docker-compose.yml` — appended `app_init` + `app` services, both gated by `profiles: ["vps"]`; no changes to existing `postgres`, `pg_archive_init`, `pg_backup`, `pg_restore`, or the `volumes:` block; OP-1 migrations and the OP-4 archive volume shape are reused unchanged.
- Changed: `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` — DEPLOY-1.2 row status set to "Landed (D-061)"; "Purpose & status" updated; no invariant or default changes.
- Changed: `docs/execution-map.md` — DEPLOY-1.2 row updated to a landed-shape pointer at `Dockerfile`, `.dockerignore`, the new compose services, and the RUNBOOK subsection.
- Changed: `docs/todo.md` — DEPLOY-1.2 marked done (D-061); **DEPLOY-1.3 is the only canonical "next"**; DEPLOY-1.6 keeps its existing wording with a short note that it is newly unblocked by DEPLOY-1.2 and may be pulled in parallel with the proxy / installer / webhook line, without elevating it to a co-canonical next.
- Changed: `docs/RUNBOOK.md` — new "VPS runtime shape (DEPLOY-1.2 / D-061)" subsection inside the existing "Self-hosted VPS reference shape (DEPLOY-1 / D-060)" section, containing the numbered, copy-paste-procedural manual smoke under the single canonical `docker compose --profile vps` path with explicit expected outputs.
- **No `src/` change**, no schema change, no migration change, no `pyproject.toml` / `uv.lock` change, no `Makefile` change, no `.env.example` change, no `tests/` change.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` deliberately **not** touched — the DEPLOY-1 invariants remain deployment-level expectations carried by D-060 + the roadmap doc until DEPLOY-1.x ships code that enforces them at runtime (`[[feedback_invariants_match_enforcement]]`).
- `docs/assumptions.md`, `docs/assumption-audit.md`, `docs/ARCHITECTURE.md`, `docs/product/{PRD,BuildPlan,TechSpec}.md`, `AGENTS.md`, `README.md`, `QUICKSTART.md`, `docs/GLOSSARY.md` — also not touched; D-060 already framed DEPLOY-1.x as not requiring further changes to canonical docs and DEPLOY-1.2 honors that.
- **DEPLOY-1.2 is complete; DEPLOY-1.3 is unblocked and is the canonical next packet; DEPLOY-1.6 is also unblocked and may be pulled in parallel with the proxy / installer / webhook line (per the roadmap §5 dependency graph), not co-canonical next.**
- Out of scope (deferred to DEPLOY-1.3..DEPLOY-1.7 or DEPLOY-2): reverse proxy + TLS + ACME (DEPLOY-1.3); operator-facing idempotent install/upgrade script + the configuration-versioning seam (DEPLOY-1.4); Telegram webhook auto-registration (DEPLOY-1.5); off-box backup sink wiring (DEPLOY-1.6, reuses OP-4 primitives unchanged); clean-VPS → working-pilot end-to-end smoke + upgrade drill (DEPLOY-1.7); managed-cloud reference deployment (DEPLOY-2 reopens A-41); any `src/`, schema, migration, retrieval, answer-path, or domain logic change; any pinning of future DEPLOY-1.x tool defaults (proxy / backup tool / installer language) beyond the runtime-shape choices DEPLOY-1.2 strictly needed; a `make app-up` / `make app-smoke` convenience target; a container-level healthcheck on the app service; any unrelated cleanup or refactor.

## D-062 — DEPLOY-1.3: reverse-proxy + TLS contour (Caddy + ACME automation)

### Decision
DEPLOY-1.3 lands the public reverse-proxy + TLS contour in front of the DEPLOY-1.2 runtime. Operates within DEPLOY-1 invariants — A-22 updated by D-060. It adds:

- A new `configs/caddy/Caddyfile`: a minimal declarative reverse-proxy config. A global `email {$ACME_EMAIL}` directive sets the Let's Encrypt registration email; a single site block keyed on `{$PUBLIC_HOSTNAME}` reverse-proxies to `app:8000` over the compose network. Nothing else — no HSTS, no security headers, no rate limits, no custom matchers, no `tls internal` fallback. The two Caddy defaults relied on are automatic HTTPS for the declared site (provisions + renews a certificate via ACME against `{$ACME_EMAIL}`) and the automatic HTTP → HTTPS redirect for a site declared with an HTTPS host. Any further hardening is deferred.
- A new docker-compose `caddy` service gated by `profiles: ["vps"]`, so a bare `docker compose up` stays byte-equivalent to today (postgres + pg_archive_init only). Image: `caddy:2-alpine`. `depends_on: { app: { condition: service_started } }`. Mounts `./configs/caddy/Caddyfile:/etc/caddy/Caddyfile:ro`, plus the named volumes `caddy_data` (cert + ACME state persistence — critical so a restart does not re-issue against Let's Encrypt rate limits) and `caddy_config`. Ports `0.0.0.0:80:80` and `0.0.0.0:443:443`. `restart: unless-stopped`. `PUBLIC_HOSTNAME` and `ACME_EMAIL` flow through from `.env`.
- Two new operator-facing knobs in `.env.example`: `PUBLIC_HOSTNAME` (fully-qualified DNS name pointing at the VPS) and `ACME_EMAIL` (Let's Encrypt registration email). Both empty by default. The inline comment states that both are required for the `vps` profile public-TLS contour and that no HTTP-only fallback path is configured.
- The DEPLOY-1.2 `app` service is **not** modified. Its `127.0.0.1:8000:8000` host port binding is retained explicitly as an **operator-only bypass-the-proxy inspection path** on the VPS host, not a closure criterion for DEPLOY-1.3.

**User-confirmed choices for this packet (per `[[feedback_separate_confirmed_from_proposed]]`):**
- Proxy / TLS terminator pinned: **Caddy**. Pins the D-060 §3 first default from the candidate set "Caddy / nginx / other ACME-capable proxy". Built-in ACME, single declarative Caddyfile, automatic HTTPS — smallest moving-part surface and aligns with the repo's preference for simple inspectable contours.
- The proxy lives inside the existing `vps` profile. The single canonical bring-up path stays `docker compose --profile vps up -d --build`; no new profile is introduced.
- The `app` service keeps its `127.0.0.1:8000:8000` loopback publish as an operator-only inspection path, not a closure signal.

**Runtime-shape choices made in this packet (revisable in later DEPLOY-1.x as long as DEPLOY-1 invariants hold):**
- Caddy image: `caddy:2-alpine`.
- Caddyfile minimal surface: only the two intentionally-configured behaviors (automatic HTTPS for the declared site + automatic HTTP → HTTPS redirect). No HSTS, no security headers, no rate limits, no `tls internal` fallback, no custom matchers / handlers.
- Persistence: a `caddy_data` named volume for cert + ACME state (so restarts do not re-issue against Let's Encrypt rate limits) and a `caddy_config` named volume for Caddy's mutable config store.
- Public binding: `0.0.0.0:80:80` and `0.0.0.0:443:443` on the host — the inbound surface required by the D-060 "public DNS + HTTPS required" invariant.

**Loopback is operator-only inspection, not closure (per `[[feedback_truthful_reply_distinction]]`).** DEPLOY-1.3 is **not** considered closed by `curl http://127.0.0.1:8000/health` alone. The retained loopback publish on `app` is an operator-only bypass-the-proxy inspection path; the decisive public-contour evidence is a successful `https://$PUBLIC_HOSTNAME/health` probe **plus** an HTTP → HTTPS redirect on `:80`, captured in the RUNBOOK operator-smoke step.

**Honest failure when required env vars are absent or invalid (per the Fallback Rule).** If `PUBLIC_HOSTNAME` or `ACME_EMAIL` is empty or invalid, the public-TLS contour does not come up cleanly: Caddy will not obtain a usable certificate for the declared site, and an external `https://$PUBLIC_HOSTNAME/health` probe will not succeed. The exact local failure mode (Caddyfile validation error vs. ACME challenge failure vs. Caddy running with an empty/unresolvable hostname) is not pinned by this packet — what **is** pinned is that **no degraded HTTP-only fallback path is configured**, so the contour does not silently succeed against a different shape than the operator requested.

**Bounded inspection validation evidence (per `[[feedback_harness_is_inspection_not_gate]]`).** Split into packet-closing evidence (sufficient to close DEPLOY-1.3 without real DNS) and real-VPS operator smoke (RUNBOOK-only, not a closure gate).

*Packet-closing inspection evidence (author/dev context, no real public DNS required):*
1. `docker compose --profile vps config` parses cleanly and lists the new `caddy` service with `PUBLIC_HOSTNAME` / `ACME_EMAIL` interpolated from `.env`, ports `80:80` and `443:443`, the Caddyfile mount, and the `caddy_data` + `caddy_config` named volumes.
2. With operator-shaped sample values exported into env, `docker run --rm -e PUBLIC_HOSTNAME=... -e ACME_EMAIL=... -v $PWD/configs/caddy/Caddyfile:/etc/caddy/Caddyfile:ro caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile` exits 0.
3. `docker compose up -d` (without `--profile vps`) still starts only `postgres` + `pg_archive_init` and no other service — confirms `caddy` is profile-gated and the D-061 byte-equivalence property is preserved.
4. Operator-side convenience (**not** the closure signal): `docker compose --profile vps up -d --build` stands up `postgres` / `app_init` / `app` / `caddy`, and the existing DEPLOY-1.2 loopback inspection `curl -fsS http://127.0.0.1:8000/health` still returns HTTP 200 — confirming the bypass-the-proxy inspection path is preserved.

*Real-VPS operator smoke (RUNBOOK-only, NOT a packet-closing gate; clean-VPS pilot smoke is DEPLOY-1.7's responsibility):*
- From a host outside the VPS: `curl -fsS -o /dev/null -w '%{http_code}\n' https://$PUBLIC_HOSTNAME/health` returns `200`.
- HTTP → HTTPS redirect: `curl -sI http://$PUBLIC_HOSTNAME/health` returns `301` or `308` to the `https://` URL.
- `docker compose --profile vps logs caddy` contains a cert-obtained / TLS handshake-success line for the configured hostname (the exact log-line shape is not pinned; the operator reads the logs, does not grep-match a fixed string).

### Why
DEPLOY-1.2 left the `app` port bound to loopback and documented that public exposure + TLS land in DEPLOY-1.3. DEPLOY-1.3 is the canonical dependency-ordered next step because both DEPLOY-1.4 (installer) and DEPLOY-1.5 (Telegram webhook auto-registration) need the public DNS + HTTPS contour to terminate against. Caddy is selected from the D-060 §3 candidate set because its built-in ACME automation and single declarative Caddyfile keep the proxy surface minimal and inspectable (`[[feedback_packet_scope_discipline]]`); a nginx + certbot split would add a separate renewal sidecar / cron without a corresponding benefit at this packet's scope. The configuration-versioning seam is deliberately not introduced here — D-060 assigns that to DEPLOY-1.4 (the installer packet) so a later DEPLOY-1.x packet can swap any default without rewriting the installer. The loopback `app` binding is retained, but the decision-log entry and RUNBOOK both state explicitly that loopback `/health` is operator-only inspection and not closure evidence — so DEPLOY-1.4 / DEPLOY-1.7 do not later treat loopback success as proxy-contour success (`[[feedback_truthful_reply_distinction]]`).

### Consequence
- New: `configs/caddy/Caddyfile`.
- Changed: `docker-compose.yml` — appended a new `caddy` service gated by `profiles: ["vps"]`, plus `caddy_data` and `caddy_config` entries in the `volumes:` block. No changes to existing `postgres`, `pg_archive_init`, `pg_backup`, `pg_restore`, `app_init`, or `app`. The `app` host port stays `127.0.0.1:8000:8000` as documented above.
- Changed: `.env.example` — appended a `# DEPLOY-1.3 / D-062 — public reverse-proxy + ACME (Caddy)` block with the two new knobs `PUBLIC_HOSTNAME=` and `ACME_EMAIL=`, both empty by default. No other env knob is added or changed.
- Changed: `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` — "Purpose & status" updated to reflect DEPLOY-1.3 landed (D-062); §3 first default ("Reverse proxy / TLS terminator") updated to record Caddy as pinned in DEPLOY-1.3 / D-062 (the candidate set is preserved as the source); §4 packet-sequence table — DEPLOY-1.3 row status set to "Landed (D-062)." Backup-tool and installer §3 defaults unchanged. No invariant changes.
- Changed: `docs/execution-map.md` — DEPLOY-1.3 row replaced with a landed-shape pointer at `configs/caddy/Caddyfile`, the new `caddy` compose service gated by `profiles: ["vps"]`, the two new `.env.example` knobs, and the RUNBOOK subsection.
- Changed: `docs/todo.md` — DEPLOY-1.3 marked done (D-062); **DEPLOY-1.4 is the sole canonical "next"**; DEPLOY-1.6 keeps its existing "newly unblocked by DEPLOY-1.2; may pull in parallel with the proxy / installer / webhook line, not co-canonical next" wording unchanged.
- Changed: `docs/RUNBOOK.md` — new "Reverse-proxy + TLS contour (DEPLOY-1.3 / D-062)" subsection inside the existing "Self-hosted VPS reference shape (DEPLOY-1 / D-060)" section, immediately after the DEPLOY-1.2 subsection. Contents: operator preconditions (DNS + firewall + the two env knobs); two clearly labeled inspection blocks (packet-closing local inspection that does not require real DNS, and real-VPS operator smoke documented as the operator-side smoke and not a packet-closing gate); the explicit "loopback `127.0.0.1:8000/health` is operator-only bypass-the-proxy inspection, not packet acceptance evidence on its own" statement; teardown via `docker compose --profile vps down` (without `-v` — Caddy cert state lives in `caddy_data`).
- **No `src/` change**, no schema change, no migration change, no `pyproject.toml` / `uv.lock` change, no `Makefile` change, no `Dockerfile` / `.dockerignore` change, no `tests/` change.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` deliberately **not** touched — the DEPLOY-1 invariants remain deployment-level expectations carried by D-060 + the roadmap doc until DEPLOY-1.x ships code that enforces them at runtime (`[[feedback_invariants_match_enforcement]]`).
- `docs/assumptions.md`, `docs/assumption-audit.md`, `docs/ARCHITECTURE.md`, `docs/product/{PRD,BuildPlan,TechSpec}.md`, `AGENTS.md`, `README.md`, `QUICKSTART.md`, `docs/GLOSSARY.md` — also not touched; D-060 already framed DEPLOY-1.x as not requiring further changes to canonical docs and DEPLOY-1.3 honors that.
- **DEPLOY-1.3 is complete; DEPLOY-1.4 is unblocked and is the sole canonical next packet; DEPLOY-1.5 stays blocked on DEPLOY-1.4; DEPLOY-1.6 remains the parallel-pullable packet unblocked by DEPLOY-1.2.**
- Out of scope (deferred to DEPLOY-1.4..DEPLOY-1.7 or DEPLOY-2): operator-facing idempotent install/upgrade script + the configuration-versioning seam (DEPLOY-1.4); Telegram webhook auto-registration against the new public DNS contour (DEPLOY-1.5); off-box backup sink wiring (DEPLOY-1.6, reuses OP-4 primitives unchanged); logs-first observability scope A-43 (DEPLOY-1.6); clean-VPS → working-pilot end-to-end smoke + upgrade drill (DEPLOY-1.7); managed-cloud reference deployment (DEPLOY-2 reopens A-41); any `src/`, schema, migration, retrieval, answer-path, or domain logic change; HSTS, security headers, rate limits, and any other Caddy hardening beyond automatic HTTPS + HTTP → HTTPS redirect; a deterministic local failure mechanism for missing `PUBLIC_HOSTNAME` / `ACME_EMAIL` (e.g., a pre-Caddy init validator) — this packet pins only the absence of a degraded fallback path, not a specific failure exit shape; `make app-up` / `make caddy-up` / `make proxy-smoke` convenience targets; a container-level healthcheck on the `app` service; any pinning of future DEPLOY-1.x tool defaults (backup tool / installer language) beyond the proxy default this packet strictly needed; any unrelated cleanup or refactor.

## D-063 — DEPLOY-1.4: installer / upgrade script (bash, non-interactive) + configuration-versioning seam

### Decision
DEPLOY-1.4 lands the operator-facing, idempotent install/upgrade script for the self-hosted VPS reference deployment. Operates within DEPLOY-1 invariants — A-22 updated by D-060. It adds:

- A new `scripts/installer/deploy.sh` — a non-interactive bash script that wraps the canonical bring-up `docker compose --profile vps up -d --build` (DEPLOY-1.2 / D-061 + DEPLOY-1.3 / D-062). Single canonical operator command: `./scripts/installer/deploy.sh`. Subcommands `--check` (preflight only; writes nothing), `--status` (print state file or "not installed"), `--version` (print `INSTALLER_CONFIG_VERSION`), `--help` (usage). The default no-arg invocation installs on a fresh host, idempotently re-applies on an already-installed host, or runs the appropriate `migrate_v<old>_to_v<new>` helpers when the deployed config is older than the installer.
- The configuration-versioning seam D-060 explicitly defers to this packet: an `INSTALLER_CONFIG_VERSION=1` constant in `deploy.sh` paired with an installer-owned `.installer-state.json` next to the repo root. The script compares the two and applies migrations in order, lowest → highest. A deployed config newer than the installer is refused with `deploy.upgrade.error` and exits non-zero without invoking `docker compose up`. At this packet only `migrate_to_v1` exists, materialized as the v1 stamp written by `write_state_success` on a successful fresh install; future DEPLOY-1.x packets that swap or add a default (e.g., DEPLOY-1.6 pinning the backup-tool default) bump `INSTALLER_CONFIG_VERSION` and add a new `migrate_v<old>_to_v<new>` helper rather than rewriting the installer.
- A `.gitignore` entry for `.installer-state.json` and its sibling failure marker `.installer-state.last_failure.json` — both are per-host operator state and must never be committed.

The installer reads `.env` (it does not write it; the user-confirmed UX is non-interactive). Preflight verifies, in order: `docker` on PATH; `docker compose version` exits 0 (Compose v2 plugin required — v1 is unsupported); cwd resolves to a repo root via `Dockerfile` + `docker-compose.yml` + `pyproject.toml` co-located; `.env` exists; `.env` has non-empty values for `POSTGRES_PASSWORD`, `PUBLIC_HOSTNAME`, and `ACME_EMAIL` (the three keys the `vps`-profile public-TLS contour requires per DEPLOY-1.3 / D-062). A preflight failure under the no-arg install path writes `.installer-state.last_failure.json` and exits non-zero; the same preflight under `--check` exits non-zero with the same diagnostic but writes nothing.

After a successful `docker compose --profile vps up -d --build`, the installer probes two distinct paths and records them honestly per `[[feedback_truthful_reply_distinction]]`:

- **Mandatory:** `http://127.0.0.1:8000/health` (the DEPLOY-1.2 loopback inspection path that DEPLOY-1.3 / D-062 explicitly framed as operator-only bypass-the-proxy inspection, not closure evidence). Bounded retry: 15 attempts × 2s = 30s. A non-200 outcome fails the run and writes the failure marker.
- **Best-effort:** `https://$PUBLIC_HOSTNAME/health` only when `PUBLIC_HOSTNAME` is set AND resolves on the host (a single `getent hosts` lookup). Recorded as one of `"ok"`, `"failed"`, `"skipped (PUBLIC_HOSTNAME unset)"`, `"skipped (hostname did not resolve)"`. A skipped or failed public-TLS probe does **not** fail the run on its own — the clean-VPS pilot smoke + the decisive public-TLS contour evidence remains DEPLOY-1.7's responsibility; this installer's job is the bring-up + state seam, not full-contour acceptance.

**User-confirmed choices for this packet (per `[[feedback_separate_confirmed_from_proposed]]`):**
- **Installer language pinned: bash.** Pins the D-060 §3 third default from the candidate set `bash vs Python CLI`. Single `scripts/installer/deploy.sh` mirroring the existing `scripts/pg_backup/*.sh` and `scripts/pg_restore/restore.sh` precedent; host-side prereq is only Docker (Python only runs inside the app image). The installer at this packet's scope is fundamentally a docker-compose orchestrator + state seam, and bash is the smallest moving-part surface for that role.
- **Installer UX pinned: non-interactive only.** Pins the D-060 §3 third default from the candidate set `interactive vs non-interactive UX`. The operator pre-fills `.env` from `.env.example` (the existing DEPLOY-1.2 / 1.3 RUNBOOK pattern); the installer reads it, preflights, runs the canonical bring-up, writes the status outcome. Deterministic, scriptable, and matches the existing copy-paste-procedural smoke shape.
- **Configuration-version surface pinned: installer-owned state file only.** A `.installer-state.json` next to the repo root paired with an `INSTALLER_CONFIG_VERSION` constant in the script. The operator does not edit it. Keeps `.env` a true operator-knob surface and avoids the desync failure mode of mirrored knobs.

**Runtime-shape choices made in this packet (proposed defaults within the user-confirmed seam; revisable in later DEPLOY-1.x as long as DEPLOY-1 invariants hold):**
- State-file name `.installer-state.json` (alongside `.installer-state.last_failure.json` for the failure marker); both at the repo root.
- State-file JSON shape — `installer_config_version`, `selected_defaults` (`reverse_proxy=caddy`, `installer_impl=bash`, `backup_tool=null` — the third stays `null` until DEPLOY-1.6 pins the backup-tool default), `last_install_timestamp`, `last_outcome`, `loopback_health`, `public_tls_probe`.
- Subcommand names: `--check`, `--status`, `--version`, `--help`. The no-arg invocation is the canonical install/upgrade path.
- Three preflight env keys: `POSTGRES_PASSWORD`, `PUBLIC_HOSTNAME`, `ACME_EMAIL`. (The other `.env` knobs are not required for the public-TLS contour to come up cleanly per DEPLOY-1.3 / D-062.)
- Log-line prefix shape `deploy.<phase>.<status>` (e.g., `deploy.preflight.ok`, `deploy.upgrade.error`) mirroring the existing `pg_backup.*` / `pg_restore.*` prefixes already in the repo.
- Bounded loopback probe: 15 × 2 s = up to 30 s.

**Honest status outcome (per `[[feedback_truthful_reply_distinction]]`).** The installer never reports a "success" outcome based on the public-TLS probe alone, nor inflates a loopback success into a public-TLS claim. `last_outcome="success"` requires `loopback_health="ok"`; `public_tls_probe` is a separate field whose value is one of four honest verdicts. The decisive clean-VPS public-contour evidence remains DEPLOY-1.7's responsibility.

**Bounded inspection validation evidence (per `[[feedback_harness_is_inspection_not_gate]]`).** Split into packet-closing evidence (sufficient to close DEPLOY-1.4 on a dev host without a real VPS) and real-VPS operator smoke (RUNBOOK-only, not a closure gate; clean-VPS pilot smoke + the upgrade drill is DEPLOY-1.7's responsibility).

*Packet-closing inspection evidence (author/dev context, no real public DNS required):*
1. `bash -n scripts/installer/deploy.sh` exits 0 — syntactic validity.
2. `./scripts/installer/deploy.sh --help` prints usage and exits 0.
3. `./scripts/installer/deploy.sh --version` prints `1` and exits 0.
4. `./scripts/installer/deploy.sh --status` against an absent state file prints `not installed (no .installer-state.json at <repo>)` and exits 0; against a present state file prints the file contents and exits 0.
5. `./scripts/installer/deploy.sh --check` against a missing `.env` exits non-zero with `deploy.preflight.error missing .env at <repo>/.env ...` and writes neither `.installer-state.json` nor the failure marker.
6. `./scripts/installer/deploy.sh --check` against a `.env` whose required keys are empty (e.g., `PUBLIC_HOSTNAME=` / `ACME_EMAIL=` straight from `.env.example`) exits non-zero with `deploy.preflight.error .env is missing or empty for required keys: PUBLIC_HOSTNAME ACME_EMAIL ...` and writes nothing.
7. `./scripts/installer/deploy.sh --check` against an operator-shaped `.env` (the three required keys non-empty) exits 0 with `deploy.preflight.ok installer_config_version=1 ...` and writes nothing.
8. Future-version refusal: with `.installer-state.json` hand-edited to set `installer_config_version: 99`, the no-arg `./scripts/installer/deploy.sh` exits non-zero with `deploy.upgrade.error deployed config v99 is newer than this installer v1 ...`, does **not** invoke `docker compose up`, writes `.installer-state.last_failure.json`, and leaves `.installer-state.json` byte-equivalent to the hand-edited input.
9. Bare-`up` byte-equivalence: `docker compose config --services` returns only `postgres` + `pg_archive_init`, and `docker compose --profile vps config --services` returns those plus `app`, `app_init`, `caddy` — confirms DEPLOY-1.4 does not regress the DEPLOY-1.2 / 1.3 byte-equivalence property (no `docker-compose.yml` change).

*Real-VPS operator smoke (RUNBOOK-only, NOT a packet-closing gate; clean-VPS pilot smoke + upgrade drill is DEPLOY-1.7's responsibility):*
- From a clean Debian / Ubuntu LTS VPS with Docker installed, the repo cloned to a working directory, DNS for `$PUBLIC_HOSTNAME` resolving to the host, inbound TCP 80 + 443 open, and `.env` filled with the four operator-required keys: `./scripts/installer/deploy.sh` exits 0 with `deploy.install.ok ... loopback_health=ok public_tls_probe="ok"` and `.installer-state.json` records `last_outcome="success"`.
- A second invocation on the same VPS exits 0 idempotently, prints `deploy.install.ok already_at_v1 re-applied ...`, refreshes only `last_install_timestamp`, and leaves the rest of the state file byte-equivalent.

### Why
DEPLOY-1.3 left the public-TLS contour requiring an operator to copy-paste the canonical `docker compose --profile vps up -d --build` from the RUNBOOK and to know that the loopback `/health` is not closure evidence. DEPLOY-1.4 is the canonical dependency-ordered next step because both DEPLOY-1.5 (Telegram webhook auto-registration) and DEPLOY-1.7 (clean-VPS smoke + upgrade drill) terminate against the installer's status outcome. Bash + non-interactive + an installer-owned state file are the smallest moving-part surfaces for an installer that mostly orchestrates the existing canonical compose path — a Python CLI would add a host-side Python prereq the bash path does not need, and a mirrored env-knob version surface would duplicate state across two files the operator can desync (`[[feedback_packet_scope_discipline]]`). The configuration-versioning seam is realized as the smallest mechanism that future DEPLOY-1.x packets can extend without rewriting the installer: bump the constant, add a `migrate_v<old>_to_v<new>` helper. The state file reserves `selected_defaults.backup_tool` for DEPLOY-1.6 to populate but does not pre-decide that default — per `[[feedback_packet_scope_discipline]]`, the seam is shaped, not pre-implemented.

### Consequence
- New: `scripts/installer/deploy.sh` (executable, `#!/usr/bin/env bash`, `set -eu`; carries `INSTALLER_CONFIG_VERSION=1` + `migrate_to_v1`).
- Changed: `.gitignore` — appended `.installer-state.json` and `.installer-state.last_failure.json` entries with an inline DEPLOY-1.4 / D-063 comment; no other `.gitignore` change.
- Changed: `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` — "Purpose & status" updated to reflect DEPLOY-1.4 landed (D-063); §3 "Installer implementation" default updated to record bash + non-interactive as pinned in DEPLOY-1.4 / D-063 (the candidate set is preserved as the source); §3 "Default-stability mitigation" paragraph updated to point at the realized seam (`scripts/installer/deploy.sh` carrying `INSTALLER_CONFIG_VERSION` + the `.installer-state.json` state file with named `migrate_v<i>_to_v<i+1>` helpers); §4 packet-sequence table — DEPLOY-1.4 row status set to "Landed (D-063)". Backup-tool default and invariants unchanged.
- Changed: `docs/execution-map.md` — DEPLOY-1.4 row replaced with a landed-shape pointer at `scripts/installer/deploy.sh`, the new `.gitignore` entries, the configuration-versioning seam (`.installer-state.json` + `INSTALLER_CONFIG_VERSION`), and the RUNBOOK subsection.
- Changed: `docs/todo.md` — DEPLOY-1.4 marked done (D-063); **DEPLOY-1.5 is the sole canonical "next"**; DEPLOY-1.6 keeps its existing "newly-unblocked by DEPLOY-1.2; parallel-pullable, not co-canonical next" wording unchanged.
- Changed: `docs/RUNBOOK.md` — new "Installer / upgrade script (DEPLOY-1.4 / D-063)" subsection inside the existing "Self-hosted VPS reference shape (DEPLOY-1 / D-060)" section, immediately after the DEPLOY-1.3 subsection. Contents: operator pre-conditions (Docker + Docker Compose v2 + `.env` populated); the single canonical install command and idempotent re-run semantics; the configuration-versioning seam (`.installer-state.json` + `INSTALLER_CONFIG_VERSION` + the future-version refusal branch); the honest status-outcome distinction (mandatory loopback vs best-effort public-TLS); the `--check` / `--status` / `--version` / `--help` subcommands with copy-paste examples; teardown unchanged.
- **No `src/` change**, no schema change, no migration change, no `pyproject.toml` / `uv.lock` change, no `Makefile` change, no `Dockerfile` / `.dockerignore` change, no `docker-compose.yml` change, no `.env.example` change, no `configs/caddy/Caddyfile` change, no `tests/` change.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` deliberately **not** touched — the DEPLOY-1 invariants remain deployment-level expectations carried by D-060 + the roadmap doc until DEPLOY-1.x ships code that enforces them at runtime (`[[feedback_invariants_match_enforcement]]`).
- `docs/assumptions.md`, `docs/assumption-audit.md`, `docs/ARCHITECTURE.md`, `docs/product/{PRD,BuildPlan,TechSpec}.md`, `AGENTS.md`, `README.md`, `QUICKSTART.md`, `docs/GLOSSARY.md` — also not touched; D-060 already framed DEPLOY-1.x as not requiring further changes to canonical docs and DEPLOY-1.4 honors that. A-42 stays closed by D-060; A-43 stays open and is pinned by DEPLOY-1.6.
- **DEPLOY-1.4 is complete; DEPLOY-1.5 is unblocked and is the sole canonical next packet; DEPLOY-1.6 remains the parallel-pullable packet unblocked by DEPLOY-1.2.**
- Out of scope (deferred to DEPLOY-1.5..DEPLOY-1.7 or DEPLOY-2): Telegram webhook auto-registration (DEPLOY-1.5); off-box backup sink wiring (DEPLOY-1.6, reuses OP-4 primitives unchanged; pins the backup-tool default and may populate `selected_defaults.backup_tool` in the state file); logs-first observability scope A-43 (DEPLOY-1.6); clean-VPS → working-pilot end-to-end smoke + upgrade drill (DEPLOY-1.7); managed-cloud reference deployment (DEPLOY-2 reopens A-41); any `src/`, schema, migration, retrieval, answer-path, or domain-logic change; any non-trivial exercise of the configuration-versioning seam beyond the no-op `migrate_to_v1` (that lands with the first later DEPLOY-1.x packet that swaps or adds a default); any `make deploy-*` convenience target (per the DEPLOY-1.2 / 1.3 precedent of explicitly deferring convenience targets at the packet that introduces a primary path); any interactive UX variant; any pinning of future DEPLOY-1.x tool defaults beyond the installer-language / UX defaults this packet strictly needed; any unrelated cleanup or refactor.

## D-064 — DEPLOY-1.5: Telegram webhook auto-registration + first non-trivial use of the configuration-versioning seam

### Decision
DEPLOY-1.5 folds Telegram webhook registration into the DEPLOY-1.4 installer flow against the DEPLOY-1.3 public DNS + HTTPS contour. Operates within DEPLOY-1 invariants — A-22 updated by D-060. It changes `scripts/installer/deploy.sh` only:

- The canonical no-arg `./scripts/installer/deploy.sh` now calls Telegram `setWebhook` after the loopback + public-TLS probes succeed, registering `https://$PUBLIC_HOSTNAME/telegram/webhook` with the operator-filled `TELEGRAM_WEBHOOK_SECRET`. Bounded retry: 3 attempts × 2 s = up to 6 s budget. The result is recorded as one of `registered (<url>)`, `skipped (public_tls_probe=<value>)`, or `failed (<short reason ≤200 chars>)` and written into a new `webhook_registration` block in `.installer-state.json`. Webhook registration is best-effort — a failure does **not** fail the run (mirrors `public_tls_probe` per `[[feedback_truthful_reply_distinction]]`); `last_outcome="success"` still requires only the mandatory loopback `/health` to be `"ok"`.
- A new `--unregister-webhook` subcommand calls Telegram `deleteWebhook` against the bot token in `.env` and, on `ok:true`, re-emits `.installer-state.json` with `webhook_registration.status="unregistered"`, `url=null`, and a fresh `attempted_at`. On a Telegram non-ok response or filesystem error the state file is left untouched and the script exits non-zero. The clearing step is skipped when no state file is present (operator can still run the API call to clear a stale webhook from any host).
- `REQUIRED_ENV_KEYS` grows by two entries — `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` — so both `--check` and the no-arg install path now refuse to proceed without the Telegram credentials the pilot needs. The preflight diagnostic line keeps the existing `deploy.preflight.error .env is missing or empty for required keys: …` shape.
- `INSTALLER_CONFIG_VERSION` bumps `1 → 2`. A new `migrate_v1_to_v2()` helper joins the chain after `migrate_to_v1`; it is a no-op stamp (the new state-file shape is materialized by the next `write_state_success` call). This is the first DEPLOY-1.x packet to exercise the D-063 configuration-versioning seam by appending a helper. Forward-version refusal continues to work — a hand-edited `installer_config_version: 99` is still refused with `deploy.upgrade.error ... v2 ...` before any `docker compose up`.

External-system behavior relied on (per `[[feedback_no_fabricated_external_requirements]]`): the Telegram Bot API `setWebhook` and `deleteWebhook` methods documented at <https://core.telegram.org/bots/api>. `setWebhook` is idempotent — a repeated call overwrites the prior URL and secret — and `deleteWebhook` returns `ok:true` even when no webhook is currently set. No other API surface is assumed.

**User-confirmed choices for this packet (per `[[feedback_separate_confirmed_from_proposed]]`):**
- **Telegram credentials are preflight-required.** `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` join `REQUIRED_ENV_KEYS` so the installer never reports `last_outcome="success"` on a Telegram-bound pilot with empty credentials. Avoids a "skipped (telegram credentials unset)" degenerate-success branch in the state file.
- **`--unregister-webhook` subcommand.** Adds a single new subcommand symmetric with the install path; bumps the subcommand surface from 4 to 5 (`--check`, `--status`, `--version`, `--unregister-webhook`, `--help`). Operator teardown becomes one command; rotation remains a no-op (re-run `./scripts/installer/deploy.sh` — `setWebhook` is idempotent).

**Proposed defaults within the user-confirmed seam (revisable in later DEPLOY-1.x as long as DEPLOY-1 invariants hold):**
- Webhook registration bounded retry budget: 3 × 2 s = up to 6 s (smaller than the 30 s loopback budget — `setWebhook` is a single synchronous API call, not a process-readiness wait).
- Reason string capture: first 200 characters of the Telegram response body on a `failed (...)` outcome.
- Log-line prefix: `deploy.webhook.*` (`deploy.webhook.unregistered ok` / `deploy.webhook.error …`) mirroring the existing `deploy.preflight.*` / `deploy.upgrade.*` family.
- `--unregister-webhook` does **not** pass `drop_pending_updates=true`; pending-update retention is Telegram's default and is fine for the pilot teardown case.

**Honest status outcome (per `[[feedback_truthful_reply_distinction]]`).** Webhook registration sits on top of the public-TLS probe — when `public_tls_probe != "ok"` (skipped / failed) the webhook is recorded as `skipped (public_tls_probe=<value>)`, not `failed`, so the operator can see the upstream cause. The installer never inflates a webhook success into a public-TLS claim or vice versa; the three honest verdicts are surfaced separately.

**Bounded inspection validation evidence (per `[[feedback_harness_is_inspection_not_gate]]`).** Split into packet-closing evidence (sufficient to close DEPLOY-1.5 on a dev host without a real VPS or real Telegram bot) and real-VPS operator smoke (RUNBOOK-only, NOT a closure gate; clean-VPS pilot smoke + the upgrade drill is DEPLOY-1.7's responsibility).

*Packet-closing inspection evidence (author/dev context, no real public DNS or real bot required):*
1. `bash -n scripts/installer/deploy.sh` exits 0 — syntactic validity.
2. `./scripts/installer/deploy.sh --version` prints `2` and exits 0.
3. `./scripts/installer/deploy.sh --help` prints usage including the `--unregister-webhook` line and exits 0.
4. `./scripts/installer/deploy.sh --status` against an absent state file prints `not installed (no .installer-state.json at <repo>)` and exits 0.
5. `./scripts/installer/deploy.sh --check` against a `.env` whose only filled keys are `POSTGRES_PASSWORD` / `PUBLIC_HOSTNAME` / `ACME_EMAIL` (the DEPLOY-1.4 example) exits non-zero with `deploy.preflight.error .env is missing or empty for required keys: TELEGRAM_BOT_TOKEN TELEGRAM_WEBHOOK_SECRET — fill them ...` and writes nothing.
6. `./scripts/installer/deploy.sh --check` against a `.env` with all five required keys filled (Telegram credentials may be placeholders for `--check`) exits 0 with `deploy.preflight.ok installer_config_version=2 repo_root=<repo>` and writes nothing.
7. `./scripts/installer/deploy.sh --unregister-webhook` against a missing `.env` exits non-zero with `deploy.webhook.error missing .env at <repo>/.env — fill TELEGRAM_BOT_TOKEN before unregistering` and writes nothing.
8. `./scripts/installer/deploy.sh --unregister-webhook` against a `.env` with empty `TELEGRAM_BOT_TOKEN` exits non-zero with `deploy.webhook.error TELEGRAM_BOT_TOKEN unset in .env — cannot call deleteWebhook` and writes nothing.
9. Future-version refusal: with `.installer-state.json` hand-edited to `installer_config_version: 99`, the no-arg `./scripts/installer/deploy.sh` exits non-zero with `deploy.upgrade.error deployed config v99 is newer than this installer v2 ...`, does **not** invoke `docker compose up`, writes `.installer-state.last_failure.json`, and leaves `.installer-state.json` byte-equivalent to the hand-edited input.
10. Bare-`up` byte-equivalence: `docker compose config --services | sort` returns only `pg_archive_init postgres`, and `docker compose --profile vps config --services | sort` returns `app app_init caddy pg_archive_init postgres` — confirms DEPLOY-1.5 does not regress the DEPLOY-1.2 / 1.3 / 1.4 byte-equivalence property (no `docker-compose.yml` change).

*Real-VPS operator smoke (RUNBOOK-only, NOT a packet-closing gate; clean-VPS pilot smoke + upgrade drill is DEPLOY-1.7's responsibility):*
- From a clean Debian / Ubuntu LTS VPS with the DEPLOY-1.4 pre-conditions plus the two new env keys filled with a real bot token + secret: `./scripts/installer/deploy.sh` exits 0 with `deploy.install.ok ... loopback_health=ok public_tls_probe="ok" webhook_registration="registered (https://<host>/telegram/webhook)"`; `--status` shows the v2 state file with the populated `webhook_registration` block.
- `./scripts/installer/deploy.sh --unregister-webhook` exits 0 with `deploy.webhook.unregistered ok`; the state file's `webhook_registration.status` becomes `"unregistered"`; the Telegram side reports no webhook (`getWebhookInfo` returns the empty URL).
- The v1 → v2 cross-version migration end-to-end against a real previously-installed v1 VPS is DEPLOY-1.7's responsibility — recorded honestly per `[[feedback_harness_is_inspection_not_gate]]`.

### Why
DEPLOY-1.4 left the operator one manual `curl .../setWebhook` step short of a runnable Telegram-bound pilot; the DEPLOY-1 exit criterion (`SELF-HOSTED-DEPLOYMENT-ROADMAP.md` §6) explicitly calls out webhook registration against the public surface as a closure signal. Folding registration into the canonical install command is the smallest change that closes that gap without expanding the installer's role beyond "wraps the canonical compose path + records honest outcomes" (`[[feedback_packet_scope_discipline]]`). Adding it as a best-effort step rather than a mandatory probe matches the `public_tls_probe` precedent — the loopback `/health` remains the only mandatory readiness signal, so a transient Telegram outage doesn't fail an otherwise healthy install. The `--unregister-webhook` subcommand is the smallest moving-part teardown surface; without it, operators would have to handcraft a curl line, leaving the state file silently stale. Bumping `INSTALLER_CONFIG_VERSION` to 2 and appending `migrate_v1_to_v2` exercises the D-063 configuration-versioning seam as the seam was designed to be exercised (`[[feedback_invariants_match_enforcement]]`).

### Consequence
- Changed: `scripts/installer/deploy.sh` — `INSTALLER_CONFIG_VERSION` bumped `1 → 2`; `REQUIRED_ENV_KEYS` extended with `TELEGRAM_BOT_TOKEN TELEGRAM_WEBHOOK_SECRET`; new `register_telegram_webhook` helper; `write_state_success` signature extended with `webhook_status` + `webhook_url` parameters and JSON body extended with a `webhook_registration` block; new `read_state_string` helper; new `write_state_unregistered` helper; new `migrate_v1_to_v2` no-op stamp + `run_migrations` chain extended; new `cmd_unregister_webhook` + `--unregister-webhook` arg-dispatch branch; usage text updated.
- Changed: `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` — "Purpose & status" updated to reflect DEPLOY-1.5 landed (D-064); §3 "Default-stability mitigation" paragraph updated to record `INSTALLER_CONFIG_VERSION=2` and the first non-trivial chain extension (`migrate_v1_to_v2`); §4 packet-sequence table — DEPLOY-1.5 row status set to "Landed (D-064)". Invariants and reverse-proxy / backup-tool / installer-language defaults unchanged.
- Changed: `docs/execution-map.md` — DEPLOY-1.5 row replaced with a landed-shape pointer at `scripts/installer/deploy.sh` (the `register_telegram_webhook` helper + the `webhook_registration` state-file block + the `--unregister-webhook` subcommand + the v1 → v2 bump) and the new RUNBOOK subsection.
- Changed: `docs/todo.md` — DEPLOY-1.5 marked done (D-064); **DEPLOY-1.6 is the sole canonical "next"**; DEPLOY-1.7 wording unchanged.
- Changed: `docs/RUNBOOK.md` — new "Telegram webhook registration (DEPLOY-1.5 / D-064)" subsection inside the existing "Self-hosted VPS reference shape (DEPLOY-1 / D-060)" section, immediately after the DEPLOY-1.4 subsection. Contents: the two new preflight env keys (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`); the registration lifecycle (initial via `./scripts/installer/deploy.sh`; rotation via re-running the same canonical command — `setWebhook` is idempotent; teardown via `./scripts/installer/deploy.sh --unregister-webhook`); the honest registration-outcome distinction (`registered (url)` / `skipped (public_tls_probe=...)` / `failed (...)`) and its place in the state-file shape; packet-closing local inspection block; real-VPS operator smoke. The existing DEPLOY-1.4 "Packet-closing local inspection" block is amended so its example `.env` includes placeholder `TELEGRAM_BOT_TOKEN` / `TELEGRAM_WEBHOOK_SECRET` values, its expected preflight error reflects the new five-key list, and its expected `--version` / `--check` output reflects v2.
- **No `src/` change**, no schema change, no migration change, no `pyproject.toml` / `uv.lock` change, no `Makefile` change, no `Dockerfile` / `.dockerignore` change, no `docker-compose.yml` change, no `.env.example` change (`TELEGRAM_BOT_TOKEN` / `TELEGRAM_WEBHOOK_SECRET` already exist there from Slice 1.x), no `.gitignore` change, no `configs/caddy/Caddyfile` change, no `tests/` change.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` deliberately **not** touched — the DEPLOY-1 invariants remain deployment-level expectations carried by D-060 + the roadmap doc until DEPLOY-1.x ships code that enforces them at runtime (`[[feedback_invariants_match_enforcement]]`).
- `docs/assumptions.md`, `docs/assumption-audit.md`, `docs/ARCHITECTURE.md`, `docs/product/{PRD,BuildPlan,TechSpec}.md`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `QUICKSTART.md`, `docs/GLOSSARY.md` — also not touched. A-42 stays closed by D-060; A-43 stays open and is pinned by DEPLOY-1.6. QUICKSTART's tunnel-based local-dev `setWebhook` recipe (D-019) is unchanged — DEPLOY-1.5 is a self-hosted-VPS installer concern.
- **DEPLOY-1.5 is complete; DEPLOY-1.6 is the sole canonical next packet; DEPLOY-1.7 unblocks once DEPLOY-1.6 lands.**
- Out of scope (deferred to DEPLOY-1.6..DEPLOY-1.7 or DEPLOY-2): off-box backup sink wiring (DEPLOY-1.6, reuses OP-4 primitives unchanged; pins the backup-tool default and populates `selected_defaults.backup_tool` in the state file via another `INSTALLER_CONFIG_VERSION` bump + `migrate_v2_to_v3`); logs-first observability scope A-43 (DEPLOY-1.6); clean-VPS → working-pilot end-to-end smoke + upgrade drill (DEPLOY-1.7); managed-cloud reference deployment (DEPLOY-2 reopens A-41); any `src/`, schema, migration, retrieval, answer-path, or domain-logic change; auto-generation of `TELEGRAM_WEBHOOK_SECRET` (the installer reads `.env` and does not write it, per D-063); a `drop_pending_updates=true` variant of the teardown call; a webhook round-trip health probe (DEPLOY-1.7's end-to-end smoke); any `make deploy-*` convenience target; any interactive UX variant; any unrelated cleanup or refactor.

## D-065 — DEPLOY-1.6: off-box backup sink wiring + backup-tool default (`rclone`)

### Decision
DEPLOY-1.6 wires the existing OP-4 WAL + base-backup artifacts (`/archive/base/...`, `/archive/wal/...` — D-053 / D-054 / D-055) to an operator-supplied S3-compatible destination, and pins the §3 backup-tool default. Operates within DEPLOY-1 invariants — A-22 updated by D-060. The packet wires the OP-4 primitives off-box; it does not re-decide them.

- A new `pg_offbox_uploader` sidecar service in `docker-compose.yml` (image `rclone/rclone:1.66`, profile `["backup"]`, `restart: unless-stopped`, `depends_on: pg_backup`) running a long-running poll loop at `scripts/pg_offbox_uploader/uploader.sh`. The uploader polls `/archive/last_success.json` — the OP-4.2 durable success marker written by `scripts/pg_backup/scheduler.sh` after a clean backup+prune cycle — and on a previously-unseen cycle runs `rclone sync /archive/base → remote:${BACKUP_S3_BUCKET}/${PREFIX}/base` then `rclone sync /archive/wal → remote:${BACKUP_S3_BUCKET}/${PREFIX}/wal`. It writes the outcome to `/archive/last_offbox.json` (timestamp, base_backup, status, error?). The uploader emits one log line per outcome: `pg_backup.offbox.ok base=<…>`, `pg_backup.offbox.skipped reason=<…>`, or `pg_backup.offbox.error stage=<base|wal> reason=<auth_failed|network|remote_error|temporary|fatal> rc=<n>`. Same `pg_backup.*` log-prefix family as `scheduler.sh` — no new logging contract is introduced (A-43 deferred — see below).
- A new best-effort `probe_offbox_backup` helper in `scripts/installer/deploy.sh`, modeled on `probe_public_tls`. Called after `register_telegram_webhook`. Returns one of `"ok"`, `"skipped (BACKUP_S3_BUCKET unset)"`, `"skipped (BACKUP_S3_ACCESS_KEY_ID unset)"`, `"skipped (BACKUP_S3_SECRET_ACCESS_KEY unset)"`, or `"failed (<short reason ≤200 chars>)"`. Two-step budget so a cold-pull of the rclone image does not consume the probe budget: a `timeout 60 docker pull -q rclone/rclone:1.66` step that runs only when `docker image inspect` reports the image absent (best-effort — a pull failure is intentionally not fatal), then a `timeout 6 docker run --rm -e RCLONE_CONFIG_OFFBOX_* rclone/rclone:1.66 lsd "offbox:<bucket>"` step (same 6 s wall-clock budget as `register_telegram_webhook`). Subsequent invocations skip the pull and only spend the 6 s. Best-effort — never fails the run on its own (mirrors `public_tls_probe` and `webhook_registration` semantics).
- A new top-level `offbox_backup_probe` field in `.installer-state.json` (written by `write_state_success` and re-emitted by `write_state_unregistered` so the field shape stays consistent across both writers — same discipline as the DEPLOY-1.5 `webhook_registration` block). `selected_defaults.backup_tool` flips from the D-063 reserved `null` to `"rclone"` in both writers — the slot pre-allocated by DEPLOY-1.4 / D-063 is now populated. The final `deploy.install.ok` log line is extended with `offbox_backup_probe="<status>"` after the existing `webhook_registration="..."` field.
- `INSTALLER_CONFIG_VERSION` bumps `2 → 3`. A new `migrate_v2_to_v3()` helper joins the chain after `migrate_v1_to_v2`; it is a no-op stamp (the new state-file shape — `selected_defaults.backup_tool="rclone"` plus the `offbox_backup_probe` field — is materialized by the next `write_state_success` call). This mirrors the D-064 `migrate_v1_to_v2` precedent — the seam is exercised by appending a named helper, not by rewriting the installer. Forward-version refusal continues to work — a hand-edited `installer_config_version: 99` is still refused with `deploy.upgrade.error ... v3 ...` before any `docker compose up`.
- Five new optional `.env.example` knobs in a new "Off-box backup sink (DEPLOY-1.6 / D-065)" section: `BACKUP_S3_BUCKET`, `BACKUP_S3_ENDPOINT`, `BACKUP_S3_PATH_PREFIX` (defaulted to `archive`), `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY`. None join `REQUIRED_ENV_KEYS` — off-box upload is operator-opt-in; unset `BACKUP_S3_*` yields a clear `skipped (…)` outcome in both the installer probe and the uploader log lines, without affecting preflight or `pg_backup.cycle.ok` semantics.

External-system behavior relied on (per `[[feedback_no_fabricated_external_requirements]]`): the `rclone` CLI documented at <https://rclone.org/docs/>, specifically `rclone sync` (idempotent — already-present files at the remote are skipped) and `rclone lsd` (list directories at a remote path), and the `S3` backend configured via the `RCLONE_CONFIG_<remote>_*` environment variables documented at <https://rclone.org/s3/>. Standard S3 GET/PUT/HEAD/LIST semantics. No provider-specific UX beyond the optional `BACKUP_S3_ENDPOINT` knob (set for R2 / B2 / Wasabi / MinIO; unset for AWS S3 itself).

**User-confirmed choices for this packet (per `[[feedback_separate_confirmed_from_proposed]]`):**
- **Backup tool pinned: `rclone`.** Pins the D-060 §3 second default from the candidate set `restic / custom scripts around rclone / pg_dump / pg_basebackup`. Syncs the existing OP-4 `/archive/base` + `/archive/wal` artifacts as bytes to any S3-compatible target, without duplicating the local `pg_basebackup` + WAL-archiving primitive. Single static binary; the official `rclone/rclone` image is small (~30 MB) and ships with the S3 backend built in. Confirmed in plan mode against the alternatives: `restic` would re-encrypt artifacts already produced by `pg_basebackup` (heavier surface, duplicated effort); `pg_dump` is logical-only and would not capture WAL (wrong primitive for PITR); a `pg_basebackup` wrapper is the existing local primitive and would still need a separate uploader.
- **Uploader placement: thin sidecar service.** A new `pg_offbox_uploader` service in `docker-compose.yml` (image `rclone/rclone:1.66`) under the existing `["backup"]` profile, polling `/archive/last_success.json`. Confirmed in plan mode against the inline-in-pg_backup alternatives (custom `Dockerfile.pg_backup` with `apt-get install rclone`; runtime install in scheduler.sh). The sidecar keeps `pg_backup`'s image, entrypoint, and scheduler.sh contract byte-equivalent (no change to OP-4.2's durable signal path), gives the uploader its own failure-isolation boundary, and reuses the official rclone image with no custom build.
- **Off-box sink stays operator opt-in (no new `REQUIRED_ENV_KEYS`).** Aligns with the user-approved scope ("unset BACKUP_S3_* must yield a clear `skipped (…)` outcome"). The DEPLOY-1 §2 invariant ("off-box backup destination required") is the closure signal for DEPLOY-1.7's clean-VPS pilot smoke, not the closure signal for DEPLOY-1.6 itself — DEPLOY-1.6 wires the seam; DEPLOY-1.7 verifies the operator filled it.

**Proposed defaults within the user-confirmed seam (revisable in later DEPLOY-1.x as long as DEPLOY-1 invariants hold):**
- Off-box installer probe is **active**: a one-shot `timeout 6 docker run --rm rclone/rclone:1.66 lsd offbox:<bucket>` against the operator-supplied remote, preceded by a separate `timeout 60 docker pull -q rclone/rclone:1.66` step that runs only when `docker image inspect` reports the image absent. Active mirrors `public_tls_probe`'s shape; passive (env-only) would not reach the `failed (…)` variant the validation expectations require.
- Probe budget: 6 s wall-clock for the actual `rclone lsd` call (matches `register_telegram_webhook`'s budget). The pull step uses its own 60 s budget and only fires when the image is not yet cached, so a cold install does not consume the probe budget and a hot install pays only the 6 s.
- Reason-string capture: first 200 characters of the rclone stderr blob on a `failed (...)` outcome, with newlines collapsed (same shape as `register_telegram_webhook`).
- Uploader poll cadence: `POLL_SECONDS=600` (10 min), matching `scheduler.sh`. The trigger is the cycle timestamp inside `/archive/last_success.json`; re-uploading is idempotent (`rclone sync` only transfers changed files).
- Uploader cursor file `/archive/last_offbox.json` (status, error class, base_backup, timestamp). The cursor is the operator-facing surface; the in-memory `LAST_UPLOADED_TS` is the trigger source so a missing cursor file (cold start) does not re-trigger an upload mid-cycle.
- Cursor failure categories: `auth_failed | network | remote_error | temporary | fatal`. Categorized from a small rclone-exit-code + stderr-keyword mapping; raw stderr is never echoed (no credential leakage).
- Uploader skipped-config log throttling: log once per state change, not once per poll, so a misconfigured uploader does not flood the journal.
- Rejected candidates documented for future revisits: `restic` (its own dedup/encryption engine — duplicates OP-4); `pg_dump` (logical-only — does not capture WAL); a `pg_basebackup` wrapper (already used locally — does not sync off-box on its own).

**Honest status outcome (per `[[feedback_truthful_reply_distinction]]`).** The off-box backup probe sits alongside `public_tls_probe` and `webhook_registration` as a third honest verdict in the installer's status surface; the four installer signals are reported separately, never coalesced. A failed or skipped `offbox_backup_probe` does NOT fail the install (`last_outcome="success"` still requires only the mandatory loopback `/health` to be `"ok"` — same as D-063 / D-064). The uploader's runtime signal is symmetric: a `pg_backup.offbox.error` log line and a `status=error` cursor never affect `/archive/last_success.json` or `pg_backup.cycle.ok` — additive observability per `[[feedback_additive_observability_best_effort]]`.

**A-43 deferred (logs-first observability scope).** A-43 (open since D-060) was conditional fold-in candidate for this packet. Deferred to a later DEPLOY-1.x packet because: (a) A-43 has multiple unpinned subdecisions (log format, structured-logging library, retention, scope, forward-seam tooling) that DEPLOY-1.6's off-box sink wiring does not need to resolve; (b) DEPLOY-1.x scope discipline (D-061..D-064 precedent) keeps each packet bounded to one subsystem; (c) the off-box sink reuses the existing ad-hoc structured-log convention already in `scripts/pg_backup/scheduler.sh` and `scripts/installer/deploy.sh` (`pg_backup.offbox.*` follows the `pg_backup.cycle.ok` shape) — no new logging contract is forced; (d) the configuration-versioning seam should cover one coherent concern per bump, and DEPLOY-1.6's `2 → 3` bump covers backup-tool default pinning. A-43 stays open and is pinned by a later DEPLOY-1.x packet — `docs/assumptions.md` and `docs/assumption-audit.md` are refined accordingly.

**Bounded inspection validation evidence (per `[[feedback_harness_is_inspection_not_gate]]`).** Split into packet-closing evidence (sufficient to close DEPLOY-1.6 on a dev host without a real VPS or a real S3 endpoint) and real-VPS operator smoke (RUNBOOK-only, NOT a closure gate; clean-VPS pilot smoke + the upgrade drill is DEPLOY-1.7's responsibility).

*Packet-closing inspection evidence (author/dev context, no real public DNS or real S3 endpoint required):*
1. `bash -n scripts/installer/deploy.sh` exits 0 — syntactic validity.
2. `sh -n scripts/pg_offbox_uploader/uploader.sh` exits 0 — syntactic validity.
3. `./scripts/installer/deploy.sh --version` prints `3` and exits 0.
4. `./scripts/installer/deploy.sh --help` prints usage including the DEPLOY-1.6 / D-065 off-box probe line and exits 0.
5. `./scripts/installer/deploy.sh --check` against a `.env` with the five DEPLOY-1.5 required keys filled and the five `BACKUP_S3_*` knobs **unset** still exits 0 (off-box sink is not in `REQUIRED_ENV_KEYS`); the `--check` line reflects `installer_config_version=3`.
6. Future-version refusal: with `.installer-state.json` hand-edited to `installer_config_version: 99`, the no-arg `./scripts/installer/deploy.sh` exits non-zero with `deploy.upgrade.error deployed config v99 is newer than this installer v3 ...`, does **not** invoke `docker compose up`, writes `.installer-state.last_failure.json`, and leaves `.installer-state.json` byte-equivalent to the hand-edited input.
7. Compose-profile parity: `docker compose --profile vps config --services | sort` returns `app app_init caddy pg_archive_init postgres` — byte-equivalent to DEPLOY-1.5; the `pg_offbox_uploader` service does **not** appear under the `vps` profile (the installer's bring-up).
8. Compose-profile inclusion: `docker compose --profile backup config --services | sort` returns `pg_archive_init pg_backup pg_offbox_uploader postgres` — adds exactly one new service to the `backup` profile.
9. Bare-`up` byte-equivalence: `docker compose config --services | sort` returns only `pg_archive_init postgres` — confirms DEPLOY-1.6 does not regress the DEPLOY-1.2..1.5 byte-equivalence property.
10. State-file shape: after a simulated successful install (e.g., on a dev host where the loopback probe succeeds), `.installer-state.json` records `"installer_config_version": 3`, `"selected_defaults.backup_tool": "rclone"`, and `"offbox_backup_probe": "<one of ok|failed (…)|skipped (BACKUP_S3_* unset)>"`. The previously-reserved `null` value for `backup_tool` is no longer emitted by either writer.

*Real-VPS operator smoke (RUNBOOK-only, NOT a packet-closing gate; clean-VPS pilot smoke + upgrade drill is DEPLOY-1.7's responsibility):*
- From a clean Debian / Ubuntu LTS VPS with the DEPLOY-1.5 pre-conditions plus the `BACKUP_S3_*` knobs filled against a reachable S3-compatible target: `./scripts/installer/deploy.sh` exits 0 with `deploy.install.ok ... offbox_backup_probe="ok"`; `--status` shows the v3 state file with `"selected_defaults.backup_tool": "rclone"` and `"offbox_backup_probe": "ok"`.
- `docker compose --profile backup up -d` starts both `pg_backup` and `pg_offbox_uploader`; after the next nightly cycle (or a manual `make backup-run`), `docker compose logs pg_offbox_uploader` shows the `pg_backup.offbox.begin … → pg_backup.offbox.ok` sequence; the remote bucket contains `<prefix>/base/base-<ts>/...` and `<prefix>/wal/...` artifacts; `/archive/last_offbox.json` records `status=ok` with the same `timestamp` and `base_backup` as `/archive/last_success.json`.
- Sink-failure additivity smoke: stopping the S3 endpoint mid-upload (or rotating in a bogus credential) yields `pg_backup.offbox.error stage=<base|wal> reason=<class> rc=<n>`; `/archive/last_success.json` is **untouched** (unchanged mtime); `pg_backup.cycle.ok` is still the most recent cycle outcome in `docker compose logs pg_backup`; `/archive/last_offbox.json` records `status=error` with a categorized reason — no credential text appears in the log.
- The v2 → v3 cross-version migration end-to-end against a real previously-installed v2 VPS is DEPLOY-1.7's responsibility — recorded honestly per `[[feedback_harness_is_inspection_not_gate]]`.

### Why
DEPLOY-1.5 left the installer one observability surface short of the DEPLOY-1 §2 invariant ("off-box backup destination required") being verifiable from the operator-facing canonical command. DEPLOY-1.6 is the canonical dependency-ordered next step because DEPLOY-1.7's clean-VPS smoke + upgrade drill needs to terminate against an off-box-sink-verified install. The reused OP-4.2 primitives mean there is no `src/`, schema, or migration surface to land here — only operator-side wiring + the `selected_defaults.backup_tool` slot D-063 reserved (`[[feedback_packet_scope_discipline]]`). Going via a sidecar polling the durable OP-4.2 signal — rather than inlining a hook in `scheduler.sh` — keeps the `pg_backup.cycle.ok` path byte-equivalent and lets the off-box failure path be observably independent of the local-cycle failure path. Bumping `INSTALLER_CONFIG_VERSION` to 3 and appending `migrate_v2_to_v3` exercises the D-063 configuration-versioning seam exactly as DEPLOY-1.5 did — append-only, named helper, no installer rewrite. The `rclone` choice over `restic` / `pg_dump` / `pg_basebackup`-wrapper is the smallest moving-part default that wires the existing OP-4 artifacts off-box without duplicating the local primitive (`[[feedback_baseline_vs_quality_packets]]` — wiring the baseline; encryption / dedup / cross-region replication are revisable quality concerns).

### Consequence
- Changed: `scripts/installer/deploy.sh` — `INSTALLER_CONFIG_VERSION` bumped `2 → 3`; new `migrate_v2_to_v3` no-op stamp + `run_migrations` chain extended; new `probe_offbox_backup` helper modeled on `probe_public_tls` (active probe via `docker run rclone/rclone:1.66 lsd` with a 15 s `timeout` budget); `write_state_success` signature extended with the `offbox` argument and JSON body extended with the `offbox_backup_probe` field; `write_state_unregistered` extended with `offbox_backup_probe` preservation (read via `read_state_string`, defaults to `"unknown"`); `selected_defaults.backup_tool` flipped from `null` to `"rclone"` in both writers; `cmd_install` calls `probe_offbox_backup` after `register_telegram_webhook` and passes the result through to `write_state_success`; final `deploy.install.ok` log line extended with `offbox_backup_probe="…"`; usage text updated.
- New: `scripts/pg_offbox_uploader/uploader.sh` (`#!/bin/sh`, `set -u`) — long-running poll loop that polls `/archive/last_success.json` and `rclone sync`s `/archive/base` + `/archive/wal` to `${REMOTE}:${BACKUP_S3_BUCKET}/${PREFIX}/{base,wal}` on a previously-unseen cycle, writes the outcome to `/archive/last_offbox.json`, and emits `pg_backup.offbox.{start,skipped,begin,ok,error}` log lines. Narrow write scope: never writes to `/archive/base`, `/archive/wal`, or `/archive/last_success.json` — only `/archive/last_offbox.json`.
- Changed: `docker-compose.yml` — new `pg_offbox_uploader` service (image `rclone/rclone:1.66`, `profiles: ["backup"]`, `restart: unless-stopped`, `depends_on: pg_backup`, env `BACKUP_S3_*`, volumes `memory_rag_pg_archive:/archive` + the script mount). Existing `pg_backup`, `pg_restore`, `postgres`, `pg_archive_init`, `app`, `app_init`, `caddy` blocks are unchanged. `--profile vps config --services` is byte-equivalent to DEPLOY-1.5.
- Changed: `.env.example` — new "Off-box backup sink (DEPLOY-1.6 / D-065)" section between the existing "Backup automation (OP-4.2 / D-054)" and "Restore drill (OP-4.3 / D-055)" sections, with five `BACKUP_S3_*` knobs marked optional and the default `BACKUP_S3_PATH_PREFIX=archive`.
- Changed: `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` — "Purpose & status" updated to reflect DEPLOY-1.6 landed (D-065); §3 "Backup tool" default pinned to **rclone** with the rejected candidates footnoted (mirrors D-062's Caddy precedent); §3 "Default-stability mitigation" paragraph updated to record `INSTALLER_CONFIG_VERSION=3` and the second non-trivial chain extension (`migrate_v2_to_v3`); §4 packet-sequence table — DEPLOY-1.6 row status set to "Landed (D-065)". Invariants and reverse-proxy / installer-language defaults unchanged.
- Changed: `docs/execution-map.md` — DEPLOY-1.6 row replaced with a landed-shape pointer at the new `pg_offbox_uploader` service + `scripts/pg_offbox_uploader/uploader.sh` + the `probe_offbox_backup` helper + the `offbox_backup_probe` state-file field + the `BACKUP_S3_*` env knobs + the v2 → v3 bump + the new RUNBOOK subsection.
- Changed: `docs/todo.md` — DEPLOY-1.6 marked done (D-065); **DEPLOY-1.7 is the sole canonical "next"**.
- Changed: `docs/RUNBOOK.md` — new "Off-box backup sink (DEPLOY-1.6 / D-065)" subsection inside the existing "Self-hosted VPS reference shape (DEPLOY-1 / D-060)" section, immediately after the DEPLOY-1.5 subsection. Contents: the five new optional `BACKUP_S3_*` env keys; how the off-box upload lifecycle interacts with the OP-4.2 nightly cycle (poll the OP-4.2 durable signal; mirror artifacts; never affect `pg_backup.cycle.ok`); how to inspect `/archive/last_offbox.json`; how to read `pg_backup.offbox.*` log lines via `docker compose logs pg_offbox_uploader`; what the four `offbox_backup_probe` variants mean in `.installer-state.json` (`ok`, `skipped (…)`, `failed (…)`); what an operator does when the sink probe says `failed (…)`; the explicit statement that a sink failure does NOT degrade `pg_backup.cycle.ok` semantics or the OP-4.2 durable signal. The existing DEPLOY-1.4 packet-closing inspection block is amended so its expected `--version` / `--check` output reflects v3.
- Changed: `docs/assumptions.md` — A-43 entry refined to record DEPLOY-1.6 did **not** fold it in (no new logging contract was forced by off-box sink wiring; the off-box log lines reuse the existing `pg_backup.*` shape). A-43 stays **open** and is pinned by a later DEPLOY-1.x packet (not DEPLOY-1.6).
- Changed: `docs/assumption-audit.md` — A-43 row "Due by" cell refined to match the assumptions.md wording (later DEPLOY-1.x packet, not DEPLOY-1.6).
- **No `src/` change**, no schema change, no migration change, no `pyproject.toml` / `uv.lock` change, no `Makefile` change, no `Dockerfile` / `.dockerignore` change, no `configs/caddy/Caddyfile` change, no `tests/` change, no `.gitignore` change.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` deliberately **not** touched — I-15 ("raw durability and export") is already broad enough; no new invariant is enforced by DEPLOY-1.6's wiring and adding one would over-claim relative to what the code enforces (`[[feedback_invariants_match_enforcement]]`). The DEPLOY-1 §2 invariant ("off-box backup destination required") remains a deployment-shape expectation carried by D-060 + the roadmap doc until DEPLOY-1.7 verifies it end-to-end.
- `docs/ARCHITECTURE.md`, `docs/product/{PRD,BuildPlan,TechSpec}.md`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `QUICKSTART.md`, `docs/GLOSSARY.md` — also not touched. A-42 stays closed by D-060; A-43 stays open (refined in scope per above); A-41 stays deferred until DEPLOY-2.
- **DEPLOY-1.6 is complete; DEPLOY-1.7 is the sole canonical next packet; DEPLOY-1 exits once DEPLOY-1.7 lands.**
- Out of scope (deferred to DEPLOY-1.7 or DEPLOY-2): the clean-VPS → working-pilot end-to-end smoke + upgrade drill (DEPLOY-1.7) including the real off-box-backup verification, the cross-version v2 → v3 migration smoke, and the operator-facing closure of the §2 off-box-backup invariant; A-43 logs-first observability seam (deferred to a later DEPLOY-1.x packet); managed-cloud reference deployment (DEPLOY-2 reopens A-41); any `src/`, schema, migration, retrieval, answer-path, or domain-logic change; any change to `pg_backup` (image, entrypoint, env, scheduler.sh, backup.sh, prune.sh) — the OP-4.2 path is reused unchanged; encryption-at-rest for the off-box sink (rclone's `--crypt` remote is a revisable quality concern); cross-region replication or lifecycle rules at the bucket (provider-side operator concern); auto-rotation of `BACKUP_S3_*` credentials (the installer reads `.env` and does not write it, per D-063); a `--reset-offbox-cursor` subcommand or other cursor manipulation (operator can `docker compose exec pg_offbox_uploader rm /archive/last_offbox.json` if needed); a provider-specific runbook section (operator's secret-management UX); any `make deploy-*` / `make offbox-*` convenience target (per the DEPLOY-1.2..1.5 precedent of deferring convenience targets); any interactive UX variant; any unrelated cleanup or refactor.

## D-066 — DEPLOY-1.7-preflight: local-only upgrade-drill harness across real prior commits

### Decision
DEPLOY-1.7-preflight adds a local-only upgrade-drill harness at `scripts/installer/drill_upgrade_local.sh` that exercises the D-063 configuration-versioning seam (`INSTALLER_CONFIG_VERSION` + the `migrate_v<old>_to_v<new>` chain) against **real prior packet commits** via a sandboxed git worktree under `mktemp -d`. Operates within DEPLOY-1 invariants — A-22 updated by D-060. The packet de-risks the seam locally; it does **not** close DEPLOY-1.7 and it does **not** close DEPLOY-1. DEPLOY-1.7 remains the sole canonical closure packet for DEPLOY-1.

- The harness runs three legs in order: leg 1 via commit `7cb96fa` (DEPLOY-1.4, `INSTALLER_CONFIG_VERSION=1`, exercises `migrate_to_v1`); leg 2 via commit `e435e1a` (DEPLOY-1.5, `INSTALLER_CONFIG_VERSION=2`, exercises `migrate_v1_to_v2`); leg 3 via commit `0aef179` (DEPLOY-1.6, `INSTALLER_CONFIG_VERSION=3`, exercises `migrate_v2_to_v3`). For each leg, the harness `git checkout`s the commit **inside the worktree**, regenerates a benign `.env` (deliberately non-resolvable `PUBLIC_HOSTNAME=*.invalid`, placeholder Telegram credentials, unset `BACKUP_S3_*`), invokes the worktree-local `./scripts/installer/deploy.sh`, snapshots the resulting `.installer-state.json` verbatim, and records the leg's exit code, the final `deploy.install.ok` line, and the elapsed wall-clock. Docker compose state is pinned across legs via `COMPOSE_PROJECT_NAME=deploy1-preflight-drill` so named volumes survive across legs (the v1 → v2 → v3 chain advances against persisted runtime state) while staying isolated from any operator compose project running against the main repo with the default project name. Compose teardown between legs is intentionally skipped — the next leg's `docker compose --profile vps up -d --build` exercises the realistic "upgrade an already-running install" operator path. A final `docker compose --profile vps down` (no `-v`) leaves the project's volumes intact for operator post-mortem.
- The harness writes the evidence artifact at `docs/deploy1-drill/deploy1-upgrade-drill-<YYYYMMDD>-evidence.json` (UTC-dated; parallel to the OP-4.3 `docs/op4-drill/op4.3-<YYYYMMDD>-evidence.json` precedent). The artifact records, per leg: `commit_sha`, `packet_label`, `expected_installer_config_version`, `exit_code`, `elapsed_seconds`, the verbatim `deploy_install_ok_line`, the verbatim `state_file_after` JSON object (or `null` if absent), the verbatim `last_failure_after` JSON object (or `null`), and an `observed_probes` dict capturing the verbatim `public_tls_probe` / `webhook_registration` / `offbox_backup_probe` / `selected_defaults.backup_tool` values present at that leg (`null` where the field shape did not yet exist — the v1 state file does not carry `webhook_registration` or `offbox_backup_probe`, the v2 state file does not carry `offbox_backup_probe`). Top-level keys `locally_confirmed_signals`, `locally_skipped_signals`, `out_of_scope_for_closure`, and `summary` classify the observations: probe verdicts are classified as `operator_dependent`, the chain-advance and shape-transitions are classified as locally confirmed; the summary always carries `closes_deploy_1_7: false`, `deploy_1_7_status: "still open"`, `deploy_1_status: "still open"`.
- The harness only asserts on two **stable, code-guaranteed** properties: per-leg `exit_code == 0` and per-leg `state_file_after.installer_config_version` matching the expected integer in the table above (the integer is a tracked literal in each commit's `scripts/installer/deploy.sh`). It does **not** hardcode expected values for `public_tls_probe`, `webhook_registration`, or `offbox_backup_probe`. Those probe verdicts are captured verbatim and classified — never asserted-on (per `[[feedback_harness_is_inspection_not_gate]]` and per the user's narrow plan-review correction that exact skipped-string values must not be pre-asserted unless guaranteed by existing code).
- The harness operates entirely in a throwaway worktree; the main repo working tree is never modified by the drill. On success, an `EXIT trap` removes the worktree + tempdir. On failure or interrupt, the trap leaves them in place and prints the absolute path so the operator can inspect, then run `git worktree remove --force <path>` manually. The harness does **not** require the main repo working tree to be clean and does **not** require `.installer-state.json` to be absent from the main repo — its operating set is the worktree, not the main repo. Docker volumes (under the pinned project name) survive the harness; the operator can clean them with `docker compose --project-name deploy1-preflight-drill --profile vps down -v` separately, without touching any other compose project's state.

**User-confirmed choices for this packet (per `[[feedback_separate_confirmed_from_proposed]]`):**
- **Local-only preflight, not closure.** DEPLOY-1.7 remains the canonical closure packet; DEPLOY-1 remains open.
- **Real prior commits (`7cb96fa` / `e435e1a` / `0aef179`), not hand-edited state files.** Per `[[feedback_real_prior_version_evidence]]`: hand-edited state files on an already-upgraded host are not closure evidence; the harness exercises the real prior-version installer + runtime contour by `git checkout`ing the actual prior packet commits.
- **Sandboxed git worktree under `mktemp -d`, not in-place checkout.** Forced by two facts: the harness script is added in this packet at HEAD and does not exist at the prior commits (an in-place `git checkout` of `7cb96fa` would erase the running script), and the main repo working tree must stay clean and reviewable before the packet's checkpoint.
- **No `scripts/installer/deploy.sh` change.** The harness runs the unchanged installer per leg.
- **Evidence artifact path** `docs/deploy1-drill/deploy1-upgrade-drill-<YYYYMMDD>-evidence.json` (parallel to `docs/op4-drill/op4.3-<YYYYMMDD>-evidence.json`).
- **Probe verdicts captured verbatim, only `exit_code` and `installer_config_version` asserted.** The narrow plan-review correction: exact skipped-string values for `public_tls_probe` / `webhook_registration` / `offbox_backup_probe` are not hardcoded; the harness captures them as observed and classifies them as `operator_dependent`.

**Proposed defaults within the user-confirmed seam (revisable in later DEPLOY-1.x as long as DEPLOY-1 invariants hold):**
- Three-leg sequence (v0→v1 / v1→v2 / v2→v3) — the smallest sufficient exercise of the chain; v0→v1 is the natural entry because it exercises the no-op `migrate_to_v1` stamp on a fresh "deployed=0" entry.
- `.env` is regenerated from scratch at each leg (POSTGRES_PASSWORD + PUBLIC_HOSTNAME + ACME_EMAIL + TELEGRAM_BOT_TOKEN + TELEGRAM_WEBHOOK_SECRET, all with benign values; `BACKUP_S3_*` left unset). The union is forward-compatible across all three legs — v1's deploy.sh ignores Telegram keys; v2/v3 read them but the webhook path's outcome depends on the public-TLS probe; v3 reads `BACKUP_S3_*` but the off-box probe outcome depends on whether the operator filled them.
- `PUBLIC_HOSTNAME=deploy1-preflight.invalid` uses an RFC 6761 reserved-TLD value to deliberately induce a non-`ok` `public_tls_probe`; the exact verdict string is captured verbatim and classified.
- `COMPOSE_PROJECT_NAME=deploy1-preflight-drill` pinned across legs (volumes survive across legs; isolated from operator compose state).
- No `docker compose down` between legs (real "upgrade an already-running install" path).
- Final `docker compose --profile vps down` (no `-v`) — volumes kept for operator post-mortem.
- On success, automatic cleanup of worktree + tempdir; on failure, leave both in place and print paths.

**External-system behavior relied on (per `[[feedback_no_fabricated_external_requirements]]`):** `git worktree add --detach <path> HEAD` per <https://git-scm.com/docs/git-worktree>; `mktemp -d -t <template>` per POSIX; `docker compose v2` semantics already in use by `scripts/installer/deploy.sh`. The RFC 6761 `.invalid` TLD is reserved for examples and guaranteed non-resolvable on a correctly-behaving DNS resolver — used here to induce, not assert, the public-TLS probe's skipped outcome.

**Bounded inspection validation evidence (per `[[feedback_harness_is_inspection_not_gate]]`).** Split into packet-closing evidence (sufficient to close DEPLOY-1.7-preflight on a dev host) and operator-dependent signals captured verbatim but not asserted-on.

*Packet-closing inspection evidence (dev host with Docker + Compose v2; no real VPS / public DNS / Telegram / S3 required):*
1. `bash -n scripts/installer/drill_upgrade_local.sh` exits 0 — syntactic validity.
2. `scripts/installer/drill_upgrade_local.sh` is executable.
3. `./scripts/installer/drill_upgrade_local.sh` runs to completion locally with overall stdout `deploy1.preflight.ok seam_exercised_locally=true closes_deploy_1_7=false`, exercising three legs across commits `7cb96fa` / `e435e1a` / `0aef179` in a worktree under `mktemp -d`.
4. The committed `docs/deploy1-drill/deploy1-upgrade-drill-<YYYYMMDD>-evidence.json` records all three legs at `exit_code: 0` and observed `state_file_after.installer_config_version` matching `1` / `2` / `3` respectively; `summary.verdict` is `"preflight ok"`; `summary.closes_deploy_1_7` is `false`; `summary.deploy_1_status` is `"still open"`.
5. The verbatim `state_file_after` snapshots in `legs[].state_file_after` show the per-version shape transitions: v1's state file does not carry `webhook_registration` or `offbox_backup_probe`; v2's carries `webhook_registration` but not `offbox_backup_probe`; v3's carries both `offbox_backup_probe` and the `selected_defaults.backup_tool="rclone"` flip from `null`. These are recorded as observations, not as pre-asserted strings.
6. The main repo working tree is clean after the run — `git status` shows exactly the new script, the new evidence artifact, and the docs changes; no `.installer-state.json`, no `.env`, no leftover paths inside the main repo.
7. Cross-reference consistency pass (per `[[feedback_docs_packet_consistency]]` and `[[feedback_closure_verdict_aggregation]]`): the decision-log entry (D-066), `RUNBOOK.md` subsection ("Local-only upgrade-drill preflight (DEPLOY-1.7-preflight / D-066)"), `SELF-HOSTED-DEPLOYMENT-ROADMAP.md` (§1 status + §4 packet-sequence table + §5 dependency DAG), `execution-map.md` (new DEPLOY-1.7-preflight row), and `todo.md` entry all agree on "preflight landed (D-066); DEPLOY-1.7 still open; DEPLOY-1 still open."

*Operator-dependent signals (captured verbatim in `observed_probes`; classified as `operator_dependent`; NOT asserted-on by the harness — DEPLOY-1.7's responsibility to confirm against real public DNS / Telegram / S3):*
- `public_tls_probe` per leg (v2 and v3 — v1's state file does not carry this field; the v3.1 commit's deploy.sh reads `PUBLIC_HOSTNAME` from `.env` and emits a non-`ok` outcome whose exact verbatim string is recorded by the harness; the harness does not pre-assert the string).
- `webhook_registration` per leg (block exists at v2 / v3; its `status` field depends on the upstream `public_tls_probe` outcome; verbatim block captured).
- `offbox_backup_probe` per leg (field exists at v3 only; the outcome depends on whether the operator filled `BACKUP_S3_*`; verbatim captured).

### Why
DEPLOY-1.7 closure remains blocked on real-VPS / public-DNS / Telegram / real-S3 operator infrastructure that does not exist in the current development environment. While that infrastructure is unavailable, the D-063 configuration-versioning seam has only been exercised on synthetic state (the future-version refusal branch, via a hand-edited `installer_config_version: 99`). The upgrade chain itself — `migrate_to_v1` → `migrate_v1_to_v2` → `migrate_v2_to_v3` — has never been advanced end-to-end against real prior-version installer + runtime state. A regression in `migrate_v1_to_v2` or `migrate_v2_to_v3` would currently first be observable on a real VPS — too late.

`[[feedback_real_prior_version_evidence]]` explicitly forbids hand-edited state files as upgrade-drill closure evidence: "Real prior-version state includes the full installer + runtime contour (env, Docker state, sidecar profiles, archive volume layout) that existed at the prior version, not just the state-file fields." This packet implements the procedure that memory describes: `git checkout <prior-packet-commit-sha>`, run the prior installer end-to-end, capture exit code + state file + log line, then advance to the next commit.

The sandboxed-worktree-not-in-place design is forced by two facts together: the harness script is added in this packet at HEAD (so an in-place `git checkout` of a prior commit would erase the running script under itself), and the main repo working tree must remain clean and reviewable for the packet's checkpoint. The throwaway worktree under `mktemp -d` gives both. `COMPOSE_PROJECT_NAME` pinning gives volume continuity across legs without leaking into operator compose state.

Cites `[[feedback_packet_scope_discipline]]` (the packet's framing is narrow — preflight, not closure; only the seam, not the operator surfaces), `[[feedback_closure_verdict_aggregation]]` (the verdict "preflight ok" never promotes to DEPLOY-1.7 closure or DEPLOY-1 closure), `[[feedback_real_prior_version_evidence]]` (real prior commits, not synthetic state), `[[feedback_harness_is_inspection_not_gate]]` (the harness is inspection — only the two stable code-guaranteed properties are asserted; everything else is recorded verbatim), and `[[feedback_separate_confirmed_from_proposed]]` (user-confirmed choices labeled separately from proposed defaults).

### Consequence
- **New:** `scripts/installer/drill_upgrade_local.sh` — local-only upgrade-drill harness; sandboxed git worktree under `mktemp -d`; pins `COMPOSE_PROJECT_NAME=deploy1-preflight-drill`; runs three legs across commits `7cb96fa` / `e435e1a` / `0aef179`; assembles the evidence JSON via an embedded `python3` step that reads the per-leg captures (`leg-<n>-meta.json` + `leg-<n>-state.json` + `leg-<n>-last-failure.json` + `leg-<n>-install-ok.txt`) inside the worktree and writes the artifact to `docs/deploy1-drill/`; EXIT trap removes the worktree + tempdir on success / preserves them on failure.
- **New:** `docs/deploy1-drill/deploy1-upgrade-drill-<YYYYMMDD>-evidence.json` — committed evidence artifact from the one local run; UTC-dated; verbatim `state_file_after` per leg + `observed_probes` per leg + classified `locally_confirmed_signals` / `locally_skipped_signals` / `out_of_scope_for_closure` / `summary` with `closes_deploy_1_7: false` and `deploy_1_7_status: "still open"`.
- **Changed:** `docs/RUNBOOK.md` — new "Local-only upgrade-drill preflight (DEPLOY-1.7-preflight / D-066)" subsection inside the existing "Self-hosted VPS reference shape (DEPLOY-1 / D-060)" section, immediately after the DEPLOY-1.6 subsection. Names operator pre-conditions, how to run, what the harness confirms locally (chain advance + shape transitions), what it does not confirm (operator-dependent probes captured verbatim under `observed_probes`), the cleanup model, and the closing statement that DEPLOY-1.7 remains the closure packet.
- **Changed:** `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` — §1 Purpose & status: appended sentence naming DEPLOY-1.7-preflight landed (D-066), DEPLOY-1.7 not started, DEPLOY-1 open; §4 packet-sequence table: new row above the existing DEPLOY-1.7 row; §5 dependency DAG: DEPLOY-1.7-preflight inserted between DEPLOY-1.6 and DEPLOY-1.7. Invariants (§2), current defaults (§3), and exit criterion (§6) unchanged.
- **Changed:** `docs/execution-map.md` — new DEPLOY-1.7-preflight row above the existing DEPLOY-1.7 row; existing DEPLOY-1.7 row left at "TBD when planned" (no scope reduction).
- **Changed:** `docs/todo.md` — new "DEPLOY-1.7-preflight — local-only upgrade-drill harness: done (D-066)" entry above the existing DEPLOY-1.7 entry; DEPLOY-1.7 entry stays as "sole canonical next" for closure.
- **No `src/` change**, no schema change, no migration change, no `tests/` change, no `pyproject.toml` / `uv.lock` change, no `Makefile` change, no `Dockerfile` / `.dockerignore` change, no `docker-compose.yml` change, no `.env.example` change, no `.gitignore` change, no `configs/caddy/Caddyfile` change, no change to `scripts/installer/deploy.sh`, `scripts/pg_offbox_uploader/`, `scripts/pg_backup/`, or `scripts/pg_restore/`.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` deliberately **not** touched — a preflight harness enforces no new runtime or data-shape invariant; adding one would over-claim relative to what the code enforces (per `[[feedback_invariants_match_enforcement]]`).
- `docs/assumptions.md` / `docs/assumption-audit.md` deliberately **not** touched — A-43 (logs-first observability scope) stays open and pinned to a later DEPLOY-1.x packet; no new assumption is opened by the preflight (per `[[feedback_contract_decisions_in_decision_log]]` — packet-level scoping choices belong in the decision-log + roadmap, not as open assumptions).
- `docs/ARCHITECTURE.md`, `docs/product/{PRD,BuildPlan,TechSpec}.md`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `QUICKSTART.md`, `docs/GLOSSARY.md` — also not touched.
- **DEPLOY-1.7-preflight is complete; DEPLOY-1.7 stays the sole canonical closure next; DEPLOY-1 stays open.**
- Out of scope (per packet boundaries): any change to `scripts/installer/deploy.sh`; any change to `scripts/pg_offbox_uploader/`, `scripts/pg_backup/`, `scripts/pg_restore/`, `docker-compose.yml`, or runtime service definitions; real-VPS pilot smoke; public DNS / TLS; real Telegram webhook checks; real S3 / off-box upload checks; any claim of DEPLOY-1 closure; any `INSTALLER_CONFIG_VERSION` bump or default revision; A-43 observability work; any `src/`, schema, migration, or test-suite behavioral change; quarterly / scheduled re-runs of the preflight (single-run artifact for this packet); any `make deploy-drill-*` convenience target (per the DEPLOY-1.2..1.6 precedent of deferring convenience targets); hardening probe-verdict assertions into closure gates (DEPLOY-1.7's responsibility).

---

## D-067 — DEPLOY-1.7a: clean-VPS pilot smoke + off-box backup §2-invariant verification (split of DEPLOY-1.7)

### Decision
Split DEPLOY-1.7 into **DEPLOY-1.7a** (clean-VPS pilot smoke + off-box backup §2-invariant verification — landed) and **DEPLOY-1.7b** (v2 → v3 cross-version upgrade drill on a real previously-installed v2 VPS — sole canonical remaining closure packet for DEPLOY-1). Operates within DEPLOY-1 invariants — A-22 updated by D-060. `SELF-HOSTED-DEPLOYMENT-ROADMAP.md` §4 explicitly permits the split: *"Names, exact granularity, and ordering between independent packets are refinable when each packet is planned — they may be merged or split as long as every resulting packet preserves the invariants in §2"*; both halves preserve the §2 invariants — DEPLOY-1.7a in fact verifies the §2 "off-box backup destination required" invariant against a real S3-compatible target; DEPLOY-1.7b will verify the §2 "operator-facing idempotent install/upgrade script" invariant across version boundaries. The DEPLOY-1.7-preflight (D-066) precedent is structurally the same shape: a narrowly-scoped follow-up sibling that de-risks a specific seam without claiming overall closure.

DEPLOY-1.7a lands via:

- The committed evidence artifact at `docs/deploy1-drill/deploy1-pilot-smoke-20260527-evidence.json` (UTC-dated; parallel to `docs/deploy1-drill/deploy1-upgrade-drill-20260522-evidence.json` from D-066), capturing verbatim from the live VPS: the installer's `.installer-state.json` fields (`installer_config_version`, `selected_defaults`, `last_install_timestamp`, `last_outcome`, `loopback_health`, `public_tls_probe`, `offbox_backup_probe`, and the `webhook_registration{status, url, attempted_at}` block); the observed `https://$PUBLIC_HOSTNAME/health` body (`{status, version, env}`); the `https://$PUBLIC_HOSTNAME/telegram/webhook` round-trip — the in-app log line of the canonical `telegram.webhook update_id=<id> route=start route_source=command confidence=n/a edit_seq=<int> lifecycle=<lifecycle> effective_path=<path>` shape, the matching access log `POST /telegram/webhook 200`, and the observed `/start` wall-clock latency (~2–3 s); an explicit `getUpdates=409` note framed as **expected with webhook active** (not a defect — Telegram documents `setWebhook` and `getUpdates` as mutually exclusive, with `getUpdates` returning HTTP 409 `Conflict: can't use getUpdates method while there is an active webhook` while a webhook is registered); the off-box happy-path leg with `BACKUP_S3_*` filled against a reachable bucket — the `pg_backup.offbox.begin base=<base_id> ts=<UTC ISO>` → `pg_backup.offbox.ok base=<base_id>` log-line pair, the `/archive/last_offbox.json` cursor with `status=ok` and `timestamp` matching `/archive/last_success.json`, and a remote-listing summary showing `<prefix>/base/...` + `<prefix>/wal/...` populated (object counts only); and the additivity smoke per RUNBOOK §"Off-box backup sink (DEPLOY-1.6 / D-065)" — force an upload failure (stop endpoint / revoke credentials / break network), capture the `/archive/last_offbox.json` transition to `status=error`, confirm `/archive/last_success.json` is unchanged, and confirm `pg_backup.cycle.ok` is still emitted.
- The new `docs/RUNBOOK.md` "Clean-VPS pilot smoke (DEPLOY-1.7a / D-067)" subsection inside the existing "Self-hosted VPS reference shape (DEPLOY-1 / D-060)" section, immediately after the DEPLOY-1.7-preflight subsection. Names operator pre-conditions (clean Debian / Ubuntu LTS VPS reachable on its public hostname; `.env` populated with `PUBLIC_HOSTNAME`, `ACME_EMAIL`, Telegram bot token + webhook secret, and all five `BACKUP_S3_*` knobs); the run procedure (install → `/health` capture → `/start` round-trip + log capture → `getUpdates=409` note → one off-box cycle + remote listing → additivity smoke); the evidence-file shape (two top-level branches `pilot_smoke` and `offbox_backup_verification`, plus `out_of_scope_for_this_packet` and a `summary`); and the explicit redaction rule with a pre-commit grep check.

**Credential text** (bucket name, endpoint URL, prefix, access key, secret, public hostname, webhook URL token) **must not appear in the captured evidence file**. Structural outcomes (status strings, log-line shapes, `"ok"` / `"error"` transitions, the additivity-smoke booleans) are captured verbatim; credential-bearing values are replaced by `<REDACTED>` or a `_redacted: true` flag. Pre-commit, grep the evidence artifact for the literal `$PUBLIC_HOSTNAME`, `$BACKUP_S3_BUCKET`, `$BACKUP_S3_ENDPOINT`, `$BACKUP_S3_PATH_PREFIX`, `$BACKUP_S3_ACCESS_KEY_ID`, `$BACKUP_S3_SECRET_ACCESS_KEY`, and `$TELEGRAM_BOT_TOKEN` values and confirm none appear literally.

### Why
Live VPS evidence already covered the pilot smoke and the off-box §2-invariant verification: the Telegram webhook round-trip is green, `POST /telegram/webhook` returns 200, `/start` round-trip latency is ~2–3 s, the public DNS + HTTPS contour is up, and the off-box leg can be exercised against a real S3-compatible bucket with the existing `BACKUP_S3_*` knobs. The v2 → v3 cross-version upgrade drill is genuinely operator-dependent — it needs a separate v2-installed VPS that does not yet exist. Packaging the three components together would stall closure of the parts already in hand on infrastructure the development environment cannot produce.

Splitting closes the pilot smoke + off-box halves now (DEPLOY-1.7a / D-067) and isolates the cross-version drill into a single bounded follow-up packet (DEPLOY-1.7b). `SELF-HOSTED-DEPLOYMENT-ROADMAP.md` §4 is explicit that packet names / granularity / ordering between independent packets is refinable at planning time, provided every resulting packet preserves the §2 invariants — both halves do. The DEPLOY-1.7-preflight (D-066) precedent is the same shape: a narrowly-scoped follow-up sibling that closes one seam without claiming overall closure.

### Consequence
- **New:** `docs/deploy1-drill/deploy1-pilot-smoke-20260527-evidence.json` — committed pilot-smoke evidence artifact; verbatim installer state-file fields, `/health` body, `/start` round-trip + log line + observed latency, `getUpdates=409` framing, off-box happy path + additivity smoke; credential-bearing values redacted (`<REDACTED>` / `_redacted: true`). Shape parallels `docs/deploy1-drill/deploy1-upgrade-drill-20260522-evidence.json`.
- **Changed:** `docs/RUNBOOK.md` — new "Clean-VPS pilot smoke (DEPLOY-1.7a / D-067)" subsection inside the existing "Self-hosted VPS reference shape (DEPLOY-1 / D-060)" section, placed immediately after the DEPLOY-1.7-preflight subsection. Names operator pre-conditions, run procedure, evidence-file shape, the explicit redaction rule, and the `getUpdates=409` framing.
- **Changed:** `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` — §1 status paragraph appended with the 1.7a / 1.7b split sentence; §4 packet-sequence table: DEPLOY-1.7 row split into 1.7a (landed) + 1.7b (sole canonical next for closure); §5 DAG line and the closure-bullet updated to reference both halves; §6 exit criterion updated to reference both halves.
- **Changed:** `docs/execution-map.md` — Deployment-shape row split into 1.7a (landed) + 1.7b (TBD when planned).
- **Changed:** `docs/todo.md` — DEPLOY-1.7 entry split into 1.7a (done) + 1.7b (sole canonical next for closure).
- **No `src/` change**, no schema change, no migration change, no `tests/` change, no `pyproject.toml` / `uv.lock` change, no `Makefile` change, no `Dockerfile` / `.dockerignore` change, no `docker-compose.yml` change, no `.env.example` change, no `.gitignore` change, no `configs/caddy/Caddyfile` change, no change to `scripts/installer/deploy.sh`, `scripts/installer/drill_upgrade_local.sh`, `scripts/pg_offbox_uploader/`, `scripts/pg_backup/`, or `scripts/pg_restore/`.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` deliberately **not** touched — DEPLOY-1.7a verifies (it does not add) an existing invariant.
- `docs/assumptions.md` / `docs/assumption-audit.md` deliberately **not** touched — A-42 (DEPLOY-1 invariants) is closed by D-060; A-43 (logs-first observability scope) stays open and pinned to a later DEPLOY-1.x packet; no new assumption is opened by this packet.
- `docs/ARCHITECTURE.md`, `docs/product/{PRD,BuildPlan,TechSpec}.md`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `QUICKSTART.md`, `docs/GLOSSARY.md` — also not touched.
- **DEPLOY-1.7a is complete; DEPLOY-1.7b stays the sole canonical closure next; DEPLOY-1 stays open.**

### Observations (deferred, not in scope for this packet)
Three Phase-4 UX polish items were surfaced during the live pilot smoke. Each is surface polish, not DEPLOY-1 scope; each is explicitly deferred to a separate post-DEPLOY-1 packet so it is not lost:

- **`/note` first-line ISO-date strictness.** The parser is stricter than operator expectation for the first-line date; the surface-level wording / parse behavior should be revisited.
- **`/ask` user-facing wording leaks implementation detail.** The user-facing reply surfaces a chunk UUID and the literal phrase "dense+sparse RRF"; both are internal vocabulary and should not appear in the user-facing reply.
- **No-memories-matched UX.** When retrieval returns zero matches, the user-facing reply needs a clearer / more helpful surface than the current shape.

### Out of scope (per packet boundaries)
- **DEPLOY-1.7b** — v2 → v3 cross-version upgrade drill against a real previously-installed v2 VPS. Sole canonical remaining closure packet for DEPLOY-1.
- Any `src/` change, schema, migration, retrieval, answer-path, or domain-logic change.
- The three Phase-4 UX polish items above (flagged as observations, not fixed here).
- Any change to `scripts/installer/deploy.sh`, `scripts/pg_offbox_uploader/uploader.sh`, `docker-compose.yml`, `Caddyfile`, or the `pg_backup` / `pg_restore` paths.
- A-43 logs-first observability scope work.
- Any `make` convenience target.
- Any pinning of new defaults.
- `docker compose down -v` of operator volumes.

---

## D-068 — DEPLOY-1.7b prep: operator procedure + evidence-file template for the v2 → v3 cross-version upgrade drill

### Decision
Land the **docs-first operator-procedure preparation** for DEPLOY-1.7b — the v2 → v3 cross-version upgrade drill against a real previously-installed v2 VPS — ahead of the operator drill itself. Operates within DEPLOY-1 invariants — A-22 updated by D-060. DEPLOY-1.7b remains the sole canonical remaining packet for DEPLOY-1 closure (per D-067 and `SELF-HOSTED-DEPLOYMENT-ROADMAP.md` §4 / §5 / §6); DEPLOY-1 remains open until the operator drill produces the populated dated evidence artifact.

D-068 mirrors the D-066 (preflight harness, local) → D-067 (pilot smoke, real-VPS evidence) precedent: a narrowly-scoped follow-up sibling that lands the bounded autonomous work now and isolates the operator-dependent closure step into a single subsequent action. `SELF-HOSTED-DEPLOYMENT-ROADMAP.md` §4 explicitly permits this kind of split: *"Names, exact granularity, and ordering between independent packets are refinable when each packet is planned — they may be merged or split as long as every resulting packet preserves the invariants in §2"*. D-068 preserves all five §2 invariants (it adds no runtime change; the §2 "operator-facing idempotent install/upgrade script" invariant is the one DEPLOY-1.7b will verify across version boundaries when the drill runs).

D-068 lands via:

- The new `docs/RUNBOOK.md` "v2 → v3 cross-version upgrade drill (DEPLOY-1.7b / D-068)" subsection at the same `###` level as its DEPLOY-1.4 / 1.5 / 1.6 / 1.7-preflight / 1.7a siblings, inside the existing "Self-hosted VPS reference shape (DEPLOY-1 / D-060)" section and immediately after the DEPLOY-1.7a / D-067 subsection. Names operator pre-conditions (a real previously-installed v2 VPS originally installed from commit `e435e1a` (DEPLOY-1.5, `INSTALLER_CONFIG_VERSION=2`); current branch checked out at DEPLOY-1.6+ / `INSTALLER_CONFIG_VERSION=3`; `.env` populated with the same env-key groups as DEPLOY-1.7a — `PUBLIC_HOSTNAME`, `ACME_EMAIL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, and all five `BACKUP_S3_*` knobs); the numbered run procedure (snapshot v2 `.installer-state.json` → `git checkout` current DEPLOY-1.6+ ref → run `bash scripts/installer/deploy.sh` → capture the verbatim `deploy.install.ok upgraded v2->v3 …` line → snapshot v3 `.installer-state.json` and confirm `installer_config_version=3` and `selected_defaults.backup_tool="rclone"` — materialized by `migrate_v2_to_v3` per the D-063 / D-065 seam — → re-probe `loopback_health` / `public_tls_probe` / `webhook_registration` (with a `/start` round-trip + canonical `telegram.webhook ... route=start ...` log line + matching `POST /telegram/webhook 200` access log + observed `/start` latency) / `offbox_backup_probe` (with one off-box cycle confirming `pg_backup.offbox.begin → pg_backup.offbox.ok` and `/archive/last_offbox.json status=ok`)); the evidence-file shape (four top-level branches `pre_upgrade_state`, `observed_migration`, `post_upgrade_state`, `summary`, plus `metadata` and `out_of_scope_for_this_packet`); and the mandatory redaction rule, quoted verbatim from the DEPLOY-1.7a / D-067 subsection so the rule and its pre-commit grep checklist (`$PUBLIC_HOSTNAME`, `$BACKUP_S3_BUCKET`, `$BACKUP_S3_ENDPOINT`, `$BACKUP_S3_PATH_PREFIX`, `$BACKUP_S3_ACCESS_KEY_ID`, `$BACKUP_S3_SECRET_ACCESS_KEY`, `$TELEGRAM_BOT_TOKEN`) do not drift.
- The new committed evidence-file template at `docs/deploy1-drill/deploy1-cross-version-drill-TEMPLATE.json` carrying a top-level `"_template": true` flag so it cannot be misread as real evidence, the four top-level branches above, and the dual placeholder convention — `<REDACTED>` for credential-bearing values and `<TO_FILL_BY_OPERATOR>` for outcomes the operator captures from the real drill. Stable values are pre-filled (the v2 install `commit_sha_at_install: "e435e1a"`, `expected_installer_config_version: 2 → 3`, the v3 `selected_defaults` shape, the structural `deploy.install.ok upgraded v2->v3 …` log-line shape, the structural `telegram.webhook update_id=<id> route=start ...` log-line shape). The operator's procedure is to copy this template to a UTC-dated working filename `docs/deploy1-drill/deploy1-cross-version-drill-<YYYYMMDD>-evidence.json`, drop the `"_template": true` flag, replace every `<TO_FILL_BY_OPERATOR>` placeholder, and run the redaction grep checklist before committing.

The closure of DEPLOY-1.7b and therefore DEPLOY-1 remains a future, operator-dependent step. The committed template plus the RUNBOOK subsection mean that when the operator finally has a real previously-installed v2 VPS, the only remaining work is to execute the documented procedure and commit the populated dated evidence artifact.

### Why
DEPLOY-1.7b is operator-dependent — it needs a separate, real, previously-installed v2 VPS that does not yet exist and that the development environment cannot synthesize. The bounded, autonomous work that can land now is the docs-first preparation: the operator procedure, the committed evidence-file template, and the cross-doc roadmap / execution-map / todo / decision-log updates that record the prep landing while keeping DEPLOY-1.7b and DEPLOY-1 explicitly open.

The precedent is D-066 → D-067: D-066 landed the local-only preflight harness (de-risk the configuration-versioning seam locally without claiming closure); D-067 landed the real-VPS pilot-smoke + off-box §2-invariant evidence (closure of the halves of DEPLOY-1.7 the development environment could verify). D-068 sits in the same shape: a narrowly-scoped follow-up sibling that closes one seam (here: pre-staging the operator drill so nothing remains beyond running it and capturing the evidence) without claiming overall closure. Packaging the docs prep together with the operator drill would stall the work already in hand on infrastructure the development environment cannot produce; landing the prep now means the operator drill is a single bounded action when it can run.

Committing the evidence-file template explicitly (with `"_template": true`, `<TO_FILL_BY_OPERATOR>` placeholders, and the operator-copy instruction in `metadata.notes`) — rather than leaving it implicit in the RUNBOOK subsection — eliminates the risk of the operator drill landing an evidence artifact whose shape drifts from the documented contract. The future dated artifact is mechanically derived by copying + filling the committed template.

### Consequence
- **New:** `docs/deploy1-drill/deploy1-cross-version-drill-TEMPLATE.json` — committed evidence-file template carrying `"_template": true`, the four top-level branches (`pre_upgrade_state`, `observed_migration`, `post_upgrade_state`, `summary`) plus `metadata` and `out_of_scope_for_this_packet`, the dual placeholder convention (`<REDACTED>` for credential-bearing values; `<TO_FILL_BY_OPERATOR>` for outcomes the operator captures), and stable pre-filled values (`commit_sha_at_install: "e435e1a"`, `expected_installer_config_version: 2 → 3`, v3 `selected_defaults` shape, structural log-line shapes). The dated working artifact (`docs/deploy1-drill/deploy1-cross-version-drill-<YYYYMMDD>-evidence.json`) is the future operator-execution packet's output, not D-068's.
- **Changed:** `docs/RUNBOOK.md` — new "v2 → v3 cross-version upgrade drill (DEPLOY-1.7b / D-068)" subsection inside the existing "Self-hosted VPS reference shape (DEPLOY-1 / D-060)" section, placed immediately after the DEPLOY-1.7a / D-067 subsection at the same `###` level. Names operator pre-conditions, the numbered run procedure, the evidence-file shape, and the explicit redaction rule (with the same grep checklist as D-067).
- **Changed:** `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` — §1 status paragraph extended with the D-068 prep-landing sentence (the operator drill remains outstanding; DEPLOY-1 remains open); §4 packet table DEPLOY-1.7b row pivoted from "Sole canonical next for closure" to "Prep landed (D-068) — operator drill outstanding" with the new template + RUNBOOK subsection named in the surfaces column; §5 dependency paragraph adjusted to note that the operator procedure + template are pre-staged via D-068 and that the only remaining work is operator execution + committing the populated artifact. **§6 exit criterion deliberately untouched** — DEPLOY-1.7b's closure contract is unchanged by the prep landing.
- **Changed:** `docs/execution-map.md` — DEPLOY-1.7b row updated to reflect that the procedure + template prep has landed and that the operator drill is outstanding.
- **Changed:** `docs/todo.md` — DEPLOY-1.7b entry pivoted from "sole canonical next for closure" framing to "prep landed (D-068); operator drill outstanding"; names the new RUNBOOK subsection and template path; reiterates that closure produces a populated dated evidence artifact.
- **No `src/` change**, no schema change, no migration change, no `tests/` change, no `pyproject.toml` / `uv.lock` change, no `Makefile` change, no `Dockerfile` / `.dockerignore` change, no `docker-compose.yml` change, no `.env.example` change, no `.gitignore` change, no `configs/caddy/Caddyfile` change, no change to `scripts/installer/deploy.sh`, `scripts/installer/drill_upgrade_local.sh`, `scripts/pg_offbox_uploader/`, `scripts/pg_backup/`, or `scripts/pg_restore/`.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` deliberately **not** touched — D-068 lands operator-procedure prep; it neither adds nor verifies a runtime invariant (the §2 "operator-facing idempotent install/upgrade script" invariant verification across version boundaries is DEPLOY-1.7b's operator-execution responsibility, not D-068's).
- `docs/assumptions.md` / `docs/assumption-audit.md` deliberately **not** touched — A-42 (DEPLOY-1 invariants) is closed by D-060; A-43 (logs-first observability scope) stays open and pinned to a later DEPLOY-1.x packet; no new assumption is opened.
- `docs/ARCHITECTURE.md`, `docs/product/{PRD,BuildPlan,TechSpec}.md`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `QUICKSTART.md`, `docs/GLOSSARY.md` — also not touched.
- **DEPLOY-1.7b prep is complete; the operator drill against a real previously-installed v2 VPS stays the sole canonical closure step; DEPLOY-1.7b and DEPLOY-1 stay open.**

### Out of scope (per packet boundaries)
- Running the v2 → v3 drill against a real previously-installed v2 VPS or committing real evidence values — that is the future operator-execution packet that closes DEPLOY-1.7b and DEPLOY-1.
- Any `src/` change, schema, migration, retrieval, answer-path, or domain-logic change.
- Any change to `scripts/installer/deploy.sh`, `scripts/installer/drill_upgrade_local.sh`, `scripts/pg_offbox_uploader/`, `scripts/pg_backup/`, `scripts/pg_restore/`, `docker-compose.yml`, `Caddyfile`, or `.env.example`.
- Any pinning of new defaults or further `INSTALLER_CONFIG_VERSION` bump (no `migrate_v3_to_v4` helper, no `selected_defaults` flip).
- Any change to `docs/INVARIANTS.md`, `docs/RUNTIME-INVARIANTS.md`, `docs/assumptions.md`, `docs/assumption-audit.md`, `docs/ARCHITECTURE.md`, `docs/product/{PRD,BuildPlan,TechSpec}.md`, `docs/GLOSSARY.md`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `QUICKSTART.md`.
- §6 of `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` exit criterion.
- The three Phase-4 UX polish observations flagged in D-067 (`/note` first-line ISO-date strictness; `/ask` user-facing wording leaking chunk UUID + the phrase "dense+sparse RRF"; no-memories-matched UX).
- A-43 logs-first observability scope work.

---

## D-069 — Post-DEPLOY-1 Phase-4 UX polish, packet 1: `/ask` user-facing reply de-leaks chunk UUID + `dense+sparse RRF`

### Decision
Close the first of the three Phase-4 UX-polish observations recorded in D-067 §Observations — the `/ask` user-facing reply leaks internal vocabulary (raw chunk UUIDs in `/sources` blocks; the literal ranking-method jargon `dense+sparse RRF` in the success-case trailer) — by adjusting two presentation surfaces only:

- **`/ask` success-case reply (`FallbackMode.NONE`)**: drop the `(hybrid retrieval — dense+sparse RRF)` trailer entirely. The reply is now `result.answer_text` alone. `WEAK_EVIDENCE` and `AMBIGUOUS` keep their plain-English explanatory trailers (`(weak evidence — model expressed uncertainty)` / `(ambiguous question — refine and ask again)`) unchanged; `NO_EVIDENCE` / `PROVIDER_UNAVAILABLE` / `PARSE_FAILURE` reply strings are unchanged.
- **`/sources` block rendering**: each chunk is rendered as `[YYYY-MM-DD] (i/N)\n\n<chunk_text>` where `i` is a 1-based index within the current `/ask`'s cached list (post-RRF order) and `N` is the chunk count. The raw `chunk_id` is no longer surfaced to the user. The `(i/N)` marker is per-last-`/ask` ephemeral ordering, **not** a stable cross-`/ask` identifier — the cache is overwritten by the next `/ask` per D-036. The `/sources` header sentence, cache lifecycle, fail-closed message, packing semantics, and outbound `(part k/N)` footer are unchanged.

The new wording lives in the same place the prior wording did — `src/memory_rag/services/dispatcher.py` — which is channel-neutral by design per its file-level docstring and Invariant I-1, so this is not a D-026 adapter-boundary move; it is a wording update in place.

### Why
D-067 §Observations recorded that the pilot operator observed the `/ask` reply surfacing a chunk UUID and the literal phrase `dense+sparse RRF`, framed as internal vocabulary that should not appear in the user-facing reply. D-067 explicitly deferred all three Phase-4 UX-polish observations to a separate post-DEPLOY-1 packet so they were not lost; this entry lands the first of those three. The functional invariants the canonical docs pin on the `/ask` reply (R-6 requested-vs-effective distinguishability; I-9 grounding via `AnswerTrace.context_chunk_ids`) are unaffected:

- **R-6 (distinguishability of degraded behavior).** Degraded modes keep their distinct user-visible surfaces — `WEAK_EVIDENCE`, `AMBIGUOUS`, `NO_EVIDENCE` (with its two sub-branches per `bool(result.evidence)`), `PROVIDER_UNAVAILABLE`, and `PARSE_FAILURE` each carry their own reply string. The success-case absence of a trailer is itself the signal that nothing degraded — it is the requested path. Removing the success-case trailer does not hide degraded behavior.
- **I-9 (every answer references chunks used as evidence).** `AnswerTrace.context_chunk_ids` continues to record every cited chunk's `chunk_id` for the durable grounding record; the RUNBOOK "Inspecting recent `/ask` retrieval traces (D-032)" SQL recipe stays the authoritative chunk-id surface for operators. The user-facing `/sources` reply was always the convenience surface, never the grounding record.

### Consequence
- **Changed:** `src/memory_rag/services/dispatcher.py` — removed the module-private `_RETRIEVAL_TRAILER` constant; `_format_answer_reply` `NONE` branch returns `result.answer_text or ""`; `_render_source_block` signature became `(chunk, *, index, total)` and now returns `f"[{chunk.note_date.isoformat()}] ({index}/{total})\n\n{chunk.chunk_text}"`; `_dispatch_sources` passes a 1-based index and `len(chunks)` per call. Both docstrings updated to describe the new shape (no decision number in code/docstrings — the canonical record is here).
- **Changed:** `tests/test_dispatcher_sources.py` — six `source_blocks` literal assertions updated to the new `(i/N)` shape (`test_ask_success_then_sources_returns_selected_chunks`, `test_two_successful_asks_sources_returns_only_latest`, `test_provider_unavailable_ask_overwrites_cache_with_retrieved_chunks`, `test_parse_failure_ask_overwrites_cache_with_retrieved_chunks`, `test_two_family_caches_are_independent`, `test_repeated_sources_does_not_clear_cache`). The chunk-id literals `c-1`, `c-2`, `a-1`, `b-1` no longer appear in expected outputs — the absence is itself the negative assertion that no UUID leaks.
- **Changed:** `tests/test_end_to_end_smoke.py` — `test_note_then_ask_returns_grounded_reply_with_date` and `test_question_plain_text_returns_grounded_reply_via_heuristic` both replaced their positive `(hybrid retrieval — dense+sparse RRF)` assertions with negative invariants (`"dense+sparse RRF" not in text`, `"hybrid retrieval" not in text`) plus an explicit `"\n\n" not in text` guardrail that ensures no remnant blank trailer line survives after `answer_text` (or between body and heuristic marker for the heuristic-routed case).
- **Changed:** `docs/RUNBOOK.md` — §"Selected-chunks recall (`/sources`, D-036)" rendering description updated to name `note_date` + 1-based `(i/N)` (with the per-last-`/ask` ephemeral framing called out explicitly) instead of `chunk_id`; §"Hybrid retrieval (D-025)" reply description updated to say the success-case reply is `answer_text` alone, with the degraded-mode trailers + log-line signal still in place.
- **Changed:** `docs/todo.md` — new "Post-DEPLOY-1 Phase-4 UX polish (D-067 observations)" milestone block with packet 1 marked done via D-069 and packets 2 / 3 (`/note` first-line ISO-date strictness; no-memories-matched UX) listed as pending separate packets.
- **Changed:** `docs/execution-map.md` — new row for the milestone, naming this packet's closure via D-069 and pointing to the dispatcher edit + RUNBOOK section updates.
- **No `src/` change outside `dispatcher.py`.** No schema change, no migration change, no `pyproject.toml` / `uv.lock` change, no `Makefile` change, no `Dockerfile` / `.dockerignore` change, no `docker-compose.yml` change, no `.env.example` change, no `.gitignore` change, no `configs/caddy/Caddyfile` change, no change to `scripts/installer/`, `scripts/pg_backup/`, `scripts/pg_offbox_uploader/`, or `scripts/pg_restore/`.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` deliberately **not** touched — R-6 and I-9 are unaffected (degraded modes still distinguishable; `AnswerTrace.context_chunk_ids` still records grounding).
- `docs/assumptions.md` / `docs/assumption-audit.md` deliberately **not** touched — no new assumption is opened; no existing assumption is closed.
- `docs/ARCHITECTURE.md`, `docs/product/{PRD,BuildPlan,TechSpec}.md`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `QUICKSTART.md`, `docs/GLOSSARY.md` — also not touched. The `docs/deploy1-drill/deploy1-cross-version-drill-TEMPLATE.json` listing of the three D-067 observations as `out_of_scope_for_this_packet` stays accurate — they remain out of DEPLOY-1.7b scope (DEPLOY-1.7b is a different operator drill, and D-069 closes only the first of the three observations against this separate post-DEPLOY-1 milestone).

### Out of scope (per packet boundaries)
- The other two D-067 §Observations — `/note` first-line ISO-date strictness (packet 2) and no-memories-matched UX (packet 3). Each gets its own packet within this post-DEPLOY-1 Phase-4 UX polish milestone.
- Any change to retrieval (RRF k-constant, dense / sparse legs, embedding model), scoring, ranking, prompt building, LLM call, fallback classification, or chat-client adapters.
- Any change to persistence: `Query`, `RetrievalHit` (incl. `leg ∈ {dense, sparse, merged}` and the `1.0 / (RRF_K + rank)` scores), `AnswerTrace.context_chunk_ids`, `event_chunks`, `notes`, `source_messages`, schemas, migrations.
- Any change to internal logs (`retrieval.hybrid …`, `retrieval.unavailable …`, `draft.persisted …`, `telegram.webhook …`). The `dense+sparse RRF` phrasing stays acceptable in operator-only log surfaces.
- Rendering `StructuredAnswer.cited_chunk_ids` (the LLM-emitted citation subset) — deferred from D-036; not in scope here.
- Fine-grained / per-quote / per-sentence attribution; user-facing `/trace` command; cross-restart or cross-worker durability of `_latest_sources` cache.
- DEPLOY-1.7b — v2 → v3 cross-version upgrade drill against a real previously-installed v2 VPS (sole canonical remaining DEPLOY-1 closure packet per D-067 / D-068).
- Any change to `docs/INVARIANTS.md`, `docs/RUNTIME-INVARIANTS.md`, `docs/assumptions.md`, `docs/assumption-audit.md`, `docs/ARCHITECTURE.md`, `docs/product/{PRD,BuildPlan,TechSpec}.md`, `docs/GLOSSARY.md`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `QUICKSTART.md`.
- A-43 logs-first observability scope work.

---

## D-070 — Post-DEPLOY-1 Phase-4 UX polish, packet 2: `/note` first-line date — six-form near-ISO whitelist + de-leaked error wording + proactive `/start` blurb

### Decision
Close the second of the three Phase-4 UX-polish observations recorded in D-067 §Observations — the `/note` first-line date parser was stricter than operator expectation and the user-facing error wording leaked the dev label `Mock` while giving no concrete example of what to type — by adjusting three presentation surfaces on the explicit `/note` dispatch path only:

- **Explicit `/note` first-line normalization.** The dispatcher's `RouteKind.NOTE` branch, when `is_heuristic=False`, runs the first non-empty line of `message.payload` through a new pure helper `normalize_iso_date_token` (in `core/domain/parser.py`) that accepts a six-form near-ISO whitelist — `YYYY-MM-DD`, `YYYY/MM/DD`, `YYYY.MM.DD`, `DD-MM-YYYY`, `DD/MM/YYYY`, `DD.MM.YYYY` (zero-padded only) — and rewrites it to canonical `YYYY-MM-DD` before passing the message to `DomainService.ingest`. The strict `parse_note` / `_parse_iso_date` / `_split_non_empty_lines` parser internals are byte-for-byte unchanged; the normalizer is purely additive.
- **DD-first inputs are always interpreted as DD/MM/YYYY by intentional product convention.** There is no fallback heuristic, no per-input ambiguity branch, no MM/DD/YYYY fallback. Concrete pin: `05/09/2026` → `2026-09-05` (5 September 2026, never 9 May 2026). The same convention applies to the DD-first `-` and `.` separators. This is named and tested as a convention pin, not as ambiguity handling.
- **User-facing error wording de-leaks `Mock`.** When the first line falls outside the whitelist and the strict parser then returns `None`, the `INVALID_INPUT` reply changes from `"Mock /note needs an ISO date (YYYY-MM-DD) on the first line. Got: '<got>'."` to `"First line must be a date like 2026-05-09. Got: '<got>'."` — drops the dev-leaking `Mock` label (mirroring D-069's de-leak pattern) and offers the operator a concrete canonical example to copy.
- **Proactive `/start` blurb.** `_REPLY_START` is extended with one short sentence naming the recommended `2026-05-09` form, listing the other five accepted forms, and explicitly stating that DD-first is read as DD/MM/YYYY — so the parent is warned at the welcome surface, not only in operator docs.

The new wording and the normalizer call site live in the same channel-neutral module the prior wording did (`src/memory_rag/services/dispatcher.py`, channel-neutral per Invariant I-1 and its file-level docstring), so this is not a D-026 adapter-boundary move; it is a localized in-place change.

### Why
D-067 §Observations recorded that the pilot operator observed the `/note` first-line date parser was stricter than operator expectation and that both the surface-level wording and the parse behavior should be revisited. D-067 explicitly deferred all three Phase-4 UX-polish observations to a separate post-DEPLOY-1 packet so they were not lost; this entry lands the second of those three (the first being D-069). The functional invariants the canonical docs pin on the `/note` lifecycle are unaffected:

- **I-5 (one event per line) / I-15 (raw-message highest durability tier).** Unchanged. The normalizer rewrites only the first-line date token in-place; the surrounding `splitlines(keepends=True)` reassembly preserves the body byte-for-byte. Raw `SourceMessage` is still recorded for both success and `INVALID_INPUT` cases as today.
- **R-13 (draft floor).** Unchanged. The draft path is untouched. The legacy heuristic plain-text NOTE auto-route in `core/routing/classifier.py` is deliberately not coupled to the new whitelist — it continues to call the strict `parse_note` and fire only for canonical `YYYY-MM-DD` plain text. That legacy auto-route is misaligned with the drafts-vs-notes product contract (drafts are stored relationally but are not chunked, embedded, indexed, or part of the retrieval corpus) and is slated for a separate cleanup/refactor milestone; D-070 ships a regression guardrail test (`test_heuristic_classifier_not_broadened_by_packet_2`) whose docstring explicitly names this as a *guard against accidental coupling*, not an assertion about the desired long-term shape of the heuristic.
- **D-026 (host-neutral core).** Unchanged. The parser helper takes a plain string token and returns a plain string. The dispatcher helper takes and returns an `InboundMessage` via `dataclasses.replace`. No transport types, host identifiers, provider SDKs, or use-case vocabulary appear in either.

The DD/MM/YYYY convention pin is an explicit product choice — not a parser side effect. `05/09/2026` deterministically becomes `2026-09-05`; a US-locale operator who meant 9 May must use the canonical `2026-05-09` form (the new error wording, the `/start` blurb, and the RUNBOOK subsection all point at that canonical form).

### Consequence
- **Changed:** `src/memory_rag/core/domain/parser.py` — added the pure helper `normalize_iso_date_token(token: object) -> str | None` plus two module-private regex constants (`_YYYY_FIRST_RE`, `_DD_FIRST_RE`) with exact `\d{4}` / `\d{2}` quantifiers, back-reference-enforced single separator, and a final `date.fromisoformat` calendar-validity guard. `ParsedNote`, `parse_note`, `_parse_iso_date`, and `_split_non_empty_lines` are byte-for-byte unchanged. Module docstring extended to name the new additive seam; no decision number in code/docstrings — the canonical record is here.
- **Changed:** `src/memory_rag/services/dispatcher.py` — added the dispatcher-local helper `_normalize_note_first_line(message: InboundMessage) -> InboundMessage` (uses `splitlines(keepends=True)` to locate the first non-empty line, runs it through `normalize_iso_date_token`, and either returns the message unchanged or returns a `dataclasses.replace(message, payload=...)` with only the first-line token rewritten — surrounding whitespace and newlines are preserved). Wired into the `RouteKind.NOTE` branch under an explicit `if not is_heuristic:` guard so the heuristic auto-route path is byte-identical to before. `_format_ingest_reply` now returns `"First line must be a date like 2026-05-09. Got: '<got>'."` on `INVALID_INPUT` (the `"Mock"` prefix is gone). `_REPLY_START` extended by one sentence naming the canonical form, listing the other five accepted forms, and stating the DD/MM/YYYY convention. New top-level import `import dataclasses` and `from memory_rag.core.domain.parser import normalize_iso_date_token`.
- **Changed:** `tests/test_note_parser.py` — added eight new parametrized blocks for `normalize_iso_date_token`: the six-form positive whitelist, the DD/MM/YYYY convention pin (`05/09/2026` → `2026-09-05`), the unpadded reject list (eight cases), the mixed-separator reject list, the natural-language reject list, the empty/junk reject list, the impossible-calendar-date reject list (`2026-02-30`, `30-02-2026`, `2026-13-01`, `32-01-2026`), and the non-string-input reject + whitespace-stripping cases. The existing `parse_note` tests (eight cases) remain untouched — proves in-parser strictness was preserved.
- **Added:** `tests/test_dispatcher_note_normalization.py` — new file with eleven tests covering the helper directly (rewrites whitelisted forms, applies the DD/MM/YYYY convention, is a no-op for canonical/unmatched/unpadded/empty inputs, skips leading blank lines like the parser) and the dispatcher seam (explicit `/note` with a slash-separated date persists the canonical date, explicit `/note` with DD-first uses the DD/MM/YYYY convention, explicit `/note` with an unmatched first line returns the new error wording with no `"Mock"`, heuristic-routed messages are not normalized). Plus two `/start` blurb pins asserting both `"2026-05-09"` and `"DD/MM/YYYY"` are present in `_REPLY_START`.
- **Changed:** `tests/test_end_to_end_smoke.py` — `test_note_with_invalid_first_line_returns_invalid_input_and_persists_source` updated to assert the new error string and explicitly assert `"Mock" not in text`. Added `test_explicit_note_with_slash_separated_yyyy_first_is_normalized_and_saved`, `test_explicit_note_with_dd_first_uses_dd_mm_yyyy_convention_pin` (the convention pin at the smoke layer — `05/09/2026` → `Saved 1 event for 2026-09-05.`), `test_explicit_note_with_dot_separated_date_is_normalized_and_saved`, `test_explicit_note_with_unpadded_date_is_rejected` (unpadded `2026-5-9` rejected), and the legacy-classifier regression guardrail `test_heuristic_classifier_not_broadened_by_packet_2` whose body and docstring explicitly frame it as a guard against accidental coupling rather than a contract assertion.
- **Changed:** `docs/RUNBOOK.md` — new "`/note` first-line date format (D-070)" subsection inside the existing §"Command surface (D-028, D-030, D-031, D-036)" section, immediately after the operational paragraph. Names the six accepted forms, the DD/MM/YYYY convention pin with the verbatim example `05/09/2026 → 2026-09-05`, the rejected categories, the new error string verbatim, the operator script for the parent, and the explicit scope note that the legacy heuristic auto-route is not coupled and is slated for separate cleanup.
- **Changed:** `docs/execution-map.md` — new Packet 2 row added under the existing "Post-DEPLOY-1 Phase-4 UX polish" milestone block, naming the parser helper, dispatcher seam, the `/start` text edit, the DD/MM/YYYY convention pin, the three test additions, the four doc files touched, and the explicit "no classifier change; no A-28 edit; no retrieval / schema change" boundary.
- **Changed:** `docs/todo.md` — Packet 2 line flipped from `pending` to `done (D-070)`; one-line summary mirrors the D-069 line shape; Packet 3 (no-memories-matched UX) kept `pending`.
- **Changed:** `QUICKSTART.md` — the inline curl-example error-reply literal updated to the new wording so the smoke example stays accurate.
- **No `src/` change outside `parser.py` and `dispatcher.py`.** No schema change, no migration change, no `pyproject.toml` / `uv.lock` change, no `Makefile` change, no `Dockerfile` / `.dockerignore` change, no `docker-compose.yml` change, no `.env.example` change, no `.gitignore` change, no `configs/caddy/Caddyfile` change, no change to `scripts/installer/`, `scripts/pg_backup/`, `scripts/pg_offbox_uploader/`, or `scripts/pg_restore/`.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` deliberately **not** touched — I-5 / I-15 / R-13 are unaffected.
- `docs/assumptions.md` / `docs/assumption-audit.md` deliberately **not** touched. A-28 (`Mock /note accepts ISO-only dates`: *"the date parser in `core/domain/parser.py` recognizes only `YYYY-MM-DD` on the first non-empty line"*) is still strictly accurate at the named code location — the in-parser strictness is byte-for-byte preserved; the new dispatcher-side normalization is a separate additive seam in a different module and is documented here plus in RUNBOOK plus in `/start`. Editing A-28 to also describe the dispatcher seam would conflate two surfaces and partially document a system where the legacy heuristic auto-route is still pending separate cleanup. A holistic A-28 rewrite is deferred to the legacy-classifier cleanup milestone so the rewrite can describe the final-state surface in one pass.
- `docs/ARCHITECTURE.md`, `docs/product/{PRD,BuildPlan,TechSpec}.md`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `docs/GLOSSARY.md` — also not touched. The `docs/deploy1-drill/deploy1-cross-version-drill-TEMPLATE.json` listing of the three D-067 observations as `out_of_scope_for_this_packet` stays accurate — D-070 closes the second of the three observations against this separate post-DEPLOY-1 milestone.

### Out of scope (per packet boundaries)
- The remaining D-067 §Observation — no-memories-matched UX (packet 3 of this milestone).
- **Heuristic plain-text NOTE auto-route loosening.** The legacy classifier surface in `src/memory_rag/core/routing/classifier.py:76-78` is not modified and its strictness is not endorsed as a long-term contract by this packet. It is misaligned with the drafts-vs-notes product contract and will be addressed in a separate cleanup/refactor milestone. The regression guardrail test landed here only proves Packet 2 did not couple into it.
- Locale-prefs / natural-language / relative dates (`May 9 2026`, `today`, `yesterday`, MM/DD/YYYY interpretation). Intentionally rejected — would require either a per-community locale setting or a clock seam for "today".
- Unpadded near-ISO forms (`2026-5-9`, `9/5/2026`). Intentionally rejected per the owner-fixed whitelist.
- Adding the same date-format blurb to `/help` or `_REPLY_CLARIFY` or `_DRAFT_REPLY_HINT`. The owner specified `/start` only; those other surfaces still reference `<YYYY-MM-DD>` which remains the canonical-form guidance and is still correct.
- Renaming `INVALID_INPUT` / `FallbackMode`. Internal vocabulary, not user-facing.
- Any change to retrieval, scoring, ranking, embedding model, prompt building, LLM call, fallback classification, chat-client adapters, or persistence (`Note`, `EventChunk`, `SourceMessage`, `Query`, `RetrievalHit`, `AnswerTrace`, schemas, migrations).
- Any change to `docs/INVARIANTS.md`, `docs/RUNTIME-INVARIANTS.md`, `docs/assumptions.md`, `docs/assumption-audit.md`, `docs/ARCHITECTURE.md`, `docs/product/{PRD,BuildPlan,TechSpec}.md`, `docs/GLOSSARY.md`, `AGENTS.md`, `CLAUDE.md`, `README.md`.
- DEPLOY-1.7b — v2 → v3 cross-version upgrade drill against a real previously-installed v2 VPS (sole canonical remaining DEPLOY-1 closure packet per D-067 / D-068).

---

## D-071 — Post-DEPLOY-1 Phase-4 UX polish, packet 3: `/ask` empty-evidence NO_EVIDENCE reply gets plain-language wording + two short question-side nudges

### Decision
Close the third and final Phase-4 UX-polish observation recorded in D-067 §Observations — when retrieval returns zero matches, the user-facing `/ask` reply was the bare string `"No memories matched 'X'."`, which was terse, used the non-canonical noun "memories" (canonical record-noun is `note` per `docs/GLOSSARY.md`), and gave the user no operational next step — by adjusting one presentation surface only:

- **Empty-evidence `/ask` reply wording.** The dispatcher's `FallbackMode.NO_EVIDENCE` branch where `result.query_text` is non-empty and `result.evidence` is empty now returns `"Nothing in your saved notes matched '{query}'. Try rephrasing the question, or use words that appear in your notes."` — driven by a new module-level template constant `_REPLY_NO_MATCHES_TEMPLATE` (mirroring the existing `_REPLY_PROVIDER_UNAVAILABLE` / `_REPLY_PARSE_FAILURE` constant pattern). The new wording is plain-language, uses the canonical "notes" noun, stays scoped to "nothing matched this question among your saved notes" (does **not** imply the user has no data at all), and offers two short question-side nudges from the allowed palette (rephrase the question; use words that appear in your notes). No `/help` nudge, no `/note` capture-nudge, no command-surface expansion, no broader coaching text.
- **Cause-neutral framing.** The new wording describes the empty-match *outcome* only; it does not name or imply a *technical reason* for the empty match. The dispatcher's internal funnelling of distinct upstream signals through this one branch (genuinely-empty merged retrieval; SQLite/`NotImplementedError` retrieval-unavailable path translated to `NO_EVIDENCE` per D-025) is an implementation property, not part of the user-facing surface.
- **Vocabulary migration scoped to this one branch.** The "memories" → "notes" rename is confined to (a) this one dispatcher branch, (b) the four locked test asserts that pinned the prior literal, and (c) the four documentation surfaces that quoted the prior literal. Product-prose mentions of "memory/journal core", "Diary Memory Service", and similar product names are out of scope and stay as-is; internal log fields are not touched.
- **Sibling fallback wording preserved with an explicit anti-bleed guard.** The empty-query NO_EVIDENCE literal (`"No query text provided."`), the LLM-marker NO_EVIDENCE literal (`"Found possible matches but couldn't ground an answer for '…'. Try refining the question."`), `_REPLY_PROVIDER_UNAVAILABLE`, `_REPLY_PARSE_FAILURE`, `_TRAILER_WEAK_EVIDENCE`, `_TRAILER_AMBIGUOUS`, and the `NONE` success-case body all stay byte-identical. A new explicit byte-equality guard test `test_sibling_fallback_wording_unchanged` in `tests/test_dispatcher_retrieval_fallback.py` pins the `PROVIDER_UNAVAILABLE` and `PARSE_FAILURE` literals as the packet's own anti-bleed safety net — redundant with the existing per-mode tests by design.
- **`/start` not reopened.** Packet 2 (D-070) is `_REPLY_START`'s canonical owner; this packet does not touch it.

The new wording lives in the same channel-neutral module the prior wording did (`src/memory_rag/services/dispatcher.py`, channel-neutral per Invariant I-1 and its file-level docstring); this is not a D-026 adapter-boundary move, it is a wording update in place.

### Why
D-067 §Observations recorded that the pilot operator observed the empty-retrieval `/ask` reply needed a clearer / more helpful surface than the bare `"No memories matched 'X'."`. D-067 explicitly deferred all three Phase-4 UX-polish observations to a separate post-DEPLOY-1 packet so they were not lost; D-069 landed the first (chunk-UUID / `dense+sparse RRF` de-leak), D-070 landed the second (`/note` first-line date), and this entry lands the third and final one — closing the "Post-DEPLOY-1 Phase-4 UX polish" milestone. The functional invariants the canonical docs pin on the `/ask` reply (R-6 requested-vs-effective distinguishability; I-9 grounding via `AnswerTrace.context_chunk_ids`; I-1 channel-neutral wording) are unaffected:

- **R-6 (distinguishability of degraded behavior).** The new empty-evidence reply is byte-distinct from the LLM-marker NO_EVIDENCE reply (`"Found possible matches but couldn't ground an answer for '…'. Try refining the question."`) and from all sibling fallback replies. The existing distinctness assertion at `tests/test_dispatcher_retrieval_fallback.py:test_llm_marker_no_evidence_distinct_from_empty_retrieval` continues to hold and the new sibling-wording guard test pins the PROVIDER_UNAVAILABLE / PARSE_FAILURE literals explicitly.
- **I-9 (every answer references chunks used as evidence).** Unaffected — this packet does not touch `AnswerTrace.context_chunk_ids`, the persisted Query / RetrievalHit shape, or the `/sources` surface.
- **I-1 (channel-neutral wording).** Preserved — the new string lives in `dispatcher.py` where the prior wording lived; no string moves into the Telegram adapter.

The historical empty-evidence wording quoted in D-035 (decision-log entries at the time of Slice 4.3 / 4.4) at lines 732 / 745 / 764 is preserved as historical record of what D-035 chose; D-071 is the live successor surface. The earlier "(unchanged)" annotation in D-035 was an explicit pin through the Phase-4 milestone; D-071 supersedes that pin only for this single branch, as the planning packet that closes the third D-067 observation.

The vocabulary migration to "notes" aligns the user-facing reply with the canonical core vocabulary set out in `docs/GLOSSARY.md` (the canonical record-noun is `note`; the table is `notes`; D-042's renaming roadmap already migrated `DiaryEntry → Note` in code/schema). The empty-evidence reply was one of the last user-facing surfaces still using the non-canonical "memories" word; the migration is contour-scoped so that product-prose usages of "memory/journal core" (which is the *system* name, not a record-noun) and unrelated user surfaces are not collaterally touched.

### Consequence
- **Changed:** `src/memory_rag/services/dispatcher.py` — added a new module-level constant `_REPLY_NO_MATCHES_TEMPLATE = "Nothing in your saved notes matched '{query}'. Try rephrasing the question, or use words that appear in your notes."` (placed alongside the existing `_REPLY_PROVIDER_UNAVAILABLE` / `_REPLY_PARSE_FAILURE` constants); the empty-evidence branch of `_format_answer_reply` (formerly `return f"No memories matched '{result.query_text}'."`) now returns `_REPLY_NO_MATCHES_TEMPLATE.format(query=result.query_text)`. `_format_answer_reply` docstring updated to describe the new empty-evidence shape (no decision number in code/docstrings — the canonical record is here). No other source line in `dispatcher.py` is touched.
- **Changed:** `tests/test_dispatcher_retrieval_fallback.py` — `test_not_implemented_error_translates_to_no_evidence` and `test_llm_marker_no_evidence_distinct_from_empty_retrieval` updated to assert the new empty-evidence literal; the byte-distinctness assertion in the latter test (and the LLM-marker literal it pins) continues to hold. Added `test_sibling_fallback_wording_unchanged` — a new explicit byte-equality guard pinning the `PROVIDER_UNAVAILABLE` and `PARSE_FAILURE` reply literals so any accidental cross-contour wording change is caught in this packet's own test diff, not only by the per-mode tests above.
- **Changed:** `tests/test_end_to_end_smoke.py` — `test_ask_with_no_match_returns_no_evidence_fallback` and `test_ask_before_any_note_returns_no_evidence` updated to assert the new empty-evidence literal at the smoke layer.
- **Changed:** `docs/RUNBOOK.md` — §"Hybrid retrieval (D-025)" sentence describing the empty-merged-set reply replaced with the new wording, framed neutrally about cause and naming the two short user-side nudges.
- **Changed:** `QUICKSTART.md` — the two inline `# → text: …` example-output comments for the empty-retrieval contour (one in the Postgres smoke, one in the SQLite smoke) updated to the new wording.
- **Changed:** `docs/todo.md` — Packet 3 line flipped from `pending` to `done (D-071)`; the "Post-DEPLOY-1 Phase-4 UX polish" milestone block flagged as closed.
- **Changed:** `docs/execution-map.md` — Packet 3 row updated from `pending` to `done via D-071` with the dispatcher edit + RUNBOOK + QUICKSTART surfaces named.
- **No `src/` change outside `dispatcher.py`.** No schema change, no migration change, no `pyproject.toml` / `uv.lock` change, no `Makefile` change, no `Dockerfile` / `.dockerignore` change, no `docker-compose.yml` change, no `.env.example` change, no `.gitignore` change, no `configs/caddy/Caddyfile` change, no change to `scripts/installer/`, `scripts/pg_backup/`, `scripts/pg_offbox_uploader/`, or `scripts/pg_restore/`.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` deliberately **not** touched — R-6, I-9, and I-1 are unaffected.
- `docs/assumptions.md` / `docs/assumption-audit.md` deliberately **not** touched — no new assumption is opened; no existing assumption is closed.
- `docs/ARCHITECTURE.md`, `docs/product/{PRD,BuildPlan,TechSpec}.md`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `docs/GLOSSARY.md` — also not touched. D-035's quotations of the prior empty-evidence wording at decision-log lines 732 / 745 / 764 are preserved as historical record of D-035; D-071 is the live successor surface.

### Out of scope (per packet boundaries)
- Any change to the LLM-marker NO_EVIDENCE reply, the empty-query (`"No query text provided."`) reply, or sibling fallback wording (`WEAK_EVIDENCE`, `AMBIGUOUS`, `PROVIDER_UNAVAILABLE`, `PARSE_FAILURE`, `NONE`). The new sibling-wording guard test pins the last two byte-for-byte; the empty-query and LLM-marker literals are pinned by their existing tests.
- `/start` wording — owned by D-070 (Packet 2 of this milestone); not reopened here.
- Any new commands, new UI flows, trace/debug user surfaces, broader onboarding text, imports, or product-capability expansion.
- Cross-contour vocabulary sweep (e.g. flipping "memories" in product-prose docs, log-field names, system names like "memory/journal core" / "Diary Memory Service", or unrelated user surfaces). The "memories" → "notes" migration is contour-scoped to this one user-facing branch.
- Any surface-level disambiguation between the distinct upstream signals that the dispatcher currently funnels through this one branch (genuinely-empty merged retrieval vs. SQLite/`NotImplementedError` retrieval-unavailable). The user-facing wording stays neutral; surfacing those signals separately would be a different packet.
- Any change to retrieval (RRF k-constant, dense / sparse legs, embedding model), scoring, ranking, prompt building, LLM call, fallback classification, or chat-client adapters.
- Any change to persistence: `Query`, `RetrievalHit`, `AnswerTrace`, `event_chunks`, `notes`, `source_messages`, schemas, migrations.
- Any change to internal logs (`retrieval.hybrid …`, `retrieval.unavailable …`, `draft.persisted …`, `telegram.webhook …`).
- Apostrophe-in-query rendering improvements (queries like `today's walk` continue to render as the prior string did — `'today's walk'` — with the existing single-quote behavior; no new escaping, no improvement, no regression).
- Sibling-subject / "did you mean another subject" hints (D-040-adjacent); these are explicitly out of scope today.
- DEPLOY-1.7b — v2 → v3 cross-version upgrade drill against a real previously-installed v2 VPS (sole canonical remaining DEPLOY-1 closure packet per D-067 / D-068).
- A-43 logs-first observability scope work.

---

## D-073 — Real-answer end-to-end value-loop proof (REAL-1) prep: operator procedure + evidence-file template for one recorded /note → retrieval → grounded-answer round-trip against real OpenAI

### Decision
Open the **Real-answer end-to-end value-loop proof (REAL-1)** milestone and land its **docs-first operator-procedure preparation** (REAL-1.0) — the RUNBOOK procedure, the committed evidence-file template, and the cross-doc registration — ahead of the operator execution itself (REAL-1.1). REAL-1.1 remains the sole closure step for REAL-1. The next free decision number on this branch is D-073: D-072 is parked on the sibling `rescue/d072-doc-closure-and-routing-contract` branch (the checkpoint commit message reads *"preserve D-072 routing/doc work before baseline reprioritization"*) and is deliberately not reused here, so the rescue work can land later at its original number without renumbering.

D-073 mirrors the D-068 (DEPLOY-1.7b prep) precedent shape: a narrowly-scoped prep packet that pins the artifact shape + procedure + cross-doc registration now, isolating the operator-dependent live-run capture into a single subsequent action. The motivation is the same — the live run cannot be authored autonomously without operator credentials (real `OPENAI_API_KEY`, real Telegram webhook secret, real Postgres), but the artifact *shape*, the *procedure*, and the *milestone registration* can — and pinning those first is the smallest autonomous step that materially advances the milestone without widening scope.

D-073 lands via:

- The new `docs/RUNBOOK.md` "Real-answer end-to-end smoke (REAL-1 / D-073)" subsection at `###` level, placed inside the existing top-level "Operations" group immediately after the "Answer traces (D-034, D-035)" subsection and before the "Selected-chunks recall (`/sources`, D-036)" subsection so it sits adjacent to the inspection surfaces it depends on. Names operator pre-conditions (the canonical env knobs — `STORAGE_BACKEND=postgres`, `EMBEDDING_BACKEND=openai`, `EMBEDDING_MODEL=text-embedding-3-large`, `EMBEDDING_DIMENSION=3072`, `CHAT_BACKEND=openai`, `CHAT_MODEL=gpt-4.1`, `TELEGRAM_WEBHOOK_SECRET` set — and the boot-gate enforcement in `src/memory_rag/app.py`'s `_verify_embedding_contour` / `_verify_chat_contour`); the numbered run procedure (export env → `docker compose --profile vps up -d --build` → confirm verbatim `app.created` line → POST `/note` reusing the QUICKSTART.md:87-92 curl shape with the real webhook secret → confirm `embedding_status='ready'` via SQL → POST `/ask` reusing the QUICKSTART.md:95-99 curl shape → capture the verbatim `answer_traces` row via the existing one-liner from §"Answer traces (D-034, D-035)" with `LIMIT 1` → capture the two `provider.attempt` log lines (embedding + chat) → hand-assemble the dated artifact by copying the template + dropping the `"_template": true` flag + replacing every `<TO_FILL_BY_OPERATOR>` placeholder → run the redaction grep checklist); the evidence-file shape (five top-level branches `metadata`, `preflight_state`, `note_round_trip`, `ask_round_trip`, `summary`, plus the verbatim `out_of_scope_for_this_packet` block); the mandatory redaction rule with a pre-commit grep checklist (`$OPENAI_API_KEY`, `$TELEGRAM_BOT_TOKEN`, `$TELEGRAM_WEBHOOK_SECRET`, `$PUBLIC_HOSTNAME`); the closure signal (a populated dated `docs/real-answer-drill/real-answer-smoke-<YYYYMMDD>-evidence.json` with all three summary booleans `true` and `closes_real_1: true`); and an explicit `make check` non-impact note (no live OpenAI in CI; no new gated test).
- The new committed evidence-file template at `docs/real-answer-drill/real-answer-smoke-TEMPLATE.json` carrying a top-level `"_template": true` flag so it cannot be misread as real evidence, the five top-level branches above, and the dual placeholder convention — `<REDACTED>` for credential-bearing values and `<TO_FILL_BY_OPERATOR>` for outcomes the operator captures from the real run. Stable values are pre-filled (`preflight_state.env_knobs.STORAGE_BACKEND="postgres"`, `EMBEDDING_BACKEND="openai"`, `EMBEDDING_MODEL="text-embedding-3-large"`, `EMBEDDING_DIMENSION=3072`, `CHAT_BACKEND="openai"`, `CHAT_MODEL="gpt-4.1"`; the structural `app.created … embedding_backend=openai embedding_dim=3072 chat_backend=openai chat_model=gpt-4.1` log-line shape; the `provider.attempt label=openai_embedding …` and `provider.attempt label=openai_chat …` shapes; the expected `answer_traces` row contract `fallback_mode='none'`, `model_name='gpt-4.1'`, `prompt_version='v1'`, non-empty `context_chunk_ids`, non-zero `latency_ms`, non-empty `token_counts`).

The closure of REAL-1.1 and therefore REAL-1 remains a future, operator-dependent step. The committed template plus the RUNBOOK subsection mean that when the operator has credentials in hand, the only remaining work is to execute the documented procedure and commit the populated dated evidence artifact.

### Why
The product baseline is incomplete under the binding owner rule until at least one real-backend `/note` → retrieval → grounded-answer round-trip has been recorded as a committed evidence artifact. The OpenAI-side adapters (D-024 embeddings; D-037 chat client + boot gate), the OP-2 bounded-retry / backoff (D-047 / D-049), the OP-4 backup automation (D-054 / D-055), and the OP-5 inspection harness (D-056 / D-057 / D-058 / D-059) contours are all already wired and validated in mock — what is missing is the captured live run.

A single-packet "land the live run + populated dated artifact" approach would be the DEPLOY-1.7a precedent (D-067), but the live run cannot be authored autonomously without operator credentials. The D-068 / DEPLOY-1.7b precedent already shows the canonical split for this constraint: prep packet first (procedure + committed template + cross-doc registration), live-run packet second. REAL-1.0 takes that shape.

Committing the evidence-file template explicitly (with `"_template": true`, `<TO_FILL_BY_OPERATOR>` placeholders, and the operator-copy instruction in `metadata.notes`) — rather than leaving it implicit in the RUNBOOK subsection — eliminates the risk of REAL-1.1 landing an artifact whose shape drifts from the documented contract. The future dated artifact is mechanically derived by copying + filling the committed template.

The five-branch artifact shape (`metadata`, `preflight_state`, `note_round_trip`, `ask_round_trip`, `summary`) is the minimum that proves the value loop end-to-end: `preflight_state` records the boot-gate green signal (the canonical env-knob set actually reached `app.created`); `note_round_trip` records that the embedding path took (`embedding_status='ready'`, real `model_name=text-embedding-3-large` at dim 3072, one `provider.attempt label=openai_embedding`); `ask_round_trip` records that the chat path took (`fallback_mode='none'`, `model_name='gpt-4.1'`, non-empty `context_chunk_ids`, non-zero `latency_ms`, non-empty `token_counts`, one `provider.attempt label=openai_chat`, the verbatim user-facing reply that references the saved note content); `summary` records the three closure booleans. No additional branches are needed because OP-2 / OP-4 / OP-5 already supply the inspection surfaces the procedure leans on — `provider.attempt` for resilience, `answer_traces` for the answer-side trace, the existing operator SQL for retrieval-side inspection. **Reuse-only**: REAL-1.0 introduces no new resilience knob, no new aggregate, no new harness code, no extension of `_TRUNCATE_TABLES`, and no behavioral change.

### Consequence
- **New:** `docs/real-answer-drill/real-answer-smoke-TEMPLATE.json` — committed evidence-file template carrying `"_template": true`, five top-level branches (`metadata`, `preflight_state`, `note_round_trip`, `ask_round_trip`, `summary`) plus `out_of_scope_for_this_packet`, the dual placeholder convention (`<REDACTED>` for credential-bearing values; `<TO_FILL_BY_OPERATOR>` for outcomes the operator captures), and stable pre-filled values (`preflight_state.env_knobs.STORAGE_BACKEND="postgres"`, the openai backends + canonical models + 3072 dim, structural log-line shapes, the expected `answer_traces` row contract). The dated working artifact (`docs/real-answer-drill/real-answer-smoke-<YYYYMMDD>-evidence.json`) is REAL-1.1's output, not D-073's.
- **Changed:** `docs/RUNBOOK.md` — new "Real-answer end-to-end smoke (REAL-1 / D-073)" subsection at `###` level placed between "Answer traces (D-034, D-035)" and "Selected-chunks recall (`/sources`, D-036)". Names operator pre-conditions, the numbered run procedure, the evidence-file shape, the explicit redaction rule (with the credential grep checklist), the closure signal, and the `make check` non-impact note.
- **Changed:** `docs/todo.md` — new "Real-answer end-to-end value-loop proof (REAL-1) — in progress" milestone block placed after the closed "Post-DEPLOY-1 Phase-4 UX polish" block and before the OP-1 section. Two bullets: REAL-1.0 prep done (D-073); REAL-1.1 live run outstanding.
- **Changed:** `docs/execution-map.md` — new "Real-answer e2e proof rollout *(sequenced separately from the Phase/Stage axis)*" section placed after the closed "Post-DEPLOY-1 Phase-4 UX polish" section. Two rows: REAL-1.0 operator-procedure prep (done, → D-073); REAL-1.1 operator live run + populated dated evidence (outstanding).
- **No `src/` change**, no schema change, no migration change, no `tests/` change, no `pyproject.toml` / `uv.lock` change, no `Makefile` change, no `Dockerfile` / `.dockerignore` change, no `docker-compose.yml` change, no `.env.example` change, no `.gitignore` change, no `configs/caddy/Caddyfile` change, no change to any `scripts/` path.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` deliberately **not** touched — D-073 lands operator-procedure prep; it neither adds nor verifies a runtime invariant. R-6 / R-9 / R-10 / I-3 / I-9 are unaffected (REAL-1.1 will exercise the same invariants the mock harness already validates under `make check`).
- `docs/assumptions.md` / `docs/assumption-audit.md` deliberately **not** touched — no new assumption is opened; no existing assumption is closed.
- `docs/ARCHITECTURE.md`, `docs/product/{PRD,BuildPlan,TechSpec}.md`, `docs/GLOSSARY.md`, `docs/OPERATIONALIZATION-ROADMAP.md`, `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md`, `docs/RENAMING-ROADMAP.md`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `QUICKSTART.md` — also not touched.
- **REAL-1.0 prep is complete; REAL-1.1 operator execution against real OpenAI stays the sole closure step; REAL-1 stays open.**

### Out of scope (per packet boundaries)
- The live run itself, the populated dated evidence artifact, and milestone closure — that is REAL-1.1.
- Any `src/`, schema, migration, `docker-compose.yml`, `Dockerfile`, installer, `.env.example`, `Makefile`, `pyproject.toml`, or `uv.lock` change.
- Any live OpenAI call inside `make check` or any new gated test (the existing `tests/test_chat_client_openai.py` and `tests/test_embedding_client_openai.py` are not touched).
- Any harness extension, new `scripts/` path, new aggregate, or retrieval / answer-path / grading behavior change.
- Any resilience-knob tuning beyond D-047 / D-049 defaults.
- The `RouteKind.ENTRY → NOTE` / `Note` / `community_id` / `DomainRepository` / `memory_rag` renames closed under D-026 / D-042 are not reopened.
- DEPLOY-1.7b — v2 → v3 cross-version upgrade drill against a real previously-installed v2 VPS (sole canonical remaining DEPLOY-1 closure packet per D-067 / D-068).
- Slice 3.4 metadata-filter dimensions (`child_id`, `visibility_scope`).
- Slice 3.7 dual-config tsvector and the unresolved D-038 Postgres baseline capture.
- The previously-checkpointed routing/doc work on `rescue/d072-doc-closure-and-routing-contract` is deferred — D-072 stays parked at its original number on that branch; D-073 does not displace it.
- Multi-run / multi-query / multi-language statistical capture — the milestone is a one-shot value-loop proof, by design.
- Any `make real-*` convenience target (per the DEPLOY-1.2..1.7 precedent of deferring convenience targets).
- A-43 logs-first observability scope work.
- Any edit to `docs/INVARIANTS.md`, `docs/RUNTIME-INVARIANTS.md`, `docs/assumptions.md`, `docs/assumption-audit.md`, `docs/ARCHITECTURE.md`, `docs/product/{PRD,BuildPlan,TechSpec}.md`, `docs/GLOSSARY.md`, `docs/OPERATIONALIZATION-ROADMAP.md`, `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md`, `docs/RENAMING-ROADMAP.md`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `QUICKSTART.md`.

---

## D-074 — Real-answer end-to-end value-loop proof (REAL-1) closure

### Context

REAL-1.0 (D-073) landed the operator procedure and evidence-file template for the real-answer smoke, but did not close REAL-1. The product-baseline gap remained open until one real-backend `/note` → retrieval → grounded-answer round-trip was captured as a populated dated evidence artifact using real Postgres, real OpenAI embeddings, real OpenAI chat, and the Telegram webhook secret contour.

### Decision

Close REAL-1.1 and therefore REAL-1 by recording the populated dated evidence artifact at `docs/real-answer-drill/real-answer-smoke-20260528-evidence.json`.

The run used the canonical real-backend contour: `STORAGE_BACKEND=postgres`, `EMBEDDING_BACKEND=openai`, `EMBEDDING_MODEL=text-embedding-3-large`, `EMBEDDING_DIMENSION=3072`, `CHAT_BACKEND=openai`, `CHAT_MODEL=gpt-4.1`, and a set Telegram webhook secret. The boot gate emitted the expected `app.created ... embedding_backend=openai embedding_dim=3072 chat_backend=openai chat_model=gpt-4.1` line.

The isolated smoke posted one `/note` into a fresh test community, persisted raw source data before enrichment, created one note and three event chunks, wrote three embedding records with `model_name='text-embedding-3-large'` and `dimension=3072`, and observed every chunk at `embedding_status='ready'`. The follow-up `/ask` produced a grounded user-facing answer from the saved note. Retrieval traces recorded dense, sparse, and merged rows; the answer trace recorded `fallback_mode='none'`, `model_name='gpt-4.1'`, `prompt_version='v1'`, non-empty `context_chunk_ids`, positive `latency_ms`, and non-empty token counts.

### Why

REAL-1 exists to prove the already-wired real provider paths produce user-visible value end to end, not only that the offline contracts and mock smokes pass. The populated artifact closes that gap with one bounded, inspectable value-loop run: capture through the Telegram webhook adapter, durable Postgres lineage, OpenAI embedding/indexing, hybrid retrieval, OpenAI grounded answer generation, and persisted traces.

The evidence is intentionally one-shot and operator-deliberate. It does not turn live OpenAI calls into CI, does not add thresholds, and does not broaden the harness. It records the product-baseline proof needed before treating the real-answer path as closed.

### Consequence

- **New:** `docs/real-answer-drill/real-answer-smoke-20260528-evidence.json` — populated REAL-1.1 evidence artifact, derived from the D-073 template with `"_template": true` removed and credential-bearing values redacted.
- **Changed:** `docs/decision-log.md` — this D-074 closure entry.
- **Changed:** `docs/todo.md` — REAL-1 milestone marked complete; REAL-1.1 marked done.
- **Changed:** `docs/execution-map.md` — REAL-1.1 row marked done (D-074) and pointed at the dated evidence artifact.
- REAL-1 is closed by `summary.note_round_trip_green == true`, `summary.ask_round_trip_green == true`, `summary.answer_grounded == true`, and `summary.closes_real_1 == true`.
- No `src/`, schema, migration, script, test, `docker-compose.yml`, `Dockerfile`, `.env`, `Makefile`, `pyproject.toml`, or `uv.lock` change is part of this closure.

### Out of scope

- Any runtime behavior change.
- Any resilience-knob tuning beyond the D-047 / D-049 defaults.
- Any live OpenAI call inside `make check` or any new gated test.
- Any harness extension, quality aggregate, threshold, or CI gate.
- Any schema, migration, retrieval, answer-path, or provider-adapter change.
- DEPLOY-1.7b, D-038, Slice 3.4, Slice 3.7, D-026 rename work, and any multi-run statistical capture.

---

## D-075 — REAL-1 tracking-doc hygiene: collapse duplicate REAL-1 entries left behind after D-074

### Context

D-074 closed REAL-1 by landing the populated dated evidence artifact `docs/real-answer-drill/real-answer-smoke-20260528-evidence.json` and adding closed-state milestone copies in `docs/todo.md` and `docs/execution-map.md`. The pre-existing open-state copies of the same milestone were not removed at the time, so the branch carried two contradictory REAL-1 milestone blocks in `docs/todo.md` (one tagged `— in progress` with REAL-1.1 marked `outstanding`, one tagged `— complete` with REAL-1.1 marked `done (D-074)`) and two REAL-1.1 rows in the `Real-answer e2e proof rollout` table in `docs/execution-map.md` (one row carrying the pre-closure `Operator-dependent. Requires …` description, one row carrying the `**Done (D-074).**` closure description). The REAL-1 milestone is therefore not reviewable as a coherent unit while the tracking docs simultaneously carry both states.

### Decision

Collapse the duplicates by deleting the stale open-state copies and keeping the closed-state entries intact:

- In `docs/todo.md`, delete the `## Real-answer end-to-end value-loop proof (REAL-1) — in progress` block (the heading and its three bullets covering milestone scope, REAL-1.0 prep, and the pre-closure REAL-1.1 outstanding description) together with the trailing blank-line separator. Keep the `## Real-answer end-to-end value-loop proof (REAL-1) — complete` block (heading + milestone scope bullet + REAL-1.0 done (D-073) bullet + REAL-1.1 done (D-074) bullet) byte-for-byte intact at its existing position.
- In `docs/execution-map.md`, delete the stale REAL-1.1 row whose right-hand column begins `Operator-dependent. Requires real \`OPENAI_API_KEY\` …` from the `Real-answer e2e proof rollout` table. Keep the REAL-1.0 (D-073) row and the REAL-1.1 `**Done (D-074).**` row byte-for-byte intact, along with the table header and the section intro.

No other doc, source file, schema, migration, test, script, or build artifact is touched. The REAL-1 evidence artifact `docs/real-answer-drill/real-answer-smoke-20260528-evidence.json` and the REAL-1.0 template `docs/real-answer-drill/real-answer-smoke-TEMPLATE.json` are not edited. The D-073 and D-074 decision-log entries are not edited. `docs/RUNBOOK.md` is not edited. The kept closed-state REAL-1 entries are not reworded.

### Why

The contradiction in the tracking docs is purely an artifact of how D-074 layered its closure copies on top of the pre-existing in-progress copies without removing them. Collapsing the duplicates is the minimum docs-only follow-up needed to leave the milestone documentation self-consistent so the branch becomes reviewable as a coherent unit, without rewording the surviving closed-state entries and without widening into REAL-2, quality expansion, deployment follow-up, or any new live-run work.

### Consequence

- **Changed:** `docs/todo.md` — stale open-state REAL-1 milestone block removed; closed-state block preserved at its existing position.
- **Changed:** `docs/execution-map.md` — stale REAL-1.1 row removed from the `Real-answer e2e proof rollout` table; REAL-1.0 (D-073) and REAL-1.1 (Done, D-074) rows preserved.
- **Changed:** `docs/decision-log.md` — this D-075 entry.
- REAL-1 closure flags from D-074 (`summary.note_round_trip_green`, `summary.ask_round_trip_green`, `summary.answer_grounded`, `summary.closes_real_1`) remain green on the unchanged evidence artifact `docs/real-answer-drill/real-answer-smoke-20260528-evidence.json`.
- No `src/`, schema, migration, script, test, `docker-compose.yml`, `Dockerfile`, `.env.example`, `Makefile`, `pyproject.toml`, or `uv.lock` change is part of this cleanup.

### Out of scope

- Any `src/`, schema, migration, test, script, `docker-compose.yml`, `Dockerfile`, `Makefile`, `pyproject.toml`, `uv.lock`, `QUICKSTART.md`, `README.md`, `AGENTS.md`, `CLAUDE.md`, `docs/RUNBOOK.md`, `docs/INVARIANTS.md`, `docs/RUNTIME-INVARIANTS.md`, `docs/assumptions.md`, `docs/assumption-audit.md`, `docs/ARCHITECTURE.md`, `docs/product/*`, `docs/GLOSSARY.md`, `docs/OPERATIONALIZATION-ROADMAP.md`, `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md`, or `docs/RENAMING-ROADMAP.md` change.
- Any edit to `docs/real-answer-drill/real-answer-smoke-20260528-evidence.json` or `docs/real-answer-drill/real-answer-smoke-TEMPLATE.json`.
- Any rewording of the kept closed-state REAL-1 entries in `docs/todo.md` or `docs/execution-map.md` beyond the minimum needed to remove duplication.
- Any widening into REAL-2, quality expansion, deployment follow-up, DEPLOY-1.7b operator drill, D-072 routing-contract rescue, D-038 baseline measurement, Slice 3.4 / 3.7 work, D-026 rename work, or new live-run work.
- Any live OpenAI call, `make check` dependency, or new gated test.

---

## D-076 — DEPLOY-1 closure prep: post-REAL-1 evidence-file template + RUNBOOK closure procedure + DEPLOY-1.7b re-scoped into DEPLOY-2 prep

### Context

REAL-1.1 closed on 2026-05-28 (D-074) with the populated dated evidence at `docs/real-answer-drill/real-answer-smoke-20260528-evidence.json`. DEPLOY-1.7a (D-067) closed the clean-VPS pilot smoke + off-box backup §2-invariant verification halves; DEPLOY-1.7-preflight (D-066) de-risked the configuration-versioning seam locally; DEPLOY-1.7b operator-procedure prep (D-068) committed `docs/deploy1-drill/deploy1-cross-version-drill-TEMPLATE.json` and a RUNBOOK subsection but the operator drill is blocked on a real previously-installed v2 VPS that does not exist and that the development environment cannot synthesize. DEPLOY-1's §6 exit criterion (in `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` before this packet) still named the v2 → v3 cross-version drill as a closure requirement, so DEPLOY-1 could not close on the existing v3 contour even though that contour is now provably end-to-end green (DEPLOY-1.7a + REAL-1.1). A-43 (logs-first observability scope, open since D-060) had also been deferred packet-by-packet by every DEPLOY-1.x packet and blocked DEPLOY-1 closure in spirit even though no DEPLOY-1.x packet had committed a specific observability surface.

### Decision

Land the **docs-first closure-prep** for DEPLOY-1 — the operator procedure + committed evidence-file template — ahead of the operator-run drill, and **re-scope DEPLOY-1.7b out of DEPLOY-1 into DEPLOY-2 prep** so DEPLOY-1's §6 exit criterion no longer depends on a real previously-installed v2 VPS. Operates within DEPLOY-1 invariants — A-22 updated by D-060. Mirrors the D-068 (DEPLOY-1.7b prep) and D-073 (REAL-1.0 prep) precedent shape: a narrowly-scoped prep packet that pins the artifact shape + procedure + cross-doc registration now, isolating the operator-dependent live-run capture into a single subsequent action.

D-076 mirrors the D-068 / D-073 precedent shape: a narrowly-scoped prep packet that lands the artifact shape + procedure + cross-doc registration now, isolating the operator-dependent live capture into a single subsequent step. The motivation is the same as D-073 — the live capture cannot be authored autonomously without the operator running it against the deployed VPS contour, but the artifact *shape*, the *procedure*, and the *cross-doc registration* can, and pinning those first is the smallest autonomous step that materially advances DEPLOY-1 closure without widening scope.

DEPLOY-1.7b re-scope rationale: moving DEPLOY-1.7b's cross-version concern into DEPLOY-2 prep (where v2 → v3 → v4 cross-version migration is a natural follow-up concern alongside the managed-cloud peer shape) lets DEPLOY-1 close on the existing v3 contour without losing the docs-first prep work D-068 already landed. The committed template at `docs/deploy1-drill/deploy1-cross-version-drill-TEMPLATE.json` and the "v2 → v3 cross-version upgrade drill (DEPLOY-1.7b / D-068)" subsection in `docs/RUNBOOK.md` are **retained verbatim** and are now DEPLOY-2 prep assets — not DEPLOY-1 closure dependencies.

D-076 lands via:

- The new committed evidence-file template at `docs/deploy1-drill/deploy1-closure-post-real1-TEMPLATE.json` carrying a top-level `"_template": true` flag so it cannot be misread as real evidence, six top-level branches (`metadata`, `installer_state`, `live_probes`, `post_real1_round_trip`, `summary`, `out_of_scope_for_this_packet`), and the dual placeholder convention established by D-067 / D-068 / D-073 — `<REDACTED>` for credential-bearing values and `<TO_FILL_BY_OPERATOR>` for outcomes the operator captures from the real contour. Stable values are pre-filled (`installer_state.installer_config_version: 3`, `selected_defaults.{reverse_proxy: "caddy", installer_impl: "bash", backup_tool: "rclone"}`, `last_outcome: "success"`; the `pg_backup.cycle.ok` / `pg_backup.offbox.{begin,ok}` log-line shapes; the `telegram.webhook update_id=<id> route=<route> ...` shape; the expected `answer_traces` row contract `fallback_mode='none'`, `model_name='gpt-4.1'`, `prompt_version='v1'`, non-empty `context_chunk_ids`, positive `latency_ms`, non-empty `token_counts`; the `provider.attempt label=openai_embedding|openai_chat` line shapes). The `live_probes.retrieval_hybrid.line_shape` and `live_probes.answer_path.line_shape` fields are left `<TO_FILL_BY_OPERATOR>` so the operator records the verbatim shape the deployed `src/memory_rag/services/retrieval.py` / `services/query_service.py` / `services/dispatcher.py` already emit — D-076 introduces no new logging contract.
- The new `docs/RUNBOOK.md` "DEPLOY-1 closure procedure (post-REAL-1) (D-076)" subsection at `###` level, placed at the end of the existing "Self-hosted VPS reference shape (DEPLOY-1 / D-060)" section (after the DEPLOY-1.7b / D-068 subsection) so it reads as the explicit closure step. Names operator pre-conditions (the deployed v3 VPS contour from DEPLOY-1.7a is up; `.env` populated per DEPLOY-1.4 / 1.5 / 1.6 plus the canonical REAL-1 env knobs); the numbered run procedure (snapshot `.installer-state.json` → capture verbatim `pg_backup.*` lines → capture one verbatim Caddy access line → `/note` round-trip + capture verbatim `telegram.webhook` line → `/ask` round-trip + capture verbatim `retrieval.hybrid` and `answer.*` lines + `answer_traces` row + `provider.attempt` lines → assemble the dated artifact → run the redaction grep checklist); the evidence-file shape (six top-level branches); the mandatory redaction rule with a pre-commit grep checklist covering `$PUBLIC_HOSTNAME`, `$BACKUP_S3_*`, `$TELEGRAM_BOT_TOKEN`, `$TELEGRAM_WEBHOOK_SECRET`, `$OPENAI_API_KEY`; the closure signal (a populated dated `docs/deploy1-drill/deploy1-closure-post-real1-<YYYYMMDD>-evidence.json` with all four summary booleans `true`); and an explicit `make check` non-impact note (no live OpenAI in CI; no new gated test).
- `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` §1 status paragraph extended; §4 packet table DEPLOY-1.7b row flipped to "Re-scoped to DEPLOY-2 prep (D-076)" with its committed template + RUNBOOK subsection retained verbatim; one new "DEPLOY-1 closure prep (post-REAL-1)" row appended; §5 dependency paragraph and diagram updated to show DEPLOY-1.7a → REAL-1 → DEPLOY-1 closure prep as the actual closure path and DEPLOY-1.7b branching off to DEPLOY-2 prep; **§6 exit criterion rewritten** to drop the v2 → v3 cross-version upgrade drill leg and replace it with the post-REAL-1 closure-procedure evidence formulation; §7 See also bullet refined to record A-43 closed by D-077.
- `docs/execution-map.md` "Deployment-shape rollout" table: DEPLOY-1.7b row updated to mark it as moved-to-DEPLOY-2-prep (template + RUNBOOK subsection retained); two new rows appended — "DEPLOY-1 closure prep (post-REAL-1)" → D-076 and "A-43 logs-first observability pin" → D-077.
- `docs/todo.md` DEPLOY-1 milestone block: DEPLOY-1.7b bullet flipped from "operator-procedure prep landed (D-068); operator drill outstanding" to "re-scoped to DEPLOY-2 prep (D-076)"; two new bullets added — DEPLOY-1 closure prep done (D-076), A-43 closed by D-077.

The closure of DEPLOY-1 remains a future, operator-dependent step. The committed template plus the RUNBOOK subsection mean that when the operator runs the documented procedure against the deployed v3 contour, the only remaining work is to commit the populated dated evidence artifact.

### Why

DEPLOY-1.7a (D-067) already closed the clean-VPS pilot smoke + off-box backup §2-invariant; DEPLOY-1.7-preflight (D-066) already de-risked the configuration-versioning seam locally; REAL-1.1 (D-074) already produced the real-backend `/note` → `/ask` round-trip evidence against the deployed contour. The only thing left blocking DEPLOY-1 closure on the previous §6 exit criterion was the v2 → v3 cross-version drill against a real previously-installed v2 VPS that the development environment cannot synthesize. Re-scoping DEPLOY-1.7b into DEPLOY-2 prep — where v2 → v3 → v4 cross-version migration is a natural follow-up alongside the managed-cloud peer shape — lets DEPLOY-1 close on the existing v3 contour without losing the docs-first prep work D-068 already landed.

A single-packet "land the operator drill + populated dated artifact" approach would be the DEPLOY-1.7a precedent (D-067), but the closure drill cannot be authored autonomously: it depends on an operator running it against the deployed VPS contour with real credentials. The D-068 / D-073 precedent already shows the canonical split for this constraint: prep packet first (procedure + committed template + cross-doc registration), live-capture packet second. D-076 takes that shape for DEPLOY-1 closure.

Committing the evidence-file template explicitly (with `"_template": true`, `<TO_FILL_BY_OPERATOR>` placeholders, and the operator-copy instruction in `metadata.notes`) — rather than leaving it implicit in the RUNBOOK subsection — eliminates the risk of the closure drill landing an artifact whose shape drifts from the documented contract. The future dated artifact is mechanically derived by copying + filling the committed template.

The six-branch artifact shape (`metadata`, `installer_state`, `live_probes`, `post_real1_round_trip`, `summary`, `out_of_scope_for_this_packet`) is the minimum that proves DEPLOY-1 closure end-to-end: `installer_state` records the deployed contour shape (the v3 `.installer-state.json` from DEPLOY-1.6); `live_probes` records that the A-43-pinned existing log families (`pg_backup.*`, Caddy access, `telegram.webhook`, `retrieval.hybrid`, `answer.*`) are emitting as expected against the deployed contour; `post_real1_round_trip` records that the real-backend `/note` → `/ask` envelope still passes against the deployed contour (structurally identical to REAL-1.1's evidence so the two artifacts are directly comparable); `summary` records the four closure booleans. The §6 exit criterion is satisfied when those four booleans are all `true`. **Reuse-only**: D-076 introduces no new resilience knob, no new aggregate, no new harness code, no new logging contract in `src/`, and no behavioral change.

### Consequence

- **New:** `docs/deploy1-drill/deploy1-closure-post-real1-TEMPLATE.json` — committed evidence-file template carrying `"_template": true`, six top-level branches (`metadata`, `installer_state`, `live_probes`, `post_real1_round_trip`, `summary`, `out_of_scope_for_this_packet`), the dual placeholder convention (`<REDACTED>` for credential-bearing values; `<TO_FILL_BY_OPERATOR>` for outcomes the operator captures), and stable pre-filled values (`installer_state.installer_config_version=3`; `selected_defaults.{reverse_proxy="caddy", installer_impl="bash", backup_tool="rclone"}`; structural log-line shapes for `pg_backup.cycle.ok` / `pg_backup.offbox.{begin,ok}` / `telegram.webhook` / `provider.attempt`; the expected `answer_traces` row contract). The dated working artifact (`docs/deploy1-drill/deploy1-closure-post-real1-<YYYYMMDD>-evidence.json`) is the future operator-execution packet's output, not D-076's.
- **Changed:** `docs/RUNBOOK.md` — new "DEPLOY-1 closure procedure (post-REAL-1) (D-076)" subsection at `###` level, placed at the end of the existing "Self-hosted VPS reference shape (DEPLOY-1 / D-060)" section (after the DEPLOY-1.7b / D-068 subsection). Names operator pre-conditions, the numbered run procedure, the evidence-file shape, the explicit redaction rule (with a pre-commit grep checklist), the closure signal, and the `make check` non-impact note. No edits to the existing DEPLOY-1.2..1.7b subsections.
- **Changed:** `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` — §1 status paragraph extended with the D-076 prep-landing sentence and the DEPLOY-1.7b re-scope sentence; §4 packet table DEPLOY-1.7b row flipped to "Re-scoped to DEPLOY-2 prep (D-076)" with its committed template + RUNBOOK subsection retained verbatim; one new "DEPLOY-1 closure prep (post-REAL-1)" row appended; §5 dependency paragraph and diagram updated to show DEPLOY-1.7a → REAL-1 → DEPLOY-1 closure prep as the actual closure path and DEPLOY-1.7b branching off to DEPLOY-2 prep; **§6 exit criterion rewritten** to drop the v2 → v3 cross-version upgrade drill leg and replace it with the post-REAL-1 closure-procedure evidence formulation; §7 See also bullet refined to record A-43 closed by D-077.
- **Changed:** `docs/execution-map.md` — DEPLOY-1.7b row updated to mark it as moved-to-DEPLOY-2-prep (template + RUNBOOK subsection retained); two new rows appended — "DEPLOY-1 closure prep (post-REAL-1)" → D-076 and "A-43 logs-first observability pin" → D-077. DEPLOY-2 row extended to record that it inherits DEPLOY-1.7b's retained template + RUNBOOK subsection as DEPLOY-2 prep.
- **Changed:** `docs/todo.md` — DEPLOY-1.7b bullet flipped from "operator-procedure prep landed (D-068); operator drill outstanding" to "re-scoped to DEPLOY-2 prep (D-076)"; two new bullets appended — DEPLOY-1 closure prep done (D-076), A-43 closed by D-077; DEPLOY-2 bullet extended.
- **No `src/` change**, no schema change, no migration change, no `tests/` change, no `pyproject.toml` / `uv.lock` change, no `Makefile` change, no `Dockerfile` / `.dockerignore` change, no `docker-compose.yml` change, no `.env.example` change, no `.gitignore` change, no `configs/caddy/Caddyfile` change, no change to `scripts/installer/deploy.sh`, `scripts/installer/drill_upgrade_local.sh`, `scripts/pg_offbox_uploader/`, `scripts/pg_backup/`, or `scripts/pg_restore/`. No new logging contract in `src/` (A-43 closure with that constraint is D-077's concern; D-076 records existing log-line shapes verbatim, captured-not-invented).
- `docs/deploy1-drill/deploy1-cross-version-drill-TEMPLATE.json`, `docs/deploy1-drill/deploy1-pilot-smoke-20260527-evidence.json`, `docs/deploy1-drill/deploy1-upgrade-drill-20260522-evidence.json`, `docs/real-answer-drill/real-answer-smoke-20260528-evidence.json`, `docs/real-answer-drill/real-answer-smoke-TEMPLATE.json` — all **not edited** (the cross-version template is retained verbatim for DEPLOY-2 use; the three dated evidence artifacts are immutable history).
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` deliberately **not** touched — D-076 lands operator-procedure prep; it neither adds nor verifies a runtime invariant (the §6 exit criterion is a roadmap-level contract, not a runtime invariant). R-6 / R-9 / R-10 / I-3 / I-9 are unaffected.
- `docs/assumptions.md` / `docs/assumption-audit.md` are touched only by the parallel D-077 entry (A-43 closure). D-076 itself opens no new assumption and closes no existing assumption.
- `docs/ARCHITECTURE.md`, `docs/product/{PRD,BuildPlan,TechSpec}.md`, `docs/GLOSSARY.md`, `docs/OPERATIONALIZATION-ROADMAP.md`, `docs/RENAMING-ROADMAP.md`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `QUICKSTART.md` — also not touched.
- **DEPLOY-1 closure prep is complete; the operator drill against the deployed v3 contour stays the sole remaining closure step; DEPLOY-1 stays open. DEPLOY-1.7b is re-scoped into DEPLOY-2 prep and is no longer a DEPLOY-1 closure dependency.**

### Out of scope (per packet boundaries)

- The operator drill itself, the populated dated evidence artifact (`docs/deploy1-drill/deploy1-closure-post-real1-<YYYYMMDD>-evidence.json`), and DEPLOY-1 milestone closure — that is the next packet.
- Any `src/`, schema, migration, `docker-compose.yml`, `Dockerfile`, installer, `.env.example`, `Makefile`, `pyproject.toml`, `uv.lock`, `Caddyfile`, or `tests/` change.
- Any new logging contract in `src/` (A-43 closure with that constraint is the parallel D-077 entry; D-076 records existing log-line shapes verbatim).
- Any DEPLOY-2 work beyond relabeling DEPLOY-1.7b's existing committed assets as DEPLOY-2 prep (no DEPLOY-2 roadmap doc, no managed-cloud architecture, no A-41 reopen — DEPLOY-2 stays deferred).
- Any live OpenAI call inside `make check` or any new gated test (the existing `tests/test_chat_client_openai.py` and `tests/test_embedding_client_openai.py` are not touched).
- Any harness extension, new `scripts/` path, new aggregate, or retrieval / answer-path / grading behavior change.
- Any resilience-knob tuning beyond D-047 / D-049 defaults.
- The `RouteKind.ENTRY → NOTE` / `Note` / `community_id` / `DomainRepository` / `memory_rag` renames closed under D-026 / D-042 are not reopened.
- The DEPLOY-1.7b cross-version drill against a real previously-installed v2 VPS — re-scoped to DEPLOY-2 prep by this packet; the drill itself stays deferred until DEPLOY-2 is pulled.
- Slice 3.4 metadata-filter dimensions (`child_id`, `visibility_scope`).
- Slice 3.7 dual-config tsvector and the unresolved D-038 Postgres baseline capture.
- Multi-run / multi-query / quarterly closure re-capture — single-artifact closure pin per the DEPLOY-1.7a / D-067 precedent.
- Any `make deploy-closure-*` / `make d1-close-*` convenience target (per the DEPLOY-1.2..1.7 precedent of deferring convenience targets).
- The previously-checkpointed routing/doc work on `rescue/d072-doc-closure-and-routing-contract` (D-072 stays parked at its original number).
- The forward seam to remote sinks named by D-060 / D-077 — deliberately deferred to a later observability packet or DEPLOY-2 prep.
- Any edit to `docs/INVARIANTS.md`, `docs/RUNTIME-INVARIANTS.md`, `docs/ARCHITECTURE.md`, `docs/product/{PRD,BuildPlan,TechSpec}.md`, `docs/GLOSSARY.md`, `docs/OPERATIONALIZATION-ROADMAP.md`, `docs/RENAMING-ROADMAP.md`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `QUICKSTART.md`.
- Any edit to `docs/deploy1-drill/deploy1-cross-version-drill-TEMPLATE.json`, `docs/deploy1-drill/deploy1-pilot-smoke-20260527-evidence.json`, `docs/deploy1-drill/deploy1-upgrade-drill-20260522-evidence.json`, `docs/real-answer-drill/real-answer-smoke-20260528-evidence.json`, or `docs/real-answer-drill/real-answer-smoke-TEMPLATE.json`.

---

## D-077 — A-43 logs-first observability pin: existing log-line families only, no new logging contract; A-43 closes

### Context

A-43 (observability scope for the first DEPLOY-1 VPS contour) was opened by D-060 with a logs-first scope and a forward seam to remote sinks, but the specific surface and tooling were left unpinned. Every DEPLOY-1.x packet since (DEPLOY-1.2 / D-061; DEPLOY-1.3 / D-062; DEPLOY-1.4 / D-063; DEPLOY-1.5 / D-064; DEPLOY-1.6 / D-065 — which explicitly declined to fold A-43 in because the off-box sink reused the existing `pg_backup.*` log-prefix family; DEPLOY-1.7-preflight / D-066; DEPLOY-1.7a / D-067; DEPLOY-1.7b prep / D-068) has deferred A-43 to "a later DEPLOY-1.x packet" because no packet needed to force a new logging contract. The DEPLOY-1 closure-prep packet (D-076) is the natural pin point: the closure procedure captures observability evidence against the deployed v3 contour, and the deployed contour already emits — in existing log families — every observability signal DEPLOY-1 closure needs to verify. The DEPLOY-1.7-preflight (D-066), DEPLOY-1.7a (D-067), and REAL-1.1 (D-074) evidence artifacts already capture those same families verbatim.

### Decision

Pin A-43 to a logs-first observability surface consisting **only of the existing log-line families** already emitted by the deployed v3 contour, and **close** A-43 on that pin. Specifically:

- **`pg_backup.*` family** — `pg_backup.cycle.{ok,start,error}`, `pg_backup.offbox.{begin,ok,skipped,error}`, the off-box additivity-smoke surfaces — already emitted by `scripts/pg_backup/scheduler.sh`, `scripts/installer/deploy.sh`, and `scripts/pg_offbox_uploader/uploader.sh`.
- **Caddy access logs** at the reverse-proxy contour established by DEPLOY-1.3 / D-062 — `POST /telegram/webhook 200`, the HTTP → HTTPS redirect transitions, ACME certificate transitions. Already emitted by the `caddy` service.
- **App-side `telegram.webhook update_id=<id> route=<route> route_source=<src> ...`** line family already emitted by `src/memory_rag/adapters/telegram/webhook.py`.
- **App-side `retrieval.hybrid ...`** line family already emitted by `src/memory_rag/services/retrieval.py`.
- **App-side `answer.* ...`** line family already emitted by `src/memory_rag/services/query_service.py` and `src/memory_rag/services/dispatcher.py`.

**No new logging contract is added to `src/`** — the pin is captured-verbatim, not invented. The DEPLOY-1 closure procedure (D-076) records the verbatim line shape and one verbatim line from each family into the evidence artifact's `live_probes` branch; D-077 does not specify the line shape as a contract, it records that the existing shape is the pinned surface.

The forward seam to remote sinks named by D-060 remains deliberately unpinned — D-077 closes A-43's logs-first surface decision but defers the forward-seam pin to a later observability packet or DEPLOY-2 prep.

A-43 moves to "Recently closed" in `docs/assumptions.md` with `→ D-077`. The audit row in `docs/assumption-audit.md` is struck through with `Closed → D-077`. Mirrors the A-22 / A-40 / A-42 closure precedent.

### Why

A-43 was the last open assumption blocking DEPLOY-1 closure even though no DEPLOY-1.x packet needed a new logging contract to do its work. Every DEPLOY-1.x packet's evidence (DEPLOY-1.7-preflight / D-066's drill harness, DEPLOY-1.7a / D-067's pilot-smoke artifact, REAL-1.1 / D-074's smoke artifact) captured the existing log-line families verbatim. The deployed v3 contour already produces every observability signal DEPLOY-1 needs to verify in those existing families. Pinning A-43 to "exactly these existing families; nothing new in `src/`" means:

- A-43 closes without forcing a `src/` change or a new logging contract.
- DEPLOY-1 can close on the existing v3 contour without a separate observability-bolt-on packet.
- The forward seam to remote sinks remains deliberately unpinned and is deferred to a later observability packet or DEPLOY-2 prep.
- DEPLOY-1.7-preflight (D-066), DEPLOY-1.7a (D-067), and REAL-1.1 (D-074) — all of which captured these existing log lines verbatim — count retroactively as the validation for the pin.

The closure mirrors the A-22 / A-40 / A-42 closure precedent: an assumption resolved by a binding decision once the relevant deployment shape's scope is sufficient. D-060 named the logs-first scope but left the specific surface open as an A-43 assumption because no packet at that time committed to a specific surface; D-077 closes that assumption now that the deployed contour's emitted families are sufficient for DEPLOY-1's closure procedure (D-076) to verify the observability shape end-to-end.

The "no new logging contract in `src/`" constraint is what makes this pin a docs-only decision rather than an implementation packet. Any future packet that wants to add a new logging contract (a structured-logging library, a new line family, a metrics surface) revises the pin in a follow-up decision; until then, the pin holds.

### Consequence

- **Changed:** `docs/assumptions.md` — A-43 entry moved out of the "DEPLOY-1 self-hosted reference shape (opened by D-060)" block (replaced with the pointer `*A-43 → D-077.*`); a new bullet added to "Recently closed" recording the pin to the existing log families and the deferred forward seam.
- **Changed:** `docs/assumption-audit.md` — A-43 row struck through (`~~A-43~~`); middle three columns zeroed (`—`); "Due by" cell closed with `Closed → D-077`. Mirrors the A-22 / A-40 / A-42 strikethrough precedent.
- **Changed:** `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` — §7 "See also" A-43 bullet refined to record A-43 closed by D-077 (also touched by the parallel D-076 entry).
- **Changed:** `docs/execution-map.md` — "A-43 logs-first observability pin" row appended to the "Deployment-shape rollout" table (also touched by the parallel D-076 entry).
- **Changed:** `docs/todo.md` — A-43 closure bullet added to the DEPLOY-1 milestone block (also touched by the parallel D-076 entry).
- `docs/RUNBOOK.md` is touched only by D-076's new closure-procedure subsection (which cites the same A-43-pinned families). D-077 does not edit any existing RUNBOOK subsection.
- **No `src/` change.** **No new logging contract** in any source file. No schema / migration / `scripts/` / `docker-compose.yml` / `Caddyfile` / `tests/` / `Dockerfile` / `Makefile` / `pyproject.toml` / `uv.lock` / `.env.example` / `.gitignore` / `.dockerignore` change.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` deliberately **not** touched — A-43 closure does not add or verify a runtime invariant.
- `docs/ARCHITECTURE.md`, `docs/product/{PRD,BuildPlan,TechSpec}.md`, `docs/GLOSSARY.md`, `docs/OPERATIONALIZATION-ROADMAP.md`, `docs/RENAMING-ROADMAP.md`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `QUICKSTART.md` — also not touched.
- **A-43 closes. DEPLOY-1's observability scope is now pinned to the existing log families with no new logging contract in `src/`.**

### Out of scope (per packet boundaries)

- Adding any new log line / new line family / new logging contract / log format in `src/` (the pin is explicitly captured-verbatim, not specified as a contract).
- Pinning the forward seam to remote sinks (deliberately deferred to a later observability packet or DEPLOY-2 prep).
- Any structured-logging library choice (no library is named or required).
- Any log-retention policy (operator concern, deferred).
- Any metrics or tracing surface (the pin is logs-first, by D-060's scope).
- Any `src/`, schema, migration, scripts, `docker-compose.yml`, `Caddyfile`, `tests/`, `Dockerfile`, `Makefile`, `pyproject.toml`, `uv.lock`, `.env.example`, `.gitignore`, or `.dockerignore` change.
- Any `make observability-*` convenience target.
- Quarterly re-pin or re-decide (the pin holds until a future observability packet revises it).
- The DEPLOY-1.7b cross-version drill (re-scoped to DEPLOY-2 prep by the parallel D-076 entry).
- The closure procedure operator drill (D-076's evidence-capture step).
- Managed-cloud reference deployment (DEPLOY-2 reopens A-41 when pulled).
- D-026 / D-042 rename reopens; Slice 3.4 / 3.7 work; D-038 baseline capture; D-072 routing-contract rescue.

---

## D-078 — Retire heuristic plain-text auto-routing to NOTE/ASK; command-less plain text routes only to the draft floor (docs-first; classifier code change deferred)

### Context

D-020 (Slice 1.4) shipped deterministic heuristic plain-text routing into three routes — then-named ENTRY (first non-empty line a valid ISO `YYYY-MM-DD` date with at least one event line), ASK (terminal `?` or an interrogative/imperative first token), and CLARIFY otherwise — with a user-facing marker and a CLARIFY reply naming both commands. D-027 then committed drafts as the unconditional safety floor, and D-028 enforced that floor in code: `core.routing.classifier.classify_plain_text` began routing "everything else" to `RouteKind.DRAFT` (reason `draft_floor_no_signal`) and the plain-text CLARIFY branch went dormant (no plain-text path emits CLARIFY). D-028 **deliberately kept** the two high-confidence heuristics layered on top of the draft floor — the first-line-ISO-date→NOTE auto-route (`first_line_iso_date_with_events`) and the question-shape→ASK auto-route (`question_mark_terminator`, `interrogative_or_imperative_first_token`).

Subsequent packets repeatedly flagged that surviving auto-route as misaligned with the drafts-vs-notes product contract and slated it for "separate cleanup": D-070's R-13 narrative, the RUNBOOK §"Command surface" scope note (which states the legacy plain-text NOTE auto-route "is misaligned with the drafts-vs-notes product contract and is slated for separate cleanup in a future milestone (not closed by D-070)"), and the TechSpec §"Convenience routing" paragraph. The drafts-vs-notes contract is load-bearing: a draft is stored raw but never parsed, chunked, embedded, indexed, or retrievable, whereas a NOTE runs the full ingestion pipeline. A surviving auto-route can therefore silently upgrade a casual dated line into a fully-indexed, retrievable NOTE the user never asked to commit. D-078 is that cleanup, recorded as the docs contract.

### Decision

Retire the heuristic auto-routing of command-less plain text to NOTE and to ASK. Command-less plain text routes **only** to the draft floor (`RouteKind.DRAFT`, reason `draft_floor_no_signal`; D-027 / D-028 / R-13). The two heuristics retired are: (a) NOTE when the first non-empty line is a canonical `YYYY-MM-DD` date with at least one event line; (b) ASK on a terminal `?` or an interrogative/imperative first token. After D-078 the only ways to reach NOTE or ASK are the explicit `/note` and `/ask` commands. `core/domain/parser.parse_note` keeps its strict canonical-ISO contract unchanged — D-078 retires the auto-route that consumed the parser, not the parser. CLARIFY is unchanged: it is not a plain-text route (dormant since D-028) and survives only as an explicit-command active-conflict reply shape.

**Narrow supersession.** D-078 supersedes **only the heuristic plain-text NOTE/ASK routing portions** of D-020 and D-028 — not those entries wholesale. The parts that survive unchanged: the draft floor itself (D-027 / D-028), the `RouteKind.DRAFT` value and `draft_floor_no_signal` reason, the `core.routing.lifecycle_for` mapping, the `SourceMessage.detected_route` lifecycle carrier (D-028), and the dormant-CLARIFY / CLARIFY-as-explicit-command-conflict-reply framing (D-020 / D-028).

**Docs-first; code deferred.** This is the docs/contract packet of a multi-packet correction on the `feat/stage1-capture-routing-baseline-correction` branch. The live classifier in `src/memory_rag/core/routing/classifier.py` **still auto-routes** high-confidence plain-text NOTE/ASK until a **separate later code packet** collapses those branches into the draft floor and updates the routing tests. D-078 records the target contract only; no `src/` or `tests/` change lands here, and no doc in this packet claims the runtime already routes draft-only. The companion `/note`-without-explicit-date→"today" default is a **distinct later packet**, explicitly deferred and not designed here.

D-072 stays parked on the sibling `rescue/d072-doc-closure-and-routing-contract` branch (its checkpoint commit message reads *"preserve D-072 routing/doc work before baseline reprioritization"*) and is not reused; this entry takes the next free number D-078, so the rescue work can land later at its original number without renumbering.

### Why

The draft floor already guarantees no inbound message is lost (D-027 / R-13), so the surviving NOTE/ASK auto-route adds no safety — it only adds surprise: a dated line or a question-shaped sentence is silently committed as a fully-indexed NOTE or run as an ASK the user never explicitly requested, which conflicts with the drafts-vs-notes contract and with the I-14 spirit that absence of an explicit command never silently changes the persistence outcome. Removing the auto-route loses no data-safety and makes the command surface predictable: explicit `/note` / `/ask` for note/query lifecycles, draft for everything else. The cleanup was already named as pending by D-070, the RUNBOOK scope note, and TechSpec §"Convenience routing"; D-078 records the contract so the later classifier code packet has a spec to conform to.

### Consequence

- **Changed:** `docs/assumptions.md` — the `*A-16 → D-020. A-17 → D-020.*` Routing & UX pointer and the two "Recently closed" A-16 / A-17 lines annotated that the heuristic plain-text NOTE/ASK routing portion is superseded by D-078 (the `→ D-020` closure attribution is retained — the assumptions were genuinely closed by D-020; D-078 reverses only the routing behavior). The A-28 entry annotated that its only auto-route consumer is retired by D-078; A-28 stays **open** as the A-12 date-parsing-scope precursor, with `/note`-without-date→today as its deferred companion.
- **Changed:** `docs/assumption-audit.md` — A-16 and A-17 rows struck through (`Closed → D-020; heuristic plain-text NOTE/ASK routing retired → D-078`), which also reconciles a standing inconsistency (assumptions.md listed them closed while the audit rows were still open). A-28 row stays open with a parenthetical noting the D-078 consumer retirement and deferred `/note`-today.
- **Changed:** `docs/INVARIANTS.md` — I-14 reworded (adds "or upgrade"; states drafts are the only command-less route per D-078; heuristics do not auto-route plain text to NOTE/ASK; classifier enforcement lands in a later packet of this milestone).
- **Changed:** `docs/RUNTIME-INVARIANTS.md` — R-11 and R-13 reworded so command-less plain text resolves only to the draft floor (heuristics no longer auto-route it to NOTE/ASK; D-078), each carrying the "classifier code change enforces this in a later packet" clause so the invariant reads as the recorded target rather than a claim the code already complies.
- **Changed:** `docs/ARCHITECTURE.md` — the target-control-surface "No command → draft" line narrowed (the "Heuristics MAY suggest a stronger route (note or ask)" allowance retired; NOTE/ASK reachable only via explicit commands; D-078) and the lifecycle-rules clarification-path clause reworded.
- **Changed:** `docs/product/PRD.md` — §6 in-scope bullet corrected (command-less plain text persists as a draft; no heuristic auto-routing to note/ask; D-027 / D-028 / D-078).
- **Changed:** `docs/product/TechSpec.md` — §"Convenience routing" corrected (command-less plain text routes only to the draft floor; the high-confidence NOTE/ASK heuristics kept by D-028 are retired by D-078; classifier code change pending). §"Safety rule" and §"Lifecycle representation" untouched.
- **Changed:** `QUICKSTART.md` — a forward-looking note added to the "Heuristic plain-text routing" section recording the D-078 target draft-only contract; the example payloads and `# → text:` outputs are **unchanged** because they show current live behavior until the classifier code packet.
- **Changed:** `docs/RUNBOOK.md` — §"Command surface" routing description keeps the accurate current behavior and adds the D-078 target-contract note; the D-070 scope note updated to record that D-078 is the contract that retires the auto-route (classifier code change + `/note`-without-date→today deferred to later packets). Header citation extended to include D-078.
- **Changed:** `docs/execution-map.md` — slice 1.4 row annotated that the heuristic plain-text NOTE/ASK auto-route is later retired by D-078; new "Stage-1 capture/routing baseline correction" section added.
- **Changed:** `docs/todo.md` — new "Stage-1 capture/routing baseline correction" milestone block near the top.
- **No `src/`, `tests/`, schema, migration, `docker-compose.yml`, `Caddyfile`, `Makefile`, `pyproject.toml`, `uv.lock`, `.env.example`, `.gitignore`, or `.dockerignore` change.** The live classifier behavior is unchanged.
- **`README.md` not touched** — it carries no routing-behavior assertion.
- **D-078 does touch `docs/INVARIANTS.md` and `docs/RUNTIME-INVARIANTS.md`** (unlike D-073 / D-077), because the routing contract is an invariant-level statement.
- **The historical D-020 and D-028 entries are not edited** — they are immutable records (D-020 in pre-rename vocabulary); D-078 supersedes their routing portions by reference only.

### Out of scope (per packet boundaries)

- The `classify_plain_text` code change collapsing the NOTE/ASK branches into the draft floor, and its test updates (`tests/test_routing_classifier.py`, dispatcher / end-to-end tests) — the next code packet in this milestone.
- The `/note`-without-explicit-date → "today" default (a distinct later packet; A-12 / A-28-adjacent).
- Any change to `parse_note` / `_parse_iso_date` / `normalize_iso_date_token` strictness (byte-for-byte preserved).
- Removing CLARIFY from the dispatcher (it survives for explicit-command active-conflict).
- Closing A-28 (it concerns `parse_note` strictness, which is unchanged here).
- D-072 routing-contract rescue (stays parked on its sibling branch at its original number).
- Author-name display, group-use, multi-diary; D-026 / D-042 rename reopens; Slice 3.4 / 3.7 work; D-038 baseline capture; A-43 forward-seam follow-ups.

## D-079 — Enforce D-078 in code: collapse the heuristic plain-text NOTE/ASK branches into the draft floor

### Context

D-078 recorded the routing-contract correction (command-less plain text routes only to the draft floor; NOTE/ASK reached only via explicit `/note` / `/ask`) but was a docs-only packet: it explicitly deferred the classifier code change to "a separate later code packet" of the Stage-1 capture/routing baseline correction, and the live classifier in `src/memory_rag/core/routing/classifier.py` kept auto-routing high-confidence plain-text NOTE (first non-empty line a canonical `YYYY-MM-DD` date with ≥1 event line) and ASK (terminal `?` or interrogative/imperative first token). This is Packet 2 — the code change that brings the runtime into compliance with D-078.

### Decision

Collapse the two heuristic branches in `classify_plain_text` so command-less plain text resolves only to `RouteKind.DRAFT` (reason `draft_floor_no_signal`); the defensive empty→`CLARIFY` branch (`empty_after_strip`) is unchanged. The now-unused `parse_note` import and the `_QUESTION_WORDS` / `_TRAILING_PUNCT` constants are removed from the classifier module. Because heuristic-routed NOTE/ASK is now an impossible runtime state (NOTE/ASK arrive only from explicit commands, `route_source == "command"`), the dispatcher's dead machinery for that state is removed: the `is_heuristic` local, the `if not is_heuristic:` `/note` normalize-gate (normalization now runs on every NOTE), the `_HEURISTIC_MARKER_NOTE` / `_HEURISTIC_MARKER_ASK` constants and their appends, and the now-unused `_append_marker` helper. The webhook still tags classifier output `route_source="heuristic"`, so a command-less plain-text DRAFT is still recorded as heuristic-sourced (R-11 provenance unchanged).

`core/domain/parser.parse_note` and the ISO-date strictness helpers are unchanged (A-28 stays **open**; the `/note`-without-explicit-date → "today" companion remains a distinct deferred packet, D-078 §Out-of-scope). CLARIFY is unchanged (defensive empty branch + explicit-command active-conflict reply shape).

### Why

D-078 fixed the contract on paper; until the classifier matched it, the documented invariants I-14 / R-11 / R-13 still read "enforcement lands in a later packet" and the live runtime still silently upgraded casual dated lines / questions into committed notes and queries. This packet closes that invariant-vs-code divergence before the branch is considered for PR. Removing the dispatcher markers and the normalize-gate is not opportunistic cleanup: those branches are reachable only by a heuristic NOTE/ASK route that can no longer occur, so keeping them would be dead code asserting an impossible state.

### Consequence

- **Changed:** `src/memory_rag/core/routing/classifier.py` — `classify_plain_text` returns only DRAFT / CLARIFY; module docstring rewritten; `parse_note` import, `_QUESTION_WORDS`, `_TRAILING_PUNCT` removed.
- **Changed:** `src/memory_rag/services/dispatcher.py` — `is_heuristic` local, NOTE normalize-gate, both heuristic markers + appends, and `_append_marker` removed; `_normalize_note_first_line` docstring updated. `route_source` metadata recording and the CLARIFY branch are unchanged.
- **Changed:** `tests/test_routing_classifier.py` — the six retired-branch cases flipped to draft-floor assertions and renamed `..._falls_through_to_draft_floor`; docstring updated.
- **Changed:** `tests/test_telegram_dispatch.py` — the dated-text and question-text cases now assert `RouteKind.DRAFT` (still `route_source == "heuristic"`); renamed.
- **Changed:** `tests/test_end_to_end_smoke.py` — the two "...via_heuristic" cases rewritten to draft outcomes; the D-070 `2026/05/09` guardrail repurposed as a positive draft-floor assertion (`test_command_less_dated_plain_text_routes_to_draft_floor`).
- **Removed (impossible-state tests):** `test_dispatcher_appends_heuristic_marker_to_note_reply` and `test_dispatcher_appends_heuristic_marker_to_ask_reply` (`tests/test_telegram_reply.py`); `test_weak_evidence_heuristic_still_appends_route_marker` (`tests/test_dispatcher_retrieval_fallback.py`); `test_dispatch_heuristic_note_route_is_not_normalized` (`tests/test_dispatcher_note_normalization.py`). Each replaced by a short comment recording why. The "no marker" guards on command-NOTE and DRAFT replies and `test_sibling_fallback_wording_unchanged` are kept.
- **Changed:** `QUICKSTART.md` — §"Heuristic plain-text routing" retitled and rewritten to draft-only; all three example outputs now show the `Stored as draft. …` reply (this also corrects a pre-existing stale example that showed CLARIFY for `recipe yesterday`, which the live classifier already routed to DRAFT).
- **Changed:** `docs/RUNBOOK.md` — §"Command surface" and the D-070 §"`/note` first-line date" scope note moved to past tense (the heuristic auto-routes are retired by D-079, not "still applied").
- **Changed:** `docs/INVARIANTS.md` (I-14) and `docs/RUNTIME-INVARIANTS.md` (R-11, R-13) — only the trailing "enforcement lands in a later packet" deferral clause replaced with past-tense enforcement (D-079); the invariant statements themselves are unchanged.
- **Changed:** `docs/todo.md` — Packet 2 marked done (D-079); Packet 3 stays pending.
- **Changed:** `docs/execution-map.md` — Stage-1 section marks Packet 2 done; slice 1.4 parenthetical updated to note D-079 enforced the retirement in code.
- **No schema, migration, `docker-compose.yml`, `Caddyfile`, `Makefile`, `pyproject.toml`, `uv.lock`, or `.env.example` change.** `detected_route` already admits `draft` (D-028).

### Out of scope (per packet boundaries)

- Packet 3: `/note` without an explicit first-line date → "today" (A-12 / A-28-adjacent).
- Any `parse_note` / date-parsing strictness change or A-28 closure.
- Any reopening of the draft floor or `core.routing.lifecycle_for` mapping beyond enforcing D-078.
- D-072 routing-contract rescue (stays parked on its sibling branch).
- Author-name display, group-use, multi-diary work.

## D-080 — Reconcile residual "classifier change deferred" doc clauses to D-079 past-tense enforcement (docs-only)

### Context

D-078 recorded the routing-contract correction (command-less plain text routes only to the draft floor; NOTE/ASK reached only via explicit `/note` / `/ask`) as a docs-only packet, and D-079 then enforced it in code — `classify_plain_text` now collapses the heuristic plain-text NOTE/ASK branches into the draft floor. D-079 also flipped the invariant docs to past tense (`INVARIANTS.md` I-14, `RUNTIME-INVARIANTS.md` R-11/R-13) and refreshed `QUICKSTART.md` / `RUNBOOK.md`.

But six product-and-supporting-doc clauses were outside D-079's scope and still asserted that classifier enforcement was *deferred / lands in a later packet*. That left a prose divergence: the invariant files read "D-079 enforces it in code" while these clauses still read "deferred." D-080 is the minimal docs-only reconciliation that removes the last of that invariant-vs-runtime divergence and makes the Stage-1 capture/routing baseline-correction milestone internally consistent. It is a follow-up to D-078 (docs contract) and D-079 (code enforcement); it introduces no new behavior.

### Decision

Flip the residual "classifier code change deferred / lands in a later packet" clauses to truthful past-tense enforcement by D-079, using the wording already established in I-14 / R-11 / R-13 (`D-078 records this contract; D-079 enforces it in code — `classify_plain_text` routes command-less plain text only to the draft floor.`). Docs-only; no `src/`, `tests/`, schema, migration, or config change. The runtime is byte-identical to its post-D-079 state.

### Why

D-078 fixed the contract on paper and D-079 made the code conform, but until these residual clauses were corrected the canonical docs still contradicted both the live runtime and the already-flipped invariant files. Closing this prose gap removes the last documentation inconsistency in the milestone before the branch is considered for PR. Packet 3 (`/note`-without-explicit-date → "today") remains a legitimately deferred companion and is untouched.

### Consequence

- **Changed:** `docs/assumptions.md` — the A-16/A-17 Routing & UX pointer line flipped from "classifier code change deferred to a later packet" to D-079 past-tense enforcement.
- **Changed:** `docs/assumption-audit.md` — the A-16 row tail flipped to `retired → D-078 / enforced in code → D-079`. The A-17 row carries no deferral clause (it concerns CLARIFY surviving only as an explicit-command conflict reply) and is unchanged.
- **Changed:** `docs/product/PRD.md` — both the §5 "Command-less plain text → draft" paragraph and the §6 in-scope bullet flipped to D-079 past-tense enforcement.
- **Changed:** `docs/ARCHITECTURE.md` — the "No command → draft" routing-contract line flipped to D-079 past-tense enforcement.
- **Changed:** `docs/product/TechSpec.md` — the §"Convenience routing" enforcement clause flipped to D-079 past-tense enforcement.
- **Changed:** `docs/todo.md` — new "Packet 2.1 — residual doc-clause reconciliation: done (D-080)" line; Packet 3 stays **pending**.
- **Changed:** `docs/execution-map.md` — new Stage-1 "Packet 2.1" row marking the reconciliation done (D-080); classifier enforcement is now both recorded and enforced consistently across all canonical docs. Packet 3 row unchanged (Pending).
- **The historical D-078 and D-079 entries are not edited** — they are immutable records; D-080 references them by number only.
- **No `src/`, `tests/`, schema, migration, or config change.** A-28 stays **open** (the `/note`-without-explicit-date → "today" companion is Packet 3).

### Out of scope (per packet boundaries)

- Packet 3: `/note` without an explicit first-line date → "today" (A-12 / A-28-adjacent).
- Any `parse_note` / date-parsing strictness change or A-28 closure.
- Any rewrite of D-078's historical record beyond the existing D-079/D-080 references.
- Any `src/`, `tests/`, schema, or migration change.
- D-072 routing-contract rescue (stays parked on its sibling branch).
- Author-name display, group-use, multi-diary work.

## D-081 — Author display-name contract: opaque-ID → display-name seam + initial `/sources` surface (docs-only)

### Context

Authorship is already persisted via the opaque `author_user_id`, mandatory at `SourceMessage`, `Note`, and `EventChunk` (I-6; foundational decision D-014) and also carried on `Query` (`docs/product/TechSpec.md` §5). But the repository has **no** documented contract for resolving that opaque core identifier into a human-readable author name, **no** named resolution seam, and **no** sanctioned user-facing surface for author attribution. "Author-name display" has appeared so far only as a deferred forward-seam item in the out-of-scope lists of D-078 / D-079 / D-080 and in `docs/todo.md`. This docs-only packet pins the contract before any adapter, storage, or rendering code lands.

### Decision

`author_user_id` remains the canonical opaque core identifier. The core neither decodes nor renders it; it carries authorship as an opaque value only (I-1, I-6; `docs/ARCHITECTURE.md` "the core receives an already-resolved scope"). Human-readable author display is resolved **only at the Telegram adapter seam**, from host-supplied identity fields, with the fallback chain `username → first_name → opaque short-ID`. Resolved display names are host-supplied and **non-authoritative** (a Telegram user may change or withhold them); they are presentation, not identity, and never replace `author_user_id` in storage, retrieval, scoping, or provenance.

The single sanctioned display surface for this milestone is `/sources` (D-036). Answer-reply (`/ask` reply) author attribution is explicitly deferred to a later named decision/packet and is recorded as a named placeholder in `docs/execution-map.md` and `docs/todo.md`. A-44 records the resolution + fallback assumption. A-15 (visibility scopes) is unchanged: this contract governs who-authored *display*, not who-may-see *visibility*.

This is a docs-only packet — no `src/`, `tests/`, schema, DDL, migration, or config change, and no claim that runtime behavior has changed. The existing invariant surface (I-1 channel boundary + I-6 authorship) already bounds the contract; no new numbered invariant or runtime invariant is added — only a narrow cross-reference to D-081 / A-44 is added to I-6.

### Why

Pinning the contract first keeps the opaque-identifier core boundary (D-026 / D-041) intact while giving the upcoming capture/render packets an unambiguous seam to build against: display resolution is adapter-only, the fallback order is fixed, and the values are explicitly non-authoritative so no later code mistakes a Telegram display name for identity. Naming `/sources` as the sole surface and deferring answer-reply attribution keeps the first milestone narrow and prevents scope creep into group-use / multi-diary work.

### Consequence

- **Changed:** `docs/decision-log.md` — this D-081 entry.
- **Changed:** `docs/assumptions.md` — new open assumption **A-44** (author display-name resolution + fallback; host-supplied / non-authoritative; resolution is adapter-only; A-15 unchanged).
- **Changed:** `docs/assumption-audit.md` — new open **A-44** row (opened by D-081; not closed — capture/render is future work).
- **Changed:** `docs/GLOSSARY.md` — short "author display name" entry: `participant` / `author_user_id` is the canonical opaque identity; display is adapter-resolved and non-authoritative.
- **Changed:** `docs/ARCHITECTURE.md` — Axis 5 (tenant/auth mapping) and the "What belongs to adapters" bullets note author-identity → display-name resolution as a Telegram adapter-seam concern; the core carries only the opaque `author_user_id`.
- **Changed:** `docs/product/TechSpec.md` — §5 authorship note: `author_user_id` is the opaque core identifier; display names are adapter-resolved, not a core field; `/sources` is the sole current display surface.
- **Changed:** `docs/RUNBOOK.md` — the `/sources` (D-036) section gains a forward note that author attribution, when surfaced, is adapter-resolved per D-081 (not asserted as rendered today).
- **Changed:** `docs/INVARIANTS.md` — narrow cross-reference added to I-6 pointing at D-081 / A-44; **no new invariant**.
- **Changed:** `docs/execution-map.md` + `docs/todo.md` — D-081 recorded; deferred `/ask`-reply author attribution recorded as a named placeholder item.
- **No `src/`, `tests/`, schema, migration, or config change.** A-15 stays unchanged; A-44 is opened **open**.

### Out of scope (per packet boundaries)

- Any `src/` or `tests/` change.
- Any schema, DDL, migration, or persistence-shape decision.
- Any implementation of `username` / `first_name` capture or storage.
- Any `/sources` author-rendering implementation.
- Answer-reply (`/ask` reply) author attribution — deferred to a later named decision/packet (placeholder recorded in `docs/execution-map.md` / `docs/todo.md`).
- Group-use enablement, multi-diary / subject-dimension work.
- Any change to Phase-8 visibility / A-15 beyond acknowledging it remains unchanged.
- Any claim that runtime behavior has already changed in code.

## D-082 — Author display-input persistence shape + capture contract (docs-only)

### Context

D-081 pinned the author *resolution* contract: `author_user_id` stays the canonical opaque core identifier; a human-readable author display name is resolved **only at the Telegram adapter seam** from host-supplied identity fields (`username → first_name → opaque short-ID`), host-supplied and non-authoritative; `/sources` (D-036) is the sole sanctioned surface; `/ask`-reply attribution is deferred (A-44). D-081 deliberately left the *persistence* story open: `docs/execution-map.md` records the next author row as "needs a schema/persistence story first", and A-44 stays open pending it. No capture column, snapshot, or storage rule may land until that shape is pinned. This docs-only packet supplies that decision before any adapter, storage, or migration code lands.

### Decision

Adopt **Option 3 (hybrid)**: pin a **minimal snapshot-oriented persistence shape now**, and **defer any adapter-side identity directory/projection to a later group-use milestone**.

The capture contract: when the Telegram adapter ingests a source message it may capture a **point-in-time snapshot** of the host-supplied identity fields `username` and `first_name` alongside the raw message. Those captured inputs are **nullable** (a Telegram user may withhold either), **non-authoritative** (a user may change them at any time; they are presentation, not identity), **adapter/storage-owned**, and exist **only** to feed later adapter-side display resolution per the D-081 / A-44 fallback chain. They never substitute for `author_user_id` in storage, retrieval, scoping, or provenance.

The persistence-shape boundary: these inputs live behind the storage/adapter seam as a snapshot only. They **must never** appear in core domain models, core types, or core function signatures (D-026 / D-041). The core continues to carry authorship as the opaque `author_user_id` alone (I-1, I-6; foundational D-014); this packet adds no core authorship field and no new invariant. The exact storage representation (column name / DDL / migration) is **not** decided here — that is Packet 2.

This is a docs-only packet — no `src/`, `tests/`, schema, DDL, migration, or config change, and no claim that runtime behavior has changed. D-082 is the decision of record created now; Packet 2 (the capture/migration code packet) cites it.

### Why

Pinning the shape before code gives Packet 2 an unambiguous contract: what is captured (`username`, `first_name`), with what properties (nullable, non-authoritative, adapter/storage-owned), and where it may live (behind the storage seam, never the core). Choosing the minimal snapshot and explicitly deferring any identity directory/projection keeps this milestone narrow, preserves the opaque-identifier core boundary (D-026 / D-041), and prevents scope creep into group-use / multi-diary work before that milestone exists.

### Consequence

- **Changed:** `docs/decision-log.md` — this D-082 entry.
- **Changed:** `docs/execution-map.md` — author block gains a D-082 row (snapshot-oriented persistence shape + capture contract, docs-only); the "capture + `/sources` rendering" row's blocker is narrowed from "needs a schema/persistence story first" to "persistence shape pinned by D-082; code capture/migration is a later packet."
- **Changed:** `docs/assumptions.md` — A-44 narrowed (capture/persistence shape pinned by D-082; resolution + `/sources` rendering remain future work). A-44 stays **open**.
- **Changed:** `docs/assumption-audit.md` — A-44 row narrowed the same way; row stays **open**.
- **Changed:** `docs/todo.md` — D-082 recorded under the author-display block; the capture item's blocker narrowed to point at D-082.
- **Changed:** `docs/product/TechSpec.md` — §5 authorship note: a cross-reference that D-082 pins the adapter/storage-owned snapshot capture shape for the host identity fields; the core adds no display field.
- **Changed:** `docs/ARCHITECTURE.md` — Axis 5 + "what belongs to adapters" bullets note that author display-input capture / persistence shape is adapter/storage-owned (D-082); the core carries only the opaque `author_user_id`.
- **Changed:** `docs/GLOSSARY.md` — new "author display input" term: host-supplied `username` / `first_name` snapshotted at the adapter/storage seam, nullable, non-authoritative, never a core field.
- **Changed:** `docs/INVARIANTS.md` — narrow clause added to I-6 (display-input capture/persistence is adapter/storage-owned per D-082); **no new invariant**.
- **No `src/`, `tests/`, schema, DDL, migration, or config change.** A-15 stays unchanged; A-44 stays **open**; capture code + DDL are **Packet 2**.

### Out of scope (per packet boundaries)

- Any `src/`, `tests/`, schema, DDL, migration, or config change — all deferred to Packet 2.
- The exact storage column/representation for the captured snapshot (Packet 2).
- Adapter-side identity directory/projection semantics — deferred to a later group-use milestone (Option 3).
- `/sources` author rendering and any other display-surface implementation.
- Answer-reply (`/ask` reply) author attribution — remains the deferred named placeholder from D-081.
- Group-use enablement, multi-diary / subject-dimension work.
- Any change to Phase-8 visibility / A-15 beyond acknowledging it remains unchanged.
- Any claim that runtime behavior has already changed in code.

## D-083 — Adapter-owned author display-input storage port + side-table seam (docs-only)

### Context

D-081 pinned author display *resolution* (`author_user_id` stays the canonical opaque core identifier; a human-readable display name is resolved **only at the Telegram adapter seam** from host-supplied identity fields, `username → first_name → opaque short-ID`, non-authoritative; `/sources` the sole surface; `/ask`-reply attribution deferred — A-44). D-082 pinned the *persistence shape*: a minimal point-in-time snapshot of host-supplied `username` / `first_name`, nullable, non-authoritative, adapter/storage-owned, for later adapter-side display resolution only — and explicitly deferred "the exact storage representation (column name / DDL / migration)" **and the seam by which that snapshot reaches durable storage** to a later packet.

That seam is a genuine architecture choice. The only existing write path to `source_messages` is fully core-typed: `services/domain_service.py` calls `DomainRepository.get_or_create_source_message(candidate)` where `candidate` is the core `SourceMessage` domain model, and the Telegram adapter never touches storage directly. Routing the snapshot down that path would push host-supplied identity into `InboundMessage` (a core routing type) or `SourceMessage` (a core domain type), violating the opaque-identifier core boundary (D-026 / D-041) and D-082's own prohibition. This packet records the owner-fixed seam decision before any adapter, storage, or migration code lands; it is the decision of record the following code packet cites.

### Decision

Adopt **Option A**: the durable landing for the author display-input snapshot is a **separate, Telegram-adapter-owned side table**, written through an **adapter-owned storage port distinct from the core `DomainRepository`**. The core repository, its signatures, and the core domain/routing types are unchanged.

**Open-source / shared-core rule.** This repository is intended to remain open-source and reusable across different users and adapter/front-end setups. Therefore common/core capabilities (ingestion, retrieval, answering, traces, the domain model, invariants) stay a single shared subsystem reusable across hosts; an adapter-dependent host-identity feature such as display-input capture must remain **adapter-owned** and must not become a core capability (D-026 / D-041). The side table and its port are Telegram-adapter artifacts; host-specific naming is permitted *there*, but the core continues to carry authorship only as the opaque `author_user_id` (I-1, I-6; foundational D-014).

**Keying / idempotency contract (spec level).** Each snapshot row is keyed by the **same message idempotency tuple** the raw message uses — `external_chat_id` + `external_message_id` + `edit_seq` (R-2 / D-023) — carried as **opaque scalars**. The side table references the message by that tuple only; it does **not** import, embed, or depend on any core type. Re-delivery or an edited state (a new `edit_seq`) follows R-2: it must not duplicate or silently mutate a prior snapshot.

**Boundary.** The captured snapshot **must never** appear in `InboundMessage`, `SourceMessage`, any other core type, or any core function signature (including `DomainRepository.get_or_create_source_message`). It reaches durable storage **only** through the adapter-owned port.

**Properties (carried from D-082).** The snapshot stays **nullable** (a user may withhold `username` or `first_name`), **non-authoritative** (host-supplied, may change at any time; presentation, not identity), **host-supplied**, and exists **only** to feed later adapter-side display resolution per the D-081 / A-44 fallback chain. It never substitutes for `author_user_id` in storage, retrieval, scoping, or provenance.

**Migration surface (descriptive only).** The code packet adds a new forward migration — the next file in `src/memory_rag/storage/postgres/migrations/` — creating the adapter-owned side table. The exact table name, column names, DDL, and migration file content are **not** decided here; they belong to that code packet.

This is a docs-only packet — no `src/`, `tests/`, schema, DDL, migration, or config change, and no claim that runtime behavior has changed. A-44 stays **open** (narrowed: the landing seam is now pinned; capture implementation and resolution/`/sources` rendering remain future work).

### Why

Pinning Option A first gives the code packet an unambiguous, settled seam to build against rather than choosing architecture inside a diff. Keeping the snapshot behind a dedicated adapter-owned side table and port — distinct from the core repository and keyed only by opaque scalars — preserves the shared-core / adapter-owned split that the open-source posture depends on, keeps the opaque-identifier core boundary intact (D-026 / D-041), and leaves the later group-use directory/projection milestone free to evolve the adapter side without touching the core. Naming the migration surface only descriptively keeps docs from outrunning code.

### Consequence

- **Changed:** `docs/decision-log.md` — this D-083 entry.
- **Changed:** `docs/assumptions.md` — A-44 narrowed (landing seam pinned by D-083: separate adapter-owned side table + adapter-owned storage port distinct from `DomainRepository`, Option A; capture implementation and resolution/rendering remain future work). A-44 stays **open**.
- **Changed:** `docs/assumption-audit.md` — A-44 row narrowed the same way; row stays **open**.
- **Changed:** `docs/ARCHITECTURE.md` — Axis 5 + "what belongs to adapters" bullets note that the display-input landing is a separate adapter-owned side table written via an adapter-owned storage port distinct from the core `DomainRepository` (D-083).
- **Changed:** `docs/GLOSSARY.md` — "author display input" term: the snapshot lands in a Telegram-adapter-owned side table via an adapter-owned storage port, keyed by the message idempotency tuple, never a core field (D-083).
- **Changed:** `docs/product/TechSpec.md` — §5 authorship note: D-083 pins the adapter-owned landing seam (separate side table + adapter-owned port distinct from `DomainRepository`); the core repository signature is unchanged and the core adds no display field.
- **Changed:** `docs/INVARIANTS.md` — narrow clause added to I-6 (the adapter/storage-owned landing is a separate side table via an adapter-owned port distinct from the core repository; D-083); **no new invariant**.
- **Changed:** `docs/execution-map.md` — author block gains a D-083 row; the capture row's blocker narrowed from "persistence shape pinned by D-082" to "seam pinned by D-083 (adapter-owned side table + port); code capture/migration is the next packet."
- **Changed:** `docs/todo.md` — D-083 recorded under the author-display block; the capture item's blocker narrowed the same way.
- **No `src/`, `tests/`, schema, DDL, migration, or config change.** A-15 stays unchanged; A-44 stays **open**; capture code, the side-table DDL, the forward migration, the adapter-owned-port implementation, and backend parity are the next packet.

### Out of scope (per packet boundaries)

- Any `src/`, `tests/`, schema, DDL, migration, or config change — all deferred to the code packet.
- The exact table name / column names / DDL / migration file contents (code packet).
- Telegram-side `username` / `first_name` capture and the adapter→port wiring (code packet).
- The adapter-owned storage-port implementation and mock / sqlite / postgres parity (code packet).
- `/sources` author rendering and any other display-surface implementation.
- Answer-reply (`/ask` reply) author attribution — remains the deferred named placeholder from D-081.
- Adapter-side identity directory/projection semantics — deferred to a later group-use milestone.
- Group-use enablement, multi-diary / subject-dimension work.
- Any change to Phase-8 visibility / A-15 beyond acknowledging it remains unchanged.
- Any claim that runtime behavior has already changed in code.

## D-084 — Author display-input capture + durable landing (adapter-owned side table & co-located port)

### Context

D-081 / D-082 / D-083 pinned, docs-only, the author display-name contract, the snapshot persistence shape + capture contract, and the adapter-owned landing seam (Option A: a separate Telegram-adapter-owned side table written through an adapter-owned storage port distinct from the core `DomainRepository`, keyed by the message idempotency tuple as opaque scalars). This is the first **code** packet: it makes the Telegram-side display-input snapshot actually land durably across all backends, without crossing the core boundary.

### Decision

Implement the D-083 seam exactly as pinned:

- **Capture.** `TelegramUser` now models the nullable host-supplied `username` / `first_name`. The webhook writes a snapshot **only for source-message-bearing routes** (note/draft lifecycles), reading the values straight from the raw `message.from_` — never via `InboundMessage` or `SourceMessage`. Capture is best-effort: a snapshot-write failure logs `author_display.capture_failed` and never breaks the user's reply (Fallback Rule).
- **Port (owner-fixed topology).** A new adapter-owned `AuthorDisplayInputStore` Protocol (`save_author_display_input` / `get_author_display_input`) is **co-located on the existing per-backend store object**. It is distinct from `DomainRepository`, uses opaque-scalar signatures only, and imports no core type. The combined `TelegramBackendStore` Protocol (adapter layer) lets the webhook build one store and hand it to both the dispatcher and the port; the storage layer never imports the adapter port. `get_author_display_input` is a raw storage read — it returns the stored `(username, first_name)` and carries **no** display-resolution / fallback-chain logic.
- **Side table + migration.** New `author_display_inputs` table (mock dict / SQLite `_DDL` / Postgres forward migration `0004.author-display-inputs.sql`), keyed by composite PRIMARY KEY `(external_chat_id, external_message_id, edit_seq)`, with nullable `username` / `first_name`, no FK, no core-type dependency.
- **Idempotency / edits (R-2).** Re-delivery of the same tuple is a no-op that preserves the original snapshot (`ON CONFLICT DO NOTHING` / `INSERT OR IGNORE` / dict-key guard) — never duplicated, never silently mutated even if a redelivered payload carries different values; an edit (new `edit_seq`) lands a new row.
- **Nulls.** Either field may be `None`, and a **both-null snapshot is still written** — recording the point-in-time "withheld" state uniformly. This is a decision of this packet, not an assumption; no new runtime invariant is enforced for it.

The core `DomainRepository`, `SearchRepository`, `InboundMessage`, `SourceMessage`, and `get_or_create_source_message` are unchanged. A-44 stays **open**: capture + durable landing are now implemented, but resolution and `/sources` rendering remain future work.

### Why

The seam was fully pinned by D-083, so this packet chooses no architecture inside the diff. Keeping the snapshot behind a dedicated adapter-owned port co-located on the store object — keyed only by opaque scalars — preserves the shared-core / adapter-owned split (D-026 / D-041) and the opaque-identifier core boundary (I-1, I-6) while making the display inputs durably available for the later resolution / `/sources` packet. Gating capture on source-message-bearing routes mirrors D-082's "when the adapter ingests a source message," so snapshots key 1:1 with persisted source rows.

### Consequence

- **Added:** `src/memory_rag/adapters/telegram/author_display.py` — `AuthorDisplayInputStore` port + combined `TelegramBackendStore` seam.
- **Added:** `src/memory_rag/storage/postgres/migrations/0004.author-display-inputs.sql` — forward migration for the side table.
- **Changed:** `src/memory_rag/adapters/telegram/models.py` — `TelegramUser` gains nullable `username` / `first_name`.
- **Changed:** `src/memory_rag/adapters/telegram/webhook.py` — shared per-process store singleton, `get_author_display_input_store` dependency, best-effort capture on note/draft routes.
- **Changed:** `src/memory_rag/storage/{mock,sqlite,postgres}/store.py` — co-located port implementation with backend parity.
- **Added:** `tests/test_author_display_capture.py`, `tests/test_author_display_boundary.py`; **Changed:** `tests/test_telegram_models.py`.
- **Changed:** `docs/decision-log.md` (this entry), `docs/assumptions.md` (A-44 status: capture + landing implemented, resolution/`/sources` still open), `docs/execution-map.md` + `docs/todo.md` (capture row → done; rendering still pending).
- A-15 unchanged; A-44 stays **open**.

### Out of scope (per packet boundaries)

- `/sources` author rendering; the adapter-side display-resolution helper (the `username → first_name → short-ID` fallback chain).
- Answer-reply (`/ask` reply) author attribution — remains the deferred named placeholder from D-081.
- Adapter-side identity directory/projection semantics; group-use enablement; multi-diary / subject-dimension work.
- A-15 / visibility changes; any widening of core domain/routing types or the `DomainRepository` signature; a `captured_at` provenance column.

## D-085 — Stage-1 capture/routing baseline correction, packet 3: explicit `/note` without a first-line date defaults to "today"

### Decision
On the explicit `/note` dispatch path, when the first non-empty line of the payload is **not** a recognized date, default the note to **today** instead of returning `INVALID_INPUT`. "today" is the UTC date the message was received — `InboundMessage.received_at.date()` (populated in production from the Telegram message send-time, `datetime.fromtimestamp(message.date, tz=UTC)`; set explicitly by every test fixture). The default is realized in the existing dispatcher helper `_normalize_note_first_line` (`src/memory_rag/services/dispatcher.py`): the not-a-date branch prepends a canonical `YYYY-MM-DD\n` line for that date to the payload, so the previously-first non-empty line and everything after it become event lines, and the strict parser then succeeds. This closes the companion correction D-078 deferred and **closes the Stage-1 capture/routing baseline correction milestone** (Packets 1/D-078, 2/D-079, 2.1/D-080, 3/D-085).

- **"today" source — reuse `received_at`, no clock seam.** D-070 named the design blocker as needing "a clock seam for 'today'." That blocker is resolved by reusing the tz-aware `InboundMessage.received_at` field already on the frozen message — a deterministic, per-message, channel-neutral source. No `Dispatcher.__init__` change, no wall-clock callable, and none of the ~11 `Dispatcher(...)` construction sites are touched. Semantically the note's date is the day the user sent the message, not a dispatch wall-clock.
- **Bare/empty `/note` keeps `INVALID_INPUT`.** The today-default fires only when there is a non-empty first line that is not a date. An empty or whitespace-only payload (a bare `/note`) has no non-empty line, so it falls through `_normalize_note_first_line` unchanged to `parse_note`, which returns `None`, and the reply stays exactly `"First line must be a date like 2026-05-09. Got: ''."`. The `INVALID_INPUT` contour is therefore preserved and reachable, just narrowed to the degenerate-input case — this avoids silently creating empty dated notes from an accidental bare `/note`.
- **Parser stays strict (A-28 stays open).** `core/domain/parser.parse_note` / `_parse_iso_date` / `_split_non_empty_lines` and the D-070 `normalize_iso_date_token` whitelist are byte-for-byte unchanged. The default lives in the dispatcher seam, not the parser — so A-28's named claim ("the date parser recognizes only `YYYY-MM-DD`") stays accurate, and A-28 remains **open** as the A-12 (date-parsing-scope) precursor.

### Why
D-078 retired the heuristic plain-text auto-route and explicitly carved out the `/note`-without-explicit-date → "today" default as a distinct later companion packet; D-070 deferred it on the clock-seam concern. With D-079 (classifier code) and D-080 (doc reconciliation) landed, this is the last open packet of the milestone. The operator-facing motivation (D-067 §Observations, the `/note` first-line-date strictness thread) is that requiring an explicit date on every `/note` is more friction than the product wants: a casual `/note went for a walk` should record under today, not bounce with an error. The functional invariants the canonical docs pin on the `/note` lifecycle are unaffected:

- **I-5 (one event per line).** Unchanged. Prepending a date line makes the previously-first line a normal event line; each non-empty body line is still one event / one chunk.
- **I-3 / I-15 (raw persisted first / raw highest durability tier).** Raw `SourceMessage` is still persisted before parse/chunk/embed, for both the success and the (empty-payload) `INVALID_INPUT` contour. **Honest-provenance note:** `DomainService.ingest` persists `raw_text=message.payload` — the dispatcher-normalized payload — so the prepended `today` line lands in `raw_text`. This extends the normalize-before-persist seam D-070 already established (D-070 rewrote the first-line date token in `raw_text`); this packet adds a prepended line for the dateless case. The original command text remains on `InboundMessage.text` (not persisted). Byte-original raw capture is not a current requirement and is not introduced here.
- **I-14 / R-11 / R-13 (command-less plain text → draft floor).** Unchanged. The default fires only on the **explicit** `/note` command; command-less plain text still routes only to the draft floor (D-078/D-079). `/note` is an explicit command, so supplying a default date does not "silently change the persistence outcome" of an unmarked message — the user explicitly asked to record a note.
- **D-026 (host-neutral core).** Unchanged. The helper takes and returns an `InboundMessage` via `dataclasses.replace`, reads the channel-neutral `received_at`, and emits a plain `YYYY-MM-DD` string. No transport types, host identifiers, provider SDKs, raw SQL, or use-case vocabulary are introduced.

### Consequence
- **Changed:** `src/memory_rag/services/dispatcher.py` — `_normalize_note_first_line` splits its former `if canonical is None or canonical == stripped: return message` into two branches: `canonical is None` (first non-empty line not a recognized date) now returns `dataclasses.replace(message, payload=f"{message.received_at.date().isoformat()}\n{payload}")`; `canonical == stripped` (already-canonical date) still returns the message unchanged; the near-ISO rewrite branch is byte-identical to D-070. The `if not payload: return message` guard and the loop's terminal `return message` (no non-empty line → empty/whitespace payload) are unchanged, so the `INVALID_INPUT` contour survives for bare/empty `/note`. Docstring updated to describe the three cases and the `received_at`-derived default. No constructor, factory, webhook, or import change.
- **Changed:** `tests/test_dispatcher_note_normalization.py` — flipped the two now-stale no-op tests (`..._for_unmatched_first_line`, `..._for_unpadded_form`) to assert the prepended-today payload (`2026-05-10\n…`, from the fixture's `received_at=datetime(2026, 5, 10, tzinfo=UTC)`); added helper tests for multi-event and leading-blank-line dateless payloads; added dispatcher-seam tests (`...dateless_note_saves_under_today`, `...dateless_multi_line_note_saves_all_events_under_today`); added sibling-wording byte-equality guards (`...empty_note_still_returns_invalid_input_wording`, `...whitespace_only_note_still_returns_invalid_input_wording`, `...dateless_note_with_no_events_uses_saved_no_events_wording`) pinning the `INVALID_INPUT` / `"Saved … with no event lines."` literals against drift. Module docstring extended with the D-085 contract.
- **Changed:** `tests/test_end_to_end_smoke.py` — added a `_today_iso(update_id)` helper mirroring the webhook's `received_at` derivation (`datetime.fromtimestamp(1715300000 + update_id, tz=UTC).date()`, computed not hardcoded); replaced `test_note_with_invalid_first_line_returns_invalid_input_and_persists_source` with `test_note_with_dateless_first_line_defaults_to_today_and_saves` (`/note not-a-date\nfoo` → `Saved 2 events for <today>`, raw source persisted) and a repointed `test_empty_note_returns_invalid_input_and_persists_source` (bare `/note` → the `Got: ''.` reply, raw source persisted); flipped `test_explicit_note_with_unpadded_date_is_rejected` → `test_explicit_note_with_unpadded_date_defaults_to_today`. The D-079 guard `test_command_less_dated_plain_text_routes_to_draft_floor` is unchanged and stays green.
- **Changed:** `tests/test_note_parser.py` — `test_returns_none_when_first_line_not_iso_date` extended with a D-085 boundary pin (`parse_note("walk in park") is None`) documenting that the default lives in the dispatcher, never in the parser. The parser strictness tests are otherwise unchanged.
- **Changed:** `docs/RUNBOOK.md` — §"`/note` first-line date format (D-070)": the "Rejected categories (fall through to the user-facing error)" block is reframed as "Forms not recognized as a date"; a new "Missing-date default (D-085)" paragraph names the `received_at`-derived "today", the prepend mechanism, and the `raw_text` provenance note; the user-facing-UX paragraph narrows the `INVALID_INPUT` reply to the empty/whitespace-only case; the scope note flips the deferred-companion clause to "landed in D-085 … parser stays strict ISO-only."
- **Changed:** `QUICKSTART.md` — the mock-smoke step 4 ("Non-ISO first line → INVALID_INPUT") becomes "Dateless first line → defaults to today" (`/note not-a-date\nfoo` → `Saved 2 events for 2024-05-10.`, with the message-date→received-date arithmetic noted); a new step 5 shows the empty-`/note` → `INVALID_INPUT` contour.
- **Changed:** `docs/assumptions.md` + `docs/assumption-audit.md` — A-28 reworded: the heuristic consumer is retired (D-078) and the `/note`-without-date → today companion landed (D-085) in the dispatcher seam, with `INVALID_INPUT` now only for empty/whitespace `/note`; A-28 stays **open** (parser strictness unchanged, A-12 precursor).
- **Changed:** `docs/execution-map.md` — the "Stage-1 capture/routing baseline correction" Packet 3 row flipped from **Pending** to **Done (D-085)** with the implementation summary and the milestone-closure note.
- **Changed:** `docs/todo.md` — Packet 3 flipped to done (D-085); the milestone marked closed.
- **No other `src/` change.** No schema / migration / DDL change, no `Dispatcher` constructor or factory change, no `config.py` / `.env.example` change, no `pyproject.toml` / `uv.lock` / `Makefile` / `docker-compose.yml` change, no live-provider change.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` deliberately **not** touched — I-3 / I-5 / I-14 / I-15 / R-11 / R-13 are unaffected (the default is on the explicit `/note` command, not command-less routing; raw is still persisted first).

### Out of scope (per packet boundaries)
- Any change to `core/domain/parser.parse_note` strictness; the parser stays ISO-only.
- Re-opening the retired heuristic plain-text auto-route; the command-less draft floor is untouched (D-078/D-079).
- Relative / natural-language dates (`yesterday`, `today`, `May 9 2026`), MM/DD/YYYY interpretation, per-community locale, locale-correct "today" — wider A-12 stays open.
- Byte-original raw-text capture (persisting the verbatim user input alongside the normalized payload).
- A clock-seam / injectable-`today` constructor argument on `Dispatcher` — deliberately avoided in favor of the existing `received_at` field.
- Author-name display, group-use, multi-diary / subject-dimension widening; retrieval / answer-path / schema / migration changes; D-072 rescue-branch work.

## D-086 — Author display-name resolution + `/sources` author rendering (closes the A-44 milestone surface)

### Context

D-081→D-084 built the author-display milestone in order: D-081 pinned the resolution contract (`author_user_id` is the canonical opaque core identifier; a human-readable display name is resolved **only at the Telegram adapter seam** via `username → first_name → opaque short-ID`, host-supplied and non-authoritative; `/sources` (D-036) is the sole sanctioned surface; `/ask`-reply attribution deferred — A-44). D-082/D-083 pinned the snapshot shape and the adapter-owned landing seam; **D-084 made the snapshot land durably** in the Telegram-adapter-owned `author_display_inputs` side table via the co-located `AuthorDisplayInputStore` port. What remained — the single explicitly **Pending** row of the milestone — is the *resolution helper + `/sources` rendering* half of A-44. This is that packet.

The seam problem this packet settles: the `/sources` block was rendered inside the channel-neutral `services/dispatcher.py` (`_render_source_block`), and an `EventChunk` carries only opaque `author_user_id` + `source_message_id` — **not** the `(external_chat_id, external_message_id, edit_seq)` tuple that keys `author_display_inputs`. Since resolution must stay adapter-only (D-081), the display name cannot be composed in the dispatcher, and the keying tuple must be recovered without teaching core types to carry display data.

### Decision

- **Relocate `/sources` block rendering to the Telegram adapter**, mirroring the established `/drafts` pattern (`DispatchResult.drafts: list[SourceMessage]` already returns domain objects that the adapter renders, including author, via `_render_draft_block`). `DispatchResult.source_blocks: list[str]` is replaced by `source_chunks: tuple[EventChunk, ...]`. `_dispatch_sources` returns the cached opaque chunks; the dispatcher keeps owning the channel-neutral header wording (`"Selected chunks for your last /ask (N chunk(s)):"`), so I-1 is preserved. The dispatcher's `_render_source_block` is removed.
- **Adapter-side resolver** in `adapters/telegram/author_display.py`: a pure `resolve_author_display_name(username, first_name, author_user_id)` implementing the fallback chain — a non-blank `username` → `@<username>`, else a non-blank `first_name` → plain, else the opaque floor `user-<last 8 of author_user_id>`. A value counts as present only when non-`None` and non-blank after `.strip()`.
- **Opaque-boundary bridge** `resolve_chunk_author_display(chunk, store)`: looks the source message up (`get_source_message(chunk.source_message_id)`) to recover the external tuple, reads the snapshot (`get_author_display_input(...)`), then resolves. A missing source row or missing snapshot (e.g. a chunk that predates D-084 capture) falls through to the short-ID floor — derived from `chunk.author_user_id`, which is always present — so the line is never blank and never raises.
- **Render format** (confirmed with owner): the author appears on a separate attribution line beneath the byte-unchanged date/index header — `[YYYY-MM-DD] (i/N)\n— <author>\n\n<chunk_text>`. Block-to-block packing is unchanged (`pack_drafts_into_messages`).
- **Store seam:** a new `get_backend_store()` dependency returns the same per-process singleton typed as the combined `TelegramBackendStore` for the renderer (it needs both `get_source_message` and `get_author_display_input`); the capture path keeps its narrow `AuthorDisplayInputStore` dependency (least privilege).

The core `DomainRepository`, `SourceMessage`, `EventChunk`, `InboundMessage`, and `get_or_create_source_message` are unchanged; no schema / migration / DDL change. Resolved names stay **non-authoritative** presentation; the core still carries authorship only as the opaque `author_user_id` (I-1, I-6). **A-44 is resolved by this packet** (its open condition was resolution + `/sources` rendering); `/ask`-reply (answer-reply) author attribution remains a **separate** deferred placeholder, not a gate on A-44.

### Why

Mirroring the `/drafts` return-domain-objects pattern means the architecture is chosen by precedent, not invented in the diff: display resolution lands adapter-side per D-081 while the channel-neutral dispatcher keeps only the header wording (I-1). Recovering the keying tuple via `get_source_message` (a read, not a signature change) bridges the opaque boundary without teaching core types to carry display data. The short-ID floor guarantees a value for every chunk, including pre-D-084 ones, so the surface degrades gracefully rather than blanking or raising.

### Consequence

- **Changed:** `src/memory_rag/adapters/telegram/author_display.py` — added `resolve_author_display_name`, `resolve_chunk_author_display`, `render_source_block` (+ `_present` helper); imports `EventChunk`.
- **Changed:** `src/memory_rag/core/routing/models.py` — `DispatchResult.source_blocks: list[str]` → `source_chunks: tuple[EventChunk, ...]`; docstring updated; `EventChunk` added to the `TYPE_CHECKING` import.
- **Changed:** `src/memory_rag/services/dispatcher.py` — `_render_source_block` removed; `_dispatch_sources` returns `source_chunks`; docstring updated.
- **Changed:** `src/memory_rag/adapters/telegram/webhook.py` — new `get_backend_store()` dependency; handler injects `backend_store`; the `/sources` branch renders blocks via `render_source_block`; `sources.delivered` log uses the chunk count.
- **Added:** `tests/test_author_display_resolution.py` (pure resolver fallback ordering, blank/whitespace handling, short-ID; bridge happy-path + missing-source/missing-snapshot/both-null floors; byte-stable block format). **Changed:** `tests/test_telegram_sources.py` (new format assertions + a populated-store three-tier rendering test), `tests/test_dispatcher_sources.py` (`source_blocks` literals → `source_chunks` identity), `tests/test_author_display_boundary.py` (guards: `DispatchResult` carries chunks not rendered authors; the dispatcher exposes no resolver/renderer symbol — resolution stays adapter-only).
- **Changed:** `docs/RUNBOOK.md` (`/sources` rendering + author-attribution paragraphs), `docs/assumptions.md` + `docs/assumption-audit.md` (A-44 → **resolved by D-086**; `/ask`-reply attribution remains a separate deferred item), `docs/execution-map.md` + `docs/todo.md` (the resolution/rendering row flipped to **Done (D-086)**).
- A-15 unchanged.

### Out of scope (per packet boundaries)

- Answer-reply (`/ask` reply) author attribution — remains the deferred named placeholder from D-081.
- Any change to core `DomainRepository`, `SourceMessage`, `EventChunk`, `InboundMessage`, or `get_or_create_source_message`; any schema / migration / DDL change.
- Group-use, multi-diary, subject-dimension, visibility (A-15), or identity-directory work.
- Batching the per-chunk snapshot reads; unrelated retrieval / answer-path / deployment work.

## D-087 — Read-access enforcement: Slice 8.1 audit + milestone decomposition (docs-first)

### Context

Execution-map Slice 8.1 ("community-scoped access enforced at every read — I-7, R-3 — Stage 3") is listed but has never been decomposed: no decision entry, no roadmap doc, no packet breakdown. D-044 explicitly left every Stage-3 Phase-8 slice undecomposed. The Stage-2 → Stage-3 operationalization gate is open (OP-1..OP-5 complete), so the milestone is unblocked. This packet opens it docs-first, mirroring the DEPLOY-1.1 (D-060) / OP-1 roadmap precedent: the decision entry carries the stable contract; a new roadmap doc carries the refinable sequence.

An as-built audit of the read surface (recorded in full in the new roadmap doc) found:

- **Already enforced (R-3 / R-8).** The hot `/ask` read path rejects a null/empty `community_id` (`ValueError`) at `QueryService.answer` and at both `SearchRepository` legs, filters by community in SQL/Python (`WHERE ec.community_id = …` on the Postgres dense + sparse legs; equivalent skip in the mock store), and asserts single-community prompt assembly in `build_answer_prompt` (`CrossCommunityContextError`). `list_source_messages`, `list_recent_drafts`, and `list_failed_event_chunks` are likewise mandatory-`community_id` and filtered. Isolation tests already exist (`test_cross_chat_isolation`, the `test_*_scope_isolates` pair, `test_missing_community_id_raises`, `test_raises_on_cross_community_chunks`).
- **Latent gaps.** `get_query`, `get_retrieval_hits_for_query`, `get_answer_trace_for_query`, and `get_event_chunk` take no `community_id` and apply no community filter — but have **no production callers** (tests only). `get_source_message` takes no `community_id` and is reached on a **live path** (`adapters/telegram/author_display.resolve_chunk_author_display`, for `/sources` author attribution), though today only over an already-community-scoped chunk drawn from the `community_id`-keyed `_latest_sources` cache. `answer_traces` rows carry no `community_id` column (community is recoverable via `query_id → queries.community_id`).

### Decision

- **Frame the milestone under I-7 / R-3 / R-8** and treat "cross-community leakage is prevented" + "access behavior is explicit" (Phase-8 DoD, `BuildPlan.md`) as the milestone exit criterion. The hot `/ask` path already satisfies it; the milestone hardens the remaining read seams so the property holds by construction rather than by current call-graph accident.
- **Defensively scope the unscoped by-id/trace reads now** (owner-confirmed), before any of them gains a production caller. Each will take a mandatory `community_id`, reject null/empty with the standard `ValueError` guard used elsewhere, and **filter by the owning community via the appropriate predicate or join for that record's storage shape** (a record that carries `community_id` directly filters on its own column; a trace record whose community lives on the parent `queries` row filters via a `query_id → queries.community_id` join). The exact per-method predicate vs. join is an implementation choice for the code packet, deliberately left contract-level here so the roadmap does not over-specify storage.
- **No `answer_traces` schema change** (owner-confirmed). Community stays recoverable through the existing `query_id → queries.community_id` join; the milestone remains a pure read-path concern and adds no column, DDL, or migration.
- **`get_source_message` is a live-path seam, sequenced separately into Packet 8.1.2.** It is *not* part of the unused-reads packet (8.1.1); threading `community_id` through it touches the live `/sources` author-resolution path and earns its own packet with cross-community characterization tests. Readers must not mistake 8.1.1's completion for closure of all latent/read seams — `get_source_message` and the `/sources`/`_latest_sources` characterization coverage close in 8.1.2, and the consolidated verification sweep in 8.1.3.
- **Record the packet ladder** (refinable when each is planned): **8.1.0** (this docs packet, D-087); **8.1.1** defensive scoping of the four unused by-id/trace reads; **8.1.2** `get_source_message` scoping + `/sources` author-resolution wiring + `/sources`/`_latest_sources` isolation characterization tests; **8.1.3** milestone closure/verification sweep + RUNBOOK operator note + DoD evidence. Slice 8.2 (visibility, A-15) and Slice 8.3 (export/delete/audit/retention) stay out of this milestone.
- **New roadmap doc** `docs/READ-ACCESS-ENFORCEMENT-ROADMAP.md` carries the as-built audit table and the refinable sequence; this entry stays authoritative for the contract.

### Why

Opening the milestone docs-first matches the established convention (DEPLOY-1.1 / D-060; OP-1 roadmap / D-044): pin the contract and the audit before touching `src/`, so the later code packets execute against a recorded decision rather than improvising scope. Scoping the unused reads now is defense-in-depth — the leakage is latent (no caller) today, but an operator inspection endpoint or future surface could expose `get_query` / `get_answer_trace_for_query` and silently cross communities; closing them while they are callerless is the cheapest point to do so and directly serves the "access behavior is explicit" DoD line. Recovering trace-read community via the existing `queries` join (rather than denormalizing `community_id` onto `answer_traces`) keeps the milestone read-only and avoids a schema/migration that the join already makes unnecessary. The functional invariants are unaffected: I-7 (every record outside `SourceMessage` carries `community_id`), R-3 (every *retrieval* call carries non-null `community_id`; the retriever rejects calls without it), and R-8 (no cross-community chunks in a prompt) all remain accurate as written — by-id reads are not "retrieval", so this packet neither weakens nor restates them.

### Consequence

- **Added:** `docs/READ-ACCESS-ENFORCEMENT-ROADMAP.md` — the milestone roadmap doc: §1 Scope (+ explicitly-out-of-scope), §2 the as-built read-path audit table, §3 the enforcement contract (D-087), §4 the refinable packet sequence, §5 dependencies & ordering, §6 exit criterion, §7 See also.
- **Changed:** `docs/execution-map.md` — the Phase-8 Slice 8.1 row points at the new roadmap doc + D-087; a "Read-access enforcement (Slice 8.1)" note block records the sub-packet pointers (8.1.0..8.1.3), mirroring the OP-/DEPLOY- annotation style.
- **Changed:** `docs/todo.md` — a new top-of-list "Slice 8.1 — Community-scoped read-access enforcement (cross-community leakage prevention)" milestone section: Packet 8.1.0 marked **done (D-087)**; 8.1.1 / 8.1.2 / 8.1.3 listed as the ordered next picks.
- **No `src/` or `tests/` change.** No method signature change, no new guard in code, no schema / migration / DDL change, no `config.py` / `.env.example` change. This is a documentation packet only; `make check` is non-impacted.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` / `docs/assumptions.md` / `docs/assumption-audit.md` deliberately **not** touched — I-7 / R-3 / R-8 stay accurate as written (they govern retrieval, not by-id reads), and no A-14 (per-chat community assignment) / A-15 (visibility, deferred to Slice 8.2) row becomes more truthful; A-14 and A-15 both stay **open**.

### Out of scope (per packet boundaries)

- Any `src/` or `tests/` change; any method-signature change or new code guard (all scheduled into 8.1.1 / 8.1.2 / 8.1.3).
- Adding a `community_id` column to `answer_traces` — explicitly omitted; community stays recoverable via the `query_id → queries.community_id` join.
- The visibility model / per-note scopes — Slice 8.2, blocked on A-15.
- Export / delete / audit / retention — Slice 8.3.
- Community-bootstrap reassignment — the per-chat `external_chat_id → community_id` mapping (A-14) stays as-is.
- Schema / DDL / migration / D-026–D-042 rename work.

## D-088 — Read-access enforcement, Packet 8.1.1: defensive scoping of the four unused by-id/trace reads

### Context

D-087 opened Slice 8.1 docs-first and recorded the as-built audit: four read methods — `get_query`, `get_retrieval_hits_for_query`, `get_answer_trace_for_query`, `get_event_chunk` — take only a record id and apply **no** community filter. The audit confirmed (and this packet re-confirmed by grep) that all four have **no production caller** under `src/memory_rag/{services,adapters,app}`; every call site is in `tests/`. They are the pure defense-in-depth seam D-087 sequenced first (8.1.1), ahead of the live `get_source_message` / `/sources` seam (8.1.2). This packet implements the 8.1.1 contract.

### Decision

- **All four reads now require a mandatory, keyword-only `community_id`** across the `DomainRepository` Protocol and all three backends (mock / sqlite / postgres), with full parity. Each rejects a null/empty `community_id` fail-closed with the standard guard already used by the enforced reads — `raise ValueError("community_id is required (Runtime invariant R-3)")` — before any lookup.
- **`community_id` is keyword-only** on these reads (e.g. `get_query(query_id, *, community_id)`) to prevent a silent positional swap between two `str` identifiers — the exact cross-community-leak class this milestone exists to prevent. (This is the only contract addition beyond D-087's; it does not restate I-7 / R-3 / R-8, which D-087 already framed.)
- **Scoping mechanism follows each record's storage shape**, exactly as D-087's contract allows: `get_query` and `get_event_chunk` filter their own `community_id` column (`WHERE … AND community_id = …`; the mock compares the stored row's `community_id`); `get_retrieval_hits_for_query` and `get_answer_trace_for_query` scope via the `query_id → queries.community_id` join (`JOIN queries q ON q.query_id = …`; the mock consults the parent `Query` in `_queries`), since neither trace record carries a `community_id` of its own and `answer_traces` gets no new column.
- **All three backends behave identically when the parent `Query` is absent or owned by another community: `[]` (hits) / `None` (trace), never an exception.** This fail-closed equivalence is pinned by one shared parametrized assertion per trace method (`test_get_retrieval_hits_missing_parent_query_reads_as_empty`, `test_get_answer_trace_missing_parent_query_reads_as_none`) so behavior cannot drift by backend.

### Why

Closing these reads while they are still callerless is the cheapest possible point — there is no live behavior to regress, and a future operator/inspection surface that reaches for `get_query` or `get_answer_trace_for_query` then inherits scoping by construction rather than having to remember it. Keyword-only is a structural guard, not a style choice: both arguments are `str`, so a positional call could transpose id and community and read the wrong community's row with no type error; forcing `community_id=` at every call site makes that mistake impossible and makes the scope explicit in the diff (the "access behavior is explicit" DoD line). Scoping the trace reads via the existing `queries` join keeps the milestone read-only and honors D-087's "no `answer_traces` schema change". I-7 / R-3 / R-8 are unaffected and not restated — by-id reads are not "retrieval".

### Consequence

- **Changed (`src/`):** `storage/repository.py` (the four Protocol signatures + docstrings), `storage/mock/store.py`, `storage/sqlite/store.py`, `storage/postgres/store.py` — each of the four reads gains the keyword-only `community_id`, the fail-closed guard, and the own-column filter or `queries` join.
- **Changed (`tests/`):** every existing call site (58, across `test_reconciliation.py`, `test_indexing_pipeline.py`, `test_sqlite_store.py`, `test_postgres_store.py`, `test_retrieval_harness_shape.py`, `test_query_service.py`, `test_end_to_end_smoke.py`, `test_storage_query_traces.py`, `test_storage_answer_traces.py`) now passes `community_id=` explicitly. New guard + cross-community isolation + parent-missing tests added to `test_storage_query_traces.py` and `test_storage_answer_traces.py`, each from one parametrized `scoped_store` fixture over mock / sqlite / (PG-gated) postgres.
- **No schema / DDL / migration change.** `get_source_message`, `/sources`, the `_latest_sources` cache, and `author_display.py` are byte-unchanged — they close in Packet 8.1.2. No `config.py` / `.env.example` change. `make check` green (628 passed, 65 PG-gated skipped, mypy clean, ruff clean).
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` / `docs/assumptions.md` / `docs/assumption-audit.md` deliberately **not** touched — I-7 / R-3 / R-8 stay accurate as written; A-14 / A-15 stay open. The keyword-only enforcement and the fail-closed parent-missing equivalence are packet-level contract decisions recorded here. `[[feedback_full_gate_and_doc_truthfulness]]`, `[[feedback_decision_log_citation]]`, `[[feedback_sibling_wording_guard_tests]]`.

### Out of scope (per packet boundaries)

- `get_source_message` scoping, the `/sources` author-resolution path, and `_latest_sources` cache isolation — Packet 8.1.2.
- The consolidated isolation sweep + RUNBOOK read-access note + DoD evidence — Packet 8.1.3.
- Any `answer_traces` `community_id` column / schema / DDL / migration.
- Visibility model (Slice 8.2 / A-15); export/delete/audit/retention (Slice 8.3); A-14 community assignment; D-026–D-042 renames.

## D-089 — Read-access enforcement, Packet 8.1.2: scope `get_source_message` + thread requester-scoped `community_id` through `/sources` author resolution

### Context

D-088 (Packet 8.1.1) closed the four unused by-id/trace reads. The **only remaining live read seam** in Slice 8.1 was `get_source_message`: the `/sources` command renders each cached chunk into a block whose author is resolved by `adapters/telegram/author_display.resolve_chunk_author_display` → `store.get_source_message(chunk.source_message_id)`. That read took no `community_id` and applied no community filter, so it could fetch any community's source row by id. This packet closes it on the live path, the last step before the 8.1.3 closure sweep.

### Decision

- **`get_source_message` is now community-scoped** across the `DomainRepository` Protocol and all three backends (mock / sqlite / postgres) with parity: a mandatory **keyword-only** `community_id` (same rationale as D-088 — prevent a silent `str`/`str` positional swap), a fail-closed null/empty guard (`raise ValueError("community_id is required (Runtime invariant R-3)")`), and an **own-column filter** on `source_messages.community_id` (`WHERE source_message_id = … AND community_id = …`; the mock compares the stored row). The `source_messages` table already carries `community_id` — no schema change, the exact analog of D-088's `get_event_chunk`.
- **The live `/sources` path threads the requester-scoped `community_id`.** The webhook resolves the requester's community at the adapter edge from the inbound chat via the current identity mapping (A-14) into a local `community_id`, then passes it through `render_source_block(..., community_id=…)` → `resolve_chunk_author_display(..., community_id=…)` → `get_source_message(..., community_id=…)`. Storage and helper seams stay on the channel-neutral `community_id` vocabulary — the Telegram `external_chat_id` identifier is converted at the edge and does not leak into the helper signatures (D-026 / D-041). Threading the requester id (rather than trusting `chunk.community_id`) makes the author lookup actively requester-scoped: defense in depth over the already-community-keyed cache.
- **`_latest_sources` and the dispatcher are unchanged and relied upon as already-community-keyed.** This packet scopes `get_source_message` and threads the requester-scoped `community_id` through `/sources` author resolution; it does **not** redesign the dispatcher/cache layer. `_latest_sources` is keyed by `external_chat_id` (D-036), `_update_latest_sources` / `_dispatch_sources` are untouched, and the existing `test_two_family_caches_are_independent` already pins that cache isolation.
- **Fail-closed by fall-through, never a raise.** A source owned by another community reads as `None`, and `resolve_chunk_author_display` already falls through a missing source to the opaque short-ID author floor (`user-<last8>`). So a (today impossible) cross-community chunk resolves to the floor rather than leaking another community's author — no new branch, no raise, rendered-block format byte-unchanged.

### Why

Closing the read while threading the requester community gives the "access behavior is explicit" DoD line a structural guarantee: `/sources` author resolution cannot cross a community boundary even if the cache invariant were ever violated, because the storage read itself now filters by the requester's community. Keeping the read on `community_id` vocabulary (converting `external_chat_id` at the edge) preserves the D-026 adapter seam — the storage layer never learns a Telegram identifier. In production `community_id == external_chat_id` (A-14 identity) and retrieval already scopes chunks to the requester (R-3 / R-8), so the correct-community author resolves exactly as before; the change is invisible except on a cross-community attempt, which now fails closed. I-7 / R-3 / R-8 are unaffected and not restated.

### Consequence

- **Changed (`src/`):** `storage/repository.py`, `storage/mock/store.py`, `storage/sqlite/store.py`, `storage/postgres/store.py` — `get_source_message` gains the keyword-only `community_id`, the guard, and the own-column filter. `adapters/telegram/author_display.py` — `resolve_chunk_author_display` and `render_source_block` gain a keyword-only `community_id` and forward it. `adapters/telegram/webhook.py` — the SOURCES branch resolves a requester-scoped `community_id` local and passes it into `render_source_block`.
- **Changed (`tests/`):** all `get_source_message` call sites pass `community_id=` (`test_sqlite_store.py`, `test_postgres_store.py`). New `tests/test_storage_source_messages.py` — one parametrized `scoped_store` fixture (mock / sqlite / PG-gated postgres) with guard + cross-community isolation + missing-id tests. `tests/test_author_display_resolution.py` — `_FakeStore.get_source_message` is now community-aware (mirrors the real own-column filter), all call sites thread `community_id="42"`, and a new seam-focused `test_bridge_floor_when_community_mismatch` proves a mismatched requester-scoped `community_id` falls to the opaque floor and reads no snapshot (controlled-input fake, not an impossible end-to-end path). `tests/test_telegram_sources.py` is unchanged and stays green — the threaded id resolves authors end-to-end (chat / chunk / source all `"42"`).
- **No schema / DDL / migration change.** `_latest_sources` / dispatcher untouched. `make check` green (635 passed, 65 PG-gated skipped, mypy clean, ruff clean).
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` / `docs/assumptions.md` / `docs/assumption-audit.md` deliberately **not** touched — I-7 / R-3 / R-8 stay accurate; A-14 / A-15 stay open. The keyword-only enforcement, the requester-scoped threading, and the fail-closed fall-through are packet-level contract decisions recorded here. `[[feedback_full_gate_and_doc_truthfulness]]`, `[[feedback_decision_log_citation]]`, `[[feedback_sibling_wording_guard_tests]]`.

### Out of scope (per packet boundaries)

- The consolidated cross-community isolation sweep + `docs/RUNBOOK.md` read-access operator note + Phase-8 DoD evidence — Packet 8.1.3.
- Any `/ask` retrieval-behavior change beyond `/sources` scoping; redesign of the dispatcher / `_latest_sources` cache.
- Schema / DDL / migration (no new columns); `answer_traces` `community_id` column.
- Visibility model (Slice 8.2 / A-15); export/delete/audit/retention (Slice 8.3); A-14 community assignment / per-note overrides; D-026–D-042 renames.

## D-090 — Read-access enforcement, Packet 8.1.3: Slice 8.1 milestone closure (consolidated isolation sweep + operator note)

### Context

D-087 (audit + decomposition), D-088 (Packet 8.1.1, the four unused by-id/trace reads), and D-089 (Packet 8.1.2, `get_source_message` + requester-scoped `/sources`) landed the Slice 8.1 enforcement. The milestone's own exit criterion (`docs/READ-ACCESS-ENFORCEMENT-ROADMAP.md` §6) was still open: no consolidated cross-community isolation proof, no operator-facing `docs/RUNBOOK.md` read-access note, and the Phase-8 DoD lines "cross-community leakage is prevented" / "access behavior is explicit" not yet recorded as one closure artifact. A read-only audit during planning also surfaced a truthfulness gap: of the five scoped by-id/trace/source reads, `get_event_chunk` (scoped by D-088) was the **only** one with no null-`community_id` guard test and no cross-community isolation test of its own — its four siblings each had both. D-088 added the `get_event_chunk` filter + guard to all backends but shipped no isolation test for them.

### Decision

- **One consolidated milestone-level proof.** New `tests/test_read_access_isolation.py` is the single reviewable sweep. From one parametrized `scoped_store` fixture (mock / sqlite / PG-gated postgres) it pins two contracts across all five scoped reads — `get_query`, `get_retrieval_hits_for_query`, `get_answer_trace_for_query`, `get_event_chunk`, `get_source_message`: (1) a null/empty `community_id` raises `ValueError` (R-3 guard sweep); (2) a record owned by `fam-A` reads the fail-closed sentinel (`None`, or `[]` for `get_retrieval_hits_for_query`) for `fam-B`, never another community's row (cross-community sweep). The file's module docstring indexes the remaining milestone evidence that stays in place (hot-path retrieval scope, prompt-assembly `CrossCommunityContextError`, the `/sources` author-resolution seam, the already-community-keyed `_latest_sources` cache) so it reads as the navigable closure index rather than a re-implementation.
- **`get_event_chunk`'s isolation/guard is newly pinned by this sweep.** It runs green against current code — D-088's filter + guard were correct; only the test was missing. No `src/` change was required.
- **Operator note.** A new `### Read-access scoping (Slice 8.1 / D-087, D-088, D-089, D-090)` subsection in `docs/RUNBOOK.md` records what 8.1 enforces: every community-owned read is scoped or a documented safe-by-construction seam; fail-closed on a bad/missing `community_id`; own-column filter vs. `query_id → queries.community_id` join; keyword-only `community_id`; the no-`answer_traces`-column / recover-via-join decision; and the `MEMORY_RAG_PG_TEST_DSN`-gated Postgres-leg caveat.
- **Milestone closed.** `docs/READ-ACCESS-ENFORCEMENT-ROADMAP.md` (§0 status, §4 packet table, §6 exit criterion), `docs/execution-map.md` (Slice 8.1 + 8.1.3 rows), and `docs/todo.md` (Slice 8.1 section) flip 8.1.3 / Slice 8.1 to done.

### Why

The consolidated sweep makes the no-cross-community-leakage property hold by construction across the whole scoped-read surface rather than by current call-graph accident, and it closes the one read (`get_event_chunk`) whose enforcement was previously asserted in the roadmap audit but unproven in tests. Recording the contract in the RUNBOOK gives operators the "access behavior is explicit" guarantee in prose alongside the executable proof. Keeping the milestone read-only (no schema, no `answer_traces` column) preserves the D-087 contract that community is recoverable via the `queries` join.

### Consequence

- **Changed (`tests/`):** new `tests/test_read_access_isolation.py` — the parametrized guard + cross-community sweep over the five scoped reads (mock + sqlite unconditionally; postgres when `MEMORY_RAG_PG_TEST_DSN` is set). No other test file changed; the per-packet isolation tests stay as-is.
- **Changed (`docs/`):** `docs/RUNBOOK.md` (new read-access scoping subsection), `docs/decision-log.md` (this D-090 entry), `docs/READ-ACCESS-ENFORCEMENT-ROADMAP.md`, `docs/execution-map.md`, `docs/todo.md` (closure flips).
- **No `src/` change. No schema / DDL / migration change.** `get_event_chunk` ran green under the new sweep, so no D-088 correction was needed.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` / `docs/assumptions.md` / `docs/assumption-audit.md` deliberately **not** touched — I-7 / R-3 / R-8 stay accurate and are not restated; A-14 / A-15 stay open. The consolidated-sweep shape and the deliberate overlap with the per-packet tests are packet-level decisions recorded here. `[[feedback_full_gate_and_doc_truthfulness]]`, `[[feedback_decision_log_citation]]`, `[[feedback_sibling_wording_guard_tests]]`.

### Out of scope (per packet boundaries)

- Visibility model / per-note scopes — Slice 8.2 (blocked on A-15).
- Export / delete / audit / retention — Slice 8.3.
- A-14 community-assignment redesign; the per-chat `external_chat_id → community_id` mapping.
- Any schema / DDL / migration (incl. an `answer_traces.community_id` column).
- Any `/ask` / `/sources` / retrieval / storage / dispatcher runtime behavior change.
- D-026–D-042 rename work.

## D-091 — Answer-reply (`/ask` reply) contributor-attribution contract + adapter seam (docs-only; code deferred to the follow-up packet)

### Context

D-081→D-086 built the author-display milestone: D-081 pinned the resolution contract (`author_user_id` is the canonical opaque core identifier; a human-readable display name is resolved **only at the Telegram adapter seam** via `username → first_name → opaque short-ID`, host-supplied and non-authoritative); D-082/D-083/D-084 pinned and landed the durable snapshot in the adapter-owned `author_display_inputs` side table; **D-086 implemented resolution + `/sources` rendering and resolved A-44.** Throughout, "answer-reply (`/ask` reply) attribution" was carried as an explicit **separate deferred placeholder** — named in `docs/execution-map.md` and `docs/todo.md`, never a gate on A-44.

This is the first packet of the `feat/ask-reply-contributor-attribution` milestone, whose intent is to surface **which contributors grounded an `/ask` answer** in the grounded reply itself — framed as *contributor attribution* (the set of contributors whose notes grounded the answer), **not** single-author attribution for the whole answer. The supporting infrastructure already exists and is reusable: the adapter-only resolver `resolve_chunk_author_display(chunk, store, *, community_id)` (D-086, community-scoped per D-089), the durable D-084 snapshot, and the answer's grounding-chunk set already exposed as `AnswerResult.context.ordered_chunks` (= `AnswerTrace.context_chunk_ids`, the same chunks `/sources` recalls). What is missing is a **recorded contract**: what the contributor set is, how it is deduplicated and ordered, how it renders, and which seam carries it. D-081 set the precedent of pinning such a display contract in docs before code (and D-078→D-079 set the precedent of a contract packet preceding the code packet); this docs-only packet does the same. **No `src/` / tests / schema / migration / runtime change** — the contract is recorded here and enforced in code by the follow-up packet.

### Decision

- **Contributor set.** The contributors surfaced for an `/ask` reply are the **distinct authors of the answer's grounding chunks** — `AnswerResult.context.ordered_chunks` (= `AnswerTrace.context_chunk_ids`). This is "the contributors whose notes grounded this answer", explicitly **not** a single author attributed to the whole answer and **not** per-claim / per-sentence attribution.
- **Deduplication.** Distinct on the canonical opaque **`author_user_id`** (deduped *before* display resolution), preserving authorship truth (I-6). Two distinct `author_user_id`s that resolve to the same display string (e.g. a shared `first_name`, or two opaque floors) intentionally appear as two separate list entries — the code packet must **not** collapse them on the display string.
- **Order.** First appearance in the grounding-chunk sequence (the `ordered_chunks` / RRF order). No re-sorting (no alphabetical).
- **Render shape.** A single **labeled footer line** beneath `answer_text`, separated by a blank line: `Contributors: <name1>, <name2>, …` (comma-space separated, in the deduped first-appearance order). A single contributor renders as `Contributors: @alice`. Each name is produced by the existing adapter-only `resolve_author_display_name` / `resolve_chunk_author_display` fallback chain (`@username → first_name → user-<last8>` floor), reusing one representative grounding chunk per distinct `author_user_id`.
- **Render condition.** The footer is rendered **iff the answer's grounding-chunk set is non-empty** — i.e. on grounded replies (including WEAK_EVIDENCE / AMBIGUOUS, which still carry grounding chunks). Contours with no grounding chunks (NO_EVIDENCE / empty-query / PROVIDER_UNAVAILABLE) carry **no** contributor line.
- **Seam.** The ASK `DispatchResult` will carry the opaque grounding chunks (mirroring the existing `DispatchResult.source_chunks` introduced by D-086 for `/sources`); the **Telegram adapter** resolves the distinct contributors and appends the footer to the reply. The channel-neutral dispatcher never composes a display name (it owns only `answer_text` and the opaque chunks), keeping resolution adapter-only (D-081 / D-086, I-1, I-6). Resolution uses the **requester-scoped** `community_id` already threaded for `/sources` author resolution (D-089), so the read can never cross a community boundary (I-7, R-3).

The core `DomainRepository`, `SourceMessage`, `EventChunk`, `InboundMessage`, `QueryService`, and `AnswerResult` are unchanged by the contract; no schema / migration / DDL. Resolved names stay **non-authoritative** presentation; the core still carries authorship only as opaque `author_user_id` (I-1, I-6). A-44 stays **resolved by D-086** — this contract does not reopen it; it pins the separately-deferred `/ask`-reply surface it named.

### Why

Pinning the contract first keeps the milestone's opening move a single reviewable decision (mirroring D-081 for `/sources` and the D-078→D-079 contract-then-code split), and locks the choices a code packet would otherwise settle silently: the contributor-set source of truth, dedup-by-`author_user_id` (authorship truth over display tidiness, I-6), first-appearance order, the labeled-footer shape, and the grounded-only render condition. Reusing the existing `source_chunks` `DispatchResult` seam and the D-086 resolver means the code packet adds no new core surface and no new retrieval — it threads the already-available grounding chunks to the adapter and renders. Framing the set as *contributors* (plural, the grounding set) rather than one author keeps the surface honest about shared-diary authorship (I-6) and avoids implying a single author for a synthesized answer.

### Consequence

- **Changed (`docs/`):** `docs/decision-log.md` (this D-091 entry); `docs/execution-map.md` (the deferred line-228 row in the "Author display-name contract (D-081)" block decomposed into a docs-only contract row → **Done (D-091)** and a Pending code row); `docs/todo.md` (the placeholder turned into an active milestone section with an ordered Packet 1 / Packet 2 ladder); `docs/assumptions.md` + `docs/assumption-audit.md` (A-44 forward cross-reference noting D-091 pins the `/ask`-reply contributor-attribution contract — **A-44 stays resolved/closed, not reopened; no new assumption number**); `docs/RUNBOOK.md` (forward note after the `/sources` author-attribution paragraph); `docs/INVARIANTS.md` (I-6 cross-reference clause — no new invariant, no semantic change).
- **No `src/` / `tests/` / schema / DDL / migration / config change.** Live `/ask` and `/sources` behavior is byte-unchanged; the contract is recorded but **not surfaced** until the follow-up code packet.
- I-1 / I-6 / I-7 / R-3 unchanged; A-14 / A-15 stay open and out of scope. The contributor-set / dedup / order / render-shape / render-condition / seam decisions are packet-level contract decisions recorded here. `[[feedback_decision_log_citation]]`, `[[feedback_cause_neutral_user_wording]]`, `[[feedback_full_gate_and_doc_truthfulness]]`.

### Out of scope (per packet boundaries)

- Any `src/` / tests / schema / migration change, and any change to live `/ask` or `/sources` runtime behavior — the rendering lands in the follow-up code packet.
- Per-claim / per-sentence **citation** attribution and rendering the LLM-emitted `StructuredAnswer.cited_chunk_ids` — the word "citation" stays reserved (D-036); this is contributor attribution over the grounding set, not citation.
- Visibility / per-note scopes — A-15 / Slice 8.2.
- Multi-diary / community-bootstrap reassignment — A-14.
- Any change to the existing `author_display` resolver/seam shape or to `/sources` rendering; durability / expiry of the latest-sources cache; group-use / identity-directory work.

## D-092 — Answer-reply (`/ask` reply) contributor-attribution rendering (code packet for D-091)

### Context

D-091 pinned, docs-only, the `/ask`-reply contributor-attribution contract and explicitly deferred behavior to a named follow-up code packet (Packet 2 of the `feat/ask-reply-contributor-attribution` milestone). Until now the `/ask` reply was `answer_text` alone (D-069); the contract was recorded but not surfaced. This packet implements the rendering within D-091's exact boundaries — no contract is reopened. The reusable infrastructure D-091 named is unchanged: the adapter-only resolver `resolve_chunk_author_display(chunk, store, *, community_id)` (D-086, requester-`community_id`-scoped per D-089), the durable D-084 snapshot, and the grounding-chunk set already exposed as `AnswerResult.context.ordered_chunks`.

### Decision

- **Seam (core).** A new opaque field `DispatchResult.grounding_chunks: tuple[EventChunk, ...] | None` carries the answer's grounding chunks to the adapter. It is a **separate field parallel to `source_chunks`**, not a reuse — the webhook keys its `/sources` render branch on `source_chunks`, so a shared field would misroute the `/ask` reply into `/sources` rendering. Like `source_chunks` it carries opaque chunks, never a pre-rendered display name.
- **Render condition (encoded in the dispatcher).** The ASK handler sets `grounding_chunks` to `answer.context.ordered_chunks` **iff** that set is non-empty (the same guard as `_update_latest_sources`), else `None`. This makes the contract's grounded-only render condition a single source-side guard: grounded replies — including `WEAK_EVIDENCE` / `AMBIGUOUS`, which carry grounding chunks — surface the footer; `NO_EVIDENCE` / empty-query / `PROVIDER_UNAVAILABLE` contours carry `None` and are byte-unchanged.
- **Rendering (adapter-only).** A new `render_contributors_footer(chunks, store, *, community_id)` in `adapters/telegram/author_display.py` deduplicates on the opaque `author_user_id` **before** display resolution, preserves first-appearance order over `chunks`, resolves one representative chunk per distinct `author_user_id` through the existing `resolve_chunk_author_display` fallback chain (`@username → first_name → opaque short-ID`), and returns the single labeled line `Contributors: <name1>, <name2>, …`. Two distinct `author_user_id`s that resolve to the same display string stay two separate entries (dedup on authorship truth, never the display string — I-6). The webhook appends `\n\n<footer>` beneath `reply_text` when `grounding_chunks` is non-empty, using the requester-scoped `community_id` (`inbound.external_chat_id`) already used for `/sources` author resolution (D-089), so the read can never cross a community boundary (I-7, R-3).
- **Channel-neutrality.** The dispatcher composes no display name; it owns only `answer_text` and the opaque chunks. Resolution stays adapter-only (D-081 / D-086, I-1).

The core `DomainRepository`, `SourceMessage`, `EventChunk`, `InboundMessage`, `QueryService`, and `AnswerResult` are unchanged; no schema / DDL / migration. `/sources` rendering is unchanged. Resolved names stay **non-authoritative** presentation; the core still carries authorship only as the opaque `author_user_id` (I-1, I-6).

### Why

This is the minimal enforcement of D-091: one new opaque field on an existing channel-neutral type plus an adapter-side render helper, reusing the D-086 resolver and D-089 scoping with no new core surface and no new retrieval. A separate `grounding_chunks` field (rather than overloading `source_chunks`) keeps the `/ask` and `/sources` render paths disjoint and each branch's intent obvious. Putting the non-empty guard in the dispatcher makes the grounded-only render condition a single, testable decision point rather than a check duplicated at the render edge.

### Consequence

- **Changed (`src/`):** `core/routing/models.py` (the `grounding_chunks` field + docstring); `services/dispatcher.py` (ASK handler threads the chunks); `adapters/telegram/author_display.py` (`render_contributors_footer`); `adapters/telegram/webhook.py` (ASK render branch appends the footer).
- **Changed (`tests/`):** `tests/test_author_display_resolution.py` (footer dedup / order / same-display-string / floor / community-mismatch units); `tests/test_telegram_ask_contributors.py` (new — webhook render path: grounded footer, dedup + order, `WEAK_EVIDENCE` keeps footer beneath trailer, `NO_EVIDENCE` no footer, cross-community floor); `tests/test_dispatcher_retrieval_fallback.py` (dispatcher seam threads / withholds `grounding_chunks`).
- **Changed (`docs/`):** this D-092 entry; `docs/RUNBOOK.md`, `docs/execution-map.md`, `docs/todo.md` flipped from "by contract / not surfaced" to "surfaced (D-092)".
- **No schema / DDL / migration / config change.** `/sources` behavior byte-unchanged. I-1 / I-6 / I-7 / R-3 unchanged; A-14 / A-15 stay open and out of scope. A-44 stays resolved (D-086). `[[feedback_decision_log_citation]]`, `[[feedback_sibling_wording_guard_tests]]`, `[[feedback_full_gate_and_doc_truthfulness]]`.

### Out of scope (per packet boundaries)

- A-15 visibility / per-note scopes (Slice 8.2).
- A-14 multi-diary / community-bootstrap reassignment.
- Per-claim / per-sentence **citation** attribution and rendering `StructuredAnswer.cited_chunk_ids` — "citation" stays reserved (D-036).
- Any change to the `author_display` resolver/seam shape beyond reusing it here, or to `/sources` rendering; latest-sources cache durability / expiry.

## D-093 — A-14 resolution: community bootstrap, chat→community mapping, and grouped-diary membership (docs-first)

### Context

The owner prioritized advancing **grouped-diary support + multi-diary on one instance**. The data plane for this already exists and is hardened: every durable record is `community_id`-keyed (`0001.baseline-schema.sql`), reads are community-scoped and fail-closed (Slice 8.1 / D-088, D-089, D-090), and authorship is preserved per opaque `author_user_id` (I-6). The control plane is unratified: `community_id` is derived per-chat as `external_chat_id` (`services/domain_service.py` `_community_id_for`, commented "Per-chat surrogate until explicit community bootstrap exists (A-14)"; mirrored inline in `adapters/telegram/webhook.py` on the `/ask` and `/sources` author-resolution paths). No `Community` / `Participant` / `Subject` entity, registry, membership table, or `/setup` command exists. A Telegram **group** chat already produces one shared `community_id` with distinct per-sender `author_user_id`, and distinct chats already produce isolated communities on one instance — grouped and multi-diary "work mechanically" but were never pinned as a contract.

This is the docs-first opener of the grouped/multi-diary milestone (Packet 1 / G-0). It resolves the **community-bootstrap half of A-14** and sequences the follow-on work in `docs/GROUPED-MULTI-DIARY-ROADMAP.md`. It changes no `src/`, schema, or runtime behavior — the live mapping is **ratified, not modified**. It mirrors the D-087 / D-044 / D-060 precedent: this entry carries the stable contract; the roadmap doc carries the refinable sequence.

### Decision

- **Bootstrap mode (ratified).** Community bootstrap is **implicit-on-first-message**: a new inbound chat initializes its community scope on the first inbound message. This names existing behavior — the first message already persists a `SourceMessage` and derives its `community_id` — so it adds no mechanism and is consistent with the no-silent-loss floor (I-14 / R-13). An explicit `/setup` command is **deferred, not rejected**: an optional later refinement for naming / configuration / admin UX. No follow-on packet may depend on `/setup` existing first.

- **Chat→community mapping (ratified, adapter-axis).** `community_id` is derived from host-chat identity by the **tenant/auth-mapping adapter axis** (D-026 axis 5: "The mapping function is adapter; the scoped query is core" — `docs/ARCHITECTURE.md`). The default Telegram mapping is one community per chat, derived 1:1 from `external_chat_id`. This is the sanctioned mapping, **no longer a "surrogate."** The core continues to receive an **opaque** `community_id`; the mapping yields an opaque scope id that the default Telegram resolver happens to derive from `external_chat_id` — it is never described as "the Telegram chat id" past the edge (the D-089 edge-conversion framing).
  - **As-built note (recorded, not fixed here).** The mapping is currently expressed at three sites — the core-side `_community_id_for` (`services/domain_service.py`) and two inline copies on the `/ask` and `/sources` paths (`adapters/telegram/webhook.py`). This entry ratifies the *mapping rule*; it does **not** claim a single resolver seam already exists. Consolidating the three sites into one adapter-owned resolver (so the core receives the already-resolved opaque `community_id`) is sequenced as the first **code** packet (G-1) in the roadmap.

- **Membership (inherited, no core ACL).** Community membership is **inherited from host-chat membership**: anyone the host (Telegram) admits to the chat is a participant for community-level read/query access and may query the whole community corpus. Read access is community scoping (Slice 8.1, already enforced); authorship stays preserved per opaque `author_user_id` (I-6). This milestone introduces **no core participant / membership / ACL table**. A core participant registry is deferred until access must diverge from host-chat membership (e.g. a participant keeping notes others in the chat cannot query) — that divergence is the province of the visibility model (A-15 / Slice 8.2), sequenced after the first grouped slice.

- **Multi-diary on one instance (ratified).** Distinct chats mapping to distinct communities on a single instance is a core + adapter capability **today** — every record is `community_id`-keyed and every read is scoped, so N communities coexist on one instance without leakage (I-7 / R-3 / R-8; Slice 8.1). DEPLOY-1's "single-community / single-tenant default for the first pilot" (A-42) is a **deployment-posture default, non-binding on the core**; `docs/ARCHITECTURE.md` already forbids the core from assuming single-tenant.

- **Subject/child bootstrap (split out, deferred).** A-14's headline conflated two questions: community bootstrap (resolved here) and subject/child bootstrap. The latter is **carved out**: `subject_id` is born in the D-040 child-filter lineage (`docs/GLOSSARY.md`, TechSpec §5), not in this milestone. A-14 is **closed → D-093** for the community half; a new **A-45 (subject/child bootstrap)** is opened, pointing one-directionally at the D-040 lineage.

- **Visibility (A-15) relationship.** A-15 stays **open** and is **sequenced after** the first grouped pilot. Community-level scoping (every chat member sees the community corpus) is the access model for the first grouped slice — mirroring the Slice 8.1-without-A-15 / Slice 8.2-blocked-on-A-15 split. This entry decides only A-15's *sequencing*; it does not enumerate `visibility_scope` values.

### Why

The grouped/multi-diary mechanics already exist and are tested; what blocked the path was an unratified contract, not missing code. Ratifying implicit-on-first-message and the 1:1 chat→community mapping names what the system already does, so no behavior moves and the smallest-viable-slice rule holds. Inheriting host-chat membership matches how a shared family chat already behaves and keeps the core channel-neutral and opaque-id-based (no Telegram membership type enters the core, I-1); a core ACL would be speculative architecture the product does not yet need. Splitting A-14 lets the unblocked community half close now while the subject/child half stays with its natural D-040 home, rather than blocking one on the other. Deferring A-15 keeps the first grouped slice at community granularity — the same granularity Slice 8.1 already enforces — so the milestone does not widen into the visibility model.

### Consequence

- **Docs (this packet):** this D-093 entry; new `docs/GROUPED-MULTI-DIARY-ROADMAP.md` (refinable G-0..G-4 packet ladder); `docs/assumptions.md` + `docs/assumption-audit.md` (close A-14 → D-093, open A-45); `docs/execution-map.md` (milestone row + note block); `docs/todo.md` (milestone section, G-0 done). Cross-reference-only touches to `docs/INVARIANTS.md` (I-6 / I-7), `docs/RUNTIME-INVARIANTS.md` (R-3 / R-8 / R-14), `docs/RUNBOOK.md`, `docs/product/TechSpec.md` §5, `docs/ARCHITECTURE.md` — no enforcement-wording change, no new I-/R- number.
- **No `src/` / `tests/` / schema / DDL / migration / config change.** The live `community_id = external_chat_id` mapping is unchanged. I-1 / I-6 / I-7 / R-3 / R-8 / R-14 unchanged. A-15 stays open and sequenced. `[[feedback_decision_log_citation]]`, `[[feedback_full_gate_and_doc_truthfulness]]`.
- **Sequenced code work (not in this packet):** G-1 consolidate the chat→community mapping into one adapter-owned resolver (the milestone's only real `src/` packet); G-2 grouped + multi-diary regression tests; G-3 operator/product docs. A-45 subject bootstrap and A-15 / Slice 8.2 visibility remain future.

### Out of scope (per packet boundaries)

- Any `src/`, schema, migration, or runtime-behavior change — including the G-1 resolver consolidation.
- A core `Community` / `Participant` / `Subject` entity, membership/ACL table, or registry.
- An explicit `/setup` command (deferred-optional, not built, not depended on).
- Enumerating A-15 `visibility_scope` values (only its sequencing is decided).
- Subject/child bootstrap mechanics (carved out to A-45 / the D-040 lineage).
- DEPLOY-2 managed-cloud multi-tenant deployment shape (own roadmap).

## D-094 — G-1: consolidate the chat→community mapping into one adapter-owned resolver (code)

### Context

D-093 / G-0 ratified the chat→community mapping as a **D-026 axis-5** adapter function — "the mapping function is adapter; the scoped query is core" — but explicitly **did not** claim a single resolver seam existed (D-093 §"As-built note"): the live mapping was open-coded across multiple sites, and the core derived community scope by reading `InboundMessage.external_chat_id` directly. This is G-1, the milestone's only real `src/` packet, sequenced first so G-2's regression suite and G-3's docs target one named seam (`docs/GROUPED-MULTI-DIARY-ROADMAP.md` §5). Behavior-preserving: the default mapping stays 1:1, so every resolved `community_id` equals the prior `external_chat_id` value.

**As-built correction.** The D-093 audit named "three sites." A full census found the core derives community scope from `external_chat_id` in **six** core/services places — `services/domain_service.py` `_community_id_for`, `services/query_service.py`, and `services/dispatcher.py` ×4 (`_update_latest_sources`, `_dispatch_drafts`, `_dispatch_export`, `_dispatch_sources`) — plus the **two** adapter copies in `adapters/telegram/webhook.py` (`/ask` footer, `/sources`). The owner ratified the full-surface consolidation; leaving the dispatcher's four derivations would have left the core still deriving scope from `external_chat_id`, violating the D-093 §3 contract.

### Decision

- **One adapter-owned resolver.** New `adapters/telegram/community.py` `resolve_community_id(external_chat_id: str) -> str` is the single site that maps a Telegram chat to a core community scope. Default mapping is identity (1:1). A future host plugs a different mapping here without touching any core call site.
- **Resolved opaque scope crosses the boundary on `InboundMessage`.** `core/routing/models.py` gains a required `community_id: str` field — the resolved opaque scope, set by the adapter at the webhook edge. The core reads `message.community_id` everywhere it previously read `message.external_chat_id` for scope. `external_chat_id` is **retained** on `InboundMessage` and `SourceMessage` purely as the transport / idempotency identifier (the R-2 / D-023 key `(external_chat_id, external_message_id, edit_seq)`; addressing the reply via `sendMessage(chat_id=…)`; the D-084 author-display capture key). The two fields are equal-valued under the default mapping but are distinct concerns.
- **Required, no default.** `community_id` has no default — there is no safe default for a resolved scope (fail-closed, consistent with R-3). The `QueryService` R-3 guard now reads `if not community_id: raise … "InboundMessage.community_id is required (R-3)"`.

### Why

The mapping is an adapter-axis function (D-026 axis 5); resolving it once at the edge and carrying the opaque result on the channel-neutral `InboundMessage` is the minimal change that makes the D-093 §3 contract true in code. It **strengthens I-1**: the core now scopes on an opaque `community_id`, never on a field named "chat id." Carrying the value on `InboundMessage` (vs. threading a separate argument through `dispatch`/`ingest`/`answer`) keeps the resolved scope cohesive with the message it scopes and avoids spreading it across many signatures. Behavior is fully preserved (default 1:1), so the smallest-viable-slice and no-behavior-drift rules hold.

### Consequence

- **`src/`:** new `adapters/telegram/community.py`; `core/routing/models.py` (`InboundMessage.community_id` + docstring); `adapters/telegram/webhook.py` (resolve once at edge, `/ask` + `/sources` read `inbound.community_id`, A-14 comments repointed to the resolver); `services/domain_service.py` (deleted `_community_id_for`, reads `message.community_id`); `services/query_service.py` (reads field, R-3 guard reworded); `services/dispatcher.py` (4 scope reads + the `community_id=`-labelled ASK log → `message.community_id`; `chat_id`-labelled transport logs unchanged); `eval/retrieval/harness.py` (2 `InboundMessage` constructions).
- **`tests/`:** `community_id` added to 8 test `InboundMessage` factories/call sites (set equal to the existing `external_chat_id` so assertions hold); `test_query_service.py::test_missing_community_id_raises` now drives `community_id=""` and matches `"community_id"`; new `tests/test_telegram_community_resolver.py` pins the default 1:1 seam.
- **No schema / DDL / migration / config change.** `SourceMessage.community_id` was already persisted; only how the value is produced upstream changed. I-1 (strengthened) / I-6 / I-7 / R-3 / R-8 / R-14 preserved. Full gate green (ruff + mypy + 672 passed / 65 PG-skipped). `[[feedback_decision_log_citation]]`, `[[feedback_full_gate_and_doc_truthfulness]]`.
- **Out of scope:** any non-default (non-1:1) mapping implementation; G-2 regression suite; G-3 operator/product docs; G-4 / A-15 visibility; A-45 subject/child bootstrap; `/setup`; core participant/ACL model; schema/migration; renames beyond the seam.

## D-095 — G-2: grouped + multi-diary characterization suite (tests)

### Context

D-094 / G-1 made the chat→community mapping a single adapter-owned seam (`resolve_community_id`) carried on `InboundMessage.community_id`. The grouped + multi-diary milestone (D-093; `docs/GROUPED-MULTI-DIARY-ROADMAP.md`) exits only when that behavior is pinned by a regression suite (G-2) and the operator/product docs are reconciled (G-3). This is G-2, sequenced after G-1 so the suite characterizes one named seam (roadmap §5). It pins *already-true* behavior; it is **not** a behavior change.

### Decision

- **One consolidated characterization file** `tests/test_grouped_multi_diary.py` (mirroring the Slice 8.1.3 precedent of one consolidated `tests/test_read_access_isolation.py`). Every `InboundMessage` is built with `community_id=resolve_community_id(chat)`, so the suite exercises the G-1 seam rather than hard-coding the identity mapping.
- **Group A — grouped diary (one chat, N senders, full ingest→ask):** one group chat is one `community_id` with distinct per-sender `author_user_id` (extends the single-author `test_domain_service` coverage to the multi-sender case); a grouped `/ask` preserves ≥2 distinct contributors through retrieval into `AnswerResult.context.ordered_chunks` (I-6), driven by full ingest rather than pre-built chunks; the ASK dispatch seam carries multi-author `DispatchResult.grounding_chunks` (D-091).
- **Group B — multi-diary on one instance (N chats → N communities):** distinct chats are isolated communities and `/ask` never crosses over (composes with `test_query_service::test_cross_chat_isolation` at grouped granularity); a thin seam pin ties the factories to `resolve_community_id` (grouped senders → one community; distinct chats → distinct communities).
- **Group C — cross-community read isolation at grouped granularity:** a grouped `/ask` cache in one community is invisible to another (composes with `test_read_access_isolation.py` and `test_dispatcher_sources::test_two_family_caches_are_independent`).

### Why

Characterizing the consolidated seam at grouped granularity is the milestone's hardening step: it locks the I-6 / I-7 / R-3 / R-8 behavior so a future reshape of `resolve_community_id` or the scoping path is caught. The suite composes with — rather than re-implements — the existing per-leg, by-id/trace, and cache isolation coverage, keeping the new file focused on the one genuine gap (a group chat with N distinct senders driven through the full ingest→ask flow).

### Consequence

- **`tests/`:** new `tests/test_grouped_multi_diary.py` (6 tests, mock-mode). **No `src/` change** — the suite passes against current production code, validating the "characterization, no behavior change" classification.
- **Harness boundary:** mock-mode only (`MockEmbeddingClient` / `MockChatClient`; sqlite retrieval raises `NotImplementedError`). The new file provides no PG/sqlite parity for the end-to-end grouped ingest→ask flow; storage-read and per-leg PG parity remain the responsibility of the existing PG-gated suites (`test_read_access_isolation.py`, `test_search_repository_postgres.py`), which stay part of full-gate validation. A module docstring states this boundary and indexes that coverage.
- **No schema / DDL / migration / config change.** I-1 / I-6 / I-7 / R-3 / R-8 preserved. Full gate green (ruff + mypy + 678 passed / 65 PG-skipped). `[[feedback_decision_log_citation]]`, `[[feedback_full_gate_and_doc_truthfulness]]`.
- **Milestone status:** G-2 landed; **G-3 (operator/product docs) still pending** — the grouped/multi-diary milestone is **not** closed by this packet (roadmap §6 exit criterion still names G-3).
- **Out of scope:** G-3 operator/product docs; adapter-side `Contributors:` footer rendering (already pinned in `test_telegram_ask_contributors.py`); G-4 / A-15 visibility; A-45 subject/child bootstrap; `/setup`; any `src/` / schema / migration change.

## D-096 — G-3: grouped + multi-diary operator/product docs reconciliation + milestone closure (docs-first)

### Context

D-094 / G-1 made the chat→community mapping a single adapter-owned seam (`resolve_community_id`, carried on `InboundMessage.community_id`) and D-095 / G-2 pinned the grouped + multi-diary behavior with `tests/test_grouped_multi_diary.py`. The grouped/multi-diary milestone (D-093; `docs/GROUPED-MULTI-DIARY-ROADMAP.md` §6) exits only when, **in addition** to G-1 and G-2, the operator/product docs record the bootstrap/mapping/membership model and how to run multi-diary on one instance (G-3). This is G-3, the milestone's final docs-only packet. It changes no `src/`, `tests/`, schema, or runtime behavior — it reconciles the canonical docs with the already-ratified, already-shipped mapping and closes the milestone.

### Decision

- **Operator how-to (RUNBOOK).** A new `docs/RUNBOOK.md` section "Grouped & multi-diary on one instance" — placed beside the existing "Read-access scoping (Slice 8.1 …)" section, which already delegates *assignment* to D-093 and governs only *reads* — documents, operator-facing: implicit-on-first-message bootstrap (no `/setup`); the default 1:1 `external_chat_id → community_id` mapping resolved at the webhook edge by the adapter-owned `resolve_community_id` (D-094), with `external_chat_id` retained only as the transport / R-2 idempotency key; host-chat-inherited membership with authorship preserved per opaque `author_user_id` (I-6); and running N isolated communities on one instance, every read community-scoped and fail-closed (I-7 / R-3 / R-8; Slice 8.1). Per-note visibility is forward-pointed to A-15 / Slice 8.2 (deferred).
- **Axis-5 reconciliation (ARCHITECTURE).** The Axis-5 prose names the single adapter-owned `resolve_community_id` seam (D-094) as the realization of the mapping; it already framed the mapping as adapter-owned and the core scope as the opaque `community_id` (no "surrogate" framing remained to remove).
- **Product reconciliation (TechSpec §5).** The §5 entity note states grouped + multi-diary-on-one-instance as **supported** (G-1/G-2; D-094/D-095) rather than only cross-referencing the D-093 contract.
- **Milestone closure.** With G-3 landing, the §6 exit criterion is met: G-1 (single seam) + G-2 (regression suite) + G-3 (docs) all landed. The roadmap `Status:` line, the G-3 packet-ladder row, §6, and the execution-map / todo milestone rows flip to closed — **conditional on this packet landing** (the milestone closes because G-3 lands, not retroactively). The deferred items (A-15 visibility / Slice 8.2 / G-4; A-45 subject/child bootstrap; `/setup`; DEPLOY-2) stay explicitly outside the closed milestone.

### Why

The milestone's mechanics and contract were already shipped (D-093/D-094/D-095); the only gap the exit criterion named was reconciling the operator/product docs so they neither outrun nor lag the code (Documentation Rule). The reconciliation is deliberately light and additive: the canonical docs were already cross-referenced to D-093, so G-3 adds the consolidated-seam reference and flips the supported/closed wording rather than rewriting aligned prose. Closing the milestone in the same packet keeps the contract→seam→tests→docs unit coherent.

### Consequence

- **Docs (this packet):** this D-096 entry; new `docs/RUNBOOK.md` "Grouped & multi-diary on one instance" section; `docs/ARCHITECTURE.md` (Axis-5 seam reference); `docs/product/TechSpec.md` §5 (supported wording); `docs/GROUPED-MULTI-DIARY-ROADMAP.md` (`Status:` line, §4 G-3 row, §6, See also); `docs/execution-map.md` (G-3 row + note block); `docs/todo.md` (milestone section). No new I-/R- number; `assumptions.md` / `assumption-audit.md` unchanged (A-14 closed → D-093, A-15 deferred, A-45 open — already correct).
- **No `src/` / `tests/` / schema / DDL / migration / config change.** The `resolve_community_id` seam and `InboundMessage.community_id` shape are referenced, not modified. I-1 / I-6 / I-7 / R-3 / R-8 / R-14 unchanged. `[[feedback_decision_log_citation]]`, `[[feedback_full_gate_and_doc_truthfulness]]`.
- **Milestone status:** G-3 landed; the grouped/multi-diary milestone (D-093) is **closed** (G-0..G-3 landed; G-4 deferred).

### Out of scope (per packet boundaries)

- Any `src/` / `tests/` / schema / migration / config change, or any change to the `resolve_community_id` seam / `InboundMessage.community_id` shape.
- Any new invariant in `INVARIANTS.md` / `RUNTIME-INVARIANTS.md` beyond pointer/wording corrections.
- G-4 / A-15 visibility model (Slice 8.2); A-45 subject/child bootstrap; `/setup`; DEPLOY-2.
- Reopening or re-deciding the D-093 contract.

## D-097 — H-0: subject-scoping contract + A-45 resolution + Milestone H roadmap (docs-first)

### Context

Milestone G closed (D-096): the chat→community mapping is a single adapter-owned resolver (`resolve_community_id`, D-094) carried on `InboundMessage.community_id`, community scoping is enforced end-to-end and fail-closed (I-7 / R-3 / R-8; Slice 8.1), and grouped + multi-diary-on-one-instance are pinned (D-095). When D-093 resolved the community half of A-14 it **carved out the subject/child half as A-45**, pointing it one-directionally at "the D-040 child-filter lineage" (D-040 shipped only the date-range filter dimension; the child/subject dimension was deferred). That label is now stale: subject scoping is a milestone in its own right, and `child` is use-case vocabulary — the canonical core term is **subject** (D-041; `docs/GLOSSARY.md`). `subject_id` exists nowhere in code, schema, or the domain model today; community is the only scoping dimension.

A-45 ("how a `subject` — first use case `child` — is first created and assigned to notes within a community") is still open and blocks any subject-scoped filtering / retrieval. This is the docs-first opener of the subject-scoping milestone (Packet H-0). It **resolves A-45 at the contract level** and sequences the follow-on code in `docs/SUBJECT-SCOPING-ROADMAP.md`. It changes no `src/`, schema, or runtime behavior. It mirrors the D-093 / G-0 precedent: this entry carries the stable contract; the roadmap doc carries the refinable sequence.

### Decision

- **`subject_id` shape (ratified).** Subject scope is carried as an **opaque, community-scoped, nullable** identifier `subject_id` on the subject-bearing core records (`Note`, `EventChunk`). It is born directly as `subject_id` (canonical vocabulary, D-041); the first use case maps `child → subject`, and `child` / `child_id` stay use-case-facing labels, never a core field name. `subject_id` is **subordinate to `community_id`**: it never widens or crosses community scope (I-7 / R-3 / R-8 are unchanged and remain the outer boundary).

- **`null` = community-wide (ratified).** A `null` `subject_id` means the note/chunk is community-wide (unscoped to any subject) — the access model that exists today. Subject scoping is **additive and optional**: introducing it does not retro-scope existing community-wide records.

- **Assignment is an adapter-axis function (ratified).** How a host assigns a `subject_id` to an inbound note is the **tenant/auth-mapping adapter axis** (D-026 axis 5: "the mapping function is adapter; the scoped query is core"), parallel to the chat→community resolver (D-094). The **default first-use-case mapping is single-subject per community** (one `child` per community) — behavior-preserving, since under it every note is community-wide / the lone subject and nothing changes versus today. The core receives an opaque `subject_id` (or `null`); it never derives subject from a host identity field (I-1). No follow-on packet may depend on an explicit subject-selection command existing first (parallel to D-093's `/setup`-deferred clause).

- **No core subject registry/entity (ratified).** This milestone introduces **no** core `Subject` / subject-registry / membership / per-subject-ACL entity. `subject_id` is an opaque scalar on existing records, exactly as `community_id` is. A subject registry is deferred until the product needs subject metadata or assignment to diverge from the default single-subject mapping (e.g. multiple named subjects per community) — a later, separately-planned decision.

- **Retrieval filter is optional, mirrors D-040 (ratified).** Subject-scoped retrieval is an **optional** keyword-only filter on the search legs, mirroring the D-040 `date_range` seam: a `Query.subject_scope` threaded to both retrieval legs, defaulting to `None` (no constraint, preserving the current retrieval shape and RRF inputs). It composes with — and is independent of — the date-range filter.

- **Separate from A-15 visibility (ratified).** Subject scoping answers *what a note is about*; A-15 visibility answers *who may see a note*. They are orthogonal. A-15 stays **open** and sequenced (Slice 8.2 / G-4) and is **not** advanced, enumerated, or blocked by this milestone.

- **A-45 disposition.** A-45 is **closed → D-097** at the bootstrap/assignment-contract level (mirroring A-14 → D-093). The code realization — `subject_id` in the data model, adapter-axis assignment, the optional retrieval filter, tests, and operator/product docs — is sequenced as Milestone H packets H-1..H-4 in `docs/SUBJECT-SCOPING-ROADMAP.md`. **No `src/` claim of a `subject_id` field/column/filter is made until H-1 makes it true** (mirroring D-093's "no single-resolver-seam claim until G-1").

### Why

The grouped/multi-diary milestone left subject scoping as the one open scoping question, parked under a now-stale "D-040 lineage" label. Ratifying the `subject_id` contract before any code names what the system will do and keeps the smallest-viable-slice rule: the default single-subject mapping is behavior-preserving, so H-1..H-4 add a dimension without moving existing behavior. Modeling `subject_id` as an opaque, nullable, community-subordinate scalar — assigned by an adapter axis, with no core registry — keeps the core channel-neutral and opaque-id-based (I-1) and avoids speculative subject-metadata architecture the product does not yet need, exactly as D-093 avoided a core participant/ACL table. Keeping subject scoping orthogonal to A-15 prevents the milestone from widening into visibility. Closing A-45 at the contract level (not the code level) matches the A-14 → D-093 precedent: the decision entry carries the contract; the roadmap carries the refinable code sequence.

### Consequence

- **Docs (this packet):** this D-097 entry; new `docs/SUBJECT-SCOPING-ROADMAP.md` (refinable H-0..H-4 packet ladder); `docs/assumptions.md` + `docs/assumption-audit.md` (close A-45 → D-097; A-15 clarified as distinct, stays open); `docs/product/TechSpec.md` §5 (subject-scoping note repointed to the ratified contract / Milestone H); `docs/GLOSSARY.md` (the `subject_id` identifier line repointed from D-040 to D-097 / Milestone H); `docs/execution-map.md` (new Milestone H block + forward-pointer from the closed Grouped block); `docs/RUNBOOK.md` (the subject/child-scoping forward note repointed to D-097 / Milestone H).
- **No `src/` / `tests/` / schema / DDL / migration / config change.** Community scoping (I-7 / R-3 / R-8) and authorship (I-6) are unchanged; no new I-/R- number; no `subject_id` field/column/filter is added in this packet. `[[feedback_decision_log_citation]]`, `[[feedback_full_gate_and_doc_truthfulness]]`.
- **Sequenced code work (not in this packet):** H-1 `subject_id` (nullable, opaque) in the `Note` / `EventChunk` domain model + migration; H-2 adapter-axis subject assignment (default single-subject mapping, carried on `InboundMessage`); H-3 optional `subject_scope` retrieval filter (mirroring D-040); H-4 regression suite + operator/product docs + milestone closure.

### Out of scope (per packet boundaries)

- Any `src/`, schema, migration, or runtime-behavior change — including H-1's `subject_id` field/column.
- A core `Subject` / subject-registry / membership / per-subject-ACL entity (deferred until assignment must diverge from the default single-subject mapping).
- An explicit subject-selection command or multi-subject UX (not built, not depended on).
- A-15 `visibility_scope` enumeration or any visibility advance (separate; Slice 8.2 / G-4).

## D-098 — Evidence-faithful attribution, Packet 1: expose the LLM-cited evidence set (`cited_chunk_ids`) on `AnswerResult`

### Context

Milestone **Evidence-faithful answer & source attribution** makes `/ask` answers and `/sources` report only the evidence the LLM actually used — its `cited_chunk_ids` — rather than every retrieved chunk, and present authors as human names. `QueryService.answer` already parses `structured.cited_chunk_ids` (validated by `parse_structured_answer` to be a subset of `AnswerContext.ordered_chunks`, I-9) but **discards** it: only `structured.answer_text` reaches `AnswerResult`. The two surfaces the milestone fixes — the on-demand `/sources` reply (`_update_latest_sources` reads `answer.context.ordered_chunks`) and the `Contributors:` footer (D-091 / D-092, keyed on the same grounding set) — therefore both render the **full retrieved set**, over-claiming the basis of the answer (PRD §7 "users can inspect the basis of answers" / "no silent failure may pretend confidence"). Exposing `cited_chunk_ids` on `AnswerResult` was already a recorded follow-up (D-058).

This is the foundational, additive seam packet: carry the LLM-used set out of the service. It is pure plumbing — **no consumer reads it yet**, no user-visible change — and unblocks the cited-only `/sources` packet (Packet 2) and the footer-removal packet (Packet 3) without forcing either to re-derive citations.

### Decision

- **`AnswerResult.cited_chunk_ids` (new field).** `AnswerResult` gains `cited_chunk_ids: tuple[str, ...] = ()`, the LLM's used-evidence set. It is **distinct from** the full retrieved set exposed by `context_chunk_ids` / `context.ordered_chunks`.
- **Per-contour truth table (every contour sets it explicitly).** The single `_finalize` convergence point gains a required keyword `cited_chunk_ids`, passed at all five call sites:
  - empty-query `NO_EVIDENCE` → `()`;
  - empty-merged `NO_EVIDENCE` → `()`;
  - `PROVIDER_UNAVAILABLE` → `()`;
  - `PARSE_FAILURE` → `()` — deliberately **not** mined from `response.raw_text`; the I-9 subset guarantee was never established on that contour;
  - graded `NONE` / `WEAK_EVIDENCE` / `AMBIGUOUS` → `structured.cited_chunk_ids` (a subset of `context_chunk_ids` by the parser's I-9 check);
  - graded LLM-marker `NO_EVIDENCE` → `structured.cited_chunk_ids` verbatim (typically `()`, taken truthfully from the structured answer, not forced).

### Why

Surfacing the already-parsed cited set on the result is the smallest bounded change that lets the consuming packets render used-only evidence without reaching back into the LLM output downstream — a worse, repeated seam. Defaulting the field to `()` and threading it explicitly through the one `_finalize` entry point keeps `Query.fallback` / `AnswerTrace.fallback_mode` / the cited set written from one decision per contour. Keeping `PARSE_FAILURE` / `PROVIDER_UNAVAILABLE` empty avoids ever presenting an unvalidated citation set as the basis of an answer.

### Consequence

- **`src/`:** `core/domain/models.py` (the `AnswerResult.cited_chunk_ids` field + docstring); `services/query_service.py` (`_finalize` keyword + the five explicit call sites). No consumer (dispatcher, Telegram adapter, eval harness) reads the field in this packet; reply rendering is byte-unchanged.
- **`tests/`:** `tests/test_query_service.py` gains a cited-set characterization block (empty on the four non-graded contours + the LLM-marker `no_evidence`; mirrors the full context under the cite-all mock; and a **strict-subset fidelity** case proving the seam carries the LLM's actual subset, not the retrieved set — via a test-only `cited_subset_size` knob on `_MarkerChatClient`).
- **Docs (this packet):** this D-098 entry; `docs/execution-map.md` (new milestone block + Packet 1 row). `[[feedback_decision_log_citation]]`, `[[feedback_full_gate_and_doc_truthfulness]]`.
- **No schema / DDL / migration / config change.** `AnswerTrace.context_chunk_ids` still records the full context set; no cited subset is persisted. I-9 / R-5 unchanged; no new I-/R- number.

### Out of scope (per packet boundaries)

- `/sources` rendering only the cited chunks + empty-cited wording (Packet 2).
- Removing the all-retrieved `Contributors:` footer (Packet 3).
- `/drafts` human author-name rendering (Packet 4).
- Persisting the cited subset onto `AnswerTrace` / any schema change.
- Threading `cited_chunk_ids` onto `DispatchResult` / the Telegram adapter (done by the consuming packets that need it).
- Reopening or re-deciding the D-093 / Milestone G community-bootstrap contract.

## D-099 — Evidence-faithful attribution, Packet A: ratify the `/ask` no-evidence guardrail (empty `cited_chunk_ids` ⇒ explicit technical no-evidence reply, never free-form `answer_text`)

### Context

The "Evidence-faithful answer & source attribution" milestone (D-098) exposed `AnswerResult.cited_chunk_ids` — the LLM's used-evidence subset — as a pure additive seam, to be consumed by a cited-only `/sources` packet (Packet B) and a footer-removal packet (Packet C). Before that consuming code lands, the owner has decided to **name and lock** the runtime property that the `/sources` re-keying makes load-bearing.

Today that property is **emergent**, composed from two existing mechanisms, not stated as one contract:

- **I-9 / `parse_structured_answer`** (`src/memory_rag/core/domain/answer_schema.py`): empty `cited_chunk_ids` is permitted **only** when `uncertainty == "no_evidence"`; `"confident"` / `"uncertain"` / `"ambiguous"` therefore require non-empty citations. A free-form substantive answer cannot pass the parser with an empty cited set.
- **D-035 / R-6** (`services/query_service.py` grading → `services/dispatcher.py` `_format_answer_reply`): the free-form `answer_text` is surfaced only on `NONE` / `WEAK_EVIDENCE` / `AMBIGUOUS` (all citation-bearing); every cited-empty contour returns a fixed/templated technical reply and the LLM-marker `no_evidence` reply deliberately does not surface the model's prose.

### Decision

Ratify the guardrail as the contract of record. **Contract (verbatim):**

> If `cited_chunk_ids` is empty, `/ask` returns an explicit technical no-evidence response and MUST NOT surface free-form `answer_text`.

The guardrail **trigger** is `cited_chunk_ids == ()`; the **guarantee** is that no free-form `answer_text` reaches the user in that case. Two distinct contour classes carry an empty cited set (per the D-098 per-contour truth table), and the entry keeps them separate:

- **No-evidence contours proper** (the system found or used no evidence): empty-query `NO_EVIDENCE`; empty-merged `NO_EVIDENCE` (retrieval returned nothing); LLM-marker `no_evidence` over non-empty retrieval (the LLM declared the retrieved chunks not-evidence). These return the explicit **technical no-evidence** reply.
- **Other cited-empty technical-failure contours** (NOT no-evidence): `PROVIDER_UNAVAILABLE` (chat provider down) and `PARSE_FAILURE` (unparseable provider response). They also carry `cited_chunk_ids == ()` and also never surface free-form `answer_text`, but they are **technical failure** contours with their own retry-hint replies — they are **not** semantic no-evidence and must not be described as such.

**Milestone scope of "no evidence" = the cited-empty reading only.** The stronger notion — *citations exist but are semantically weak / do not truly support the answer* — is a **separate, future groundedness/factuality concern** owned by the Phase 7 track and is explicitly **out of scope** here. D-099 makes **no claim** that citation presence alone proves factual support; it only ratifies that an **empty** cited set blocks a free-form answer.

This is recorded via cross-reference clauses on **I-9** and **R-6** (no new invariant id, no semantic rewrite — the D-082 / D-083 / D-091 precedent), with this entry as the decision of record.

### Why

The cited-empty ⇒ no-free-form-answer property is now load-bearing for Packet B's cited-only `/sources` and must be an intentional contract, not an accident that a future refactor could silently erode. Recording it as a named guardrail with cross-references — rather than minting a parallel invariant — locks it at the invariant layer while honoring that **no runtime behavior changes**: the property already holds. Keeping the no-evidence contours proper distinct from the provider/parse technical-failure contours, and fencing the semantic-groundedness reading into Phase 7, prevents the contract from overclaiming.

### Consequence

- **Docs-only; no runtime behavior change** (the guardrail already holds; this packet does not alter any code path or user-facing reply).
- **Changed:** this D-099 entry; `docs/execution-map.md` (Packet A row inserted as the next planned packet, pre-checkpoint; pending rows relabeled B / C / D); `docs/INVARIANTS.md` (one cross-reference clause on I-9 → D-099, **no new invariant, no semantic change**); `docs/RUNTIME-INVARIANTS.md` (parallel cross-reference clause on R-6 → D-099, **no new R-number**).
- **No `src/` / `tests/` / schema / migration / config change.** I-9 / R-5 / R-6 semantics unchanged. `[[feedback_decision_log_citation]]`, `[[feedback_full_gate_and_doc_truthfulness]]`, `[[feedback_minimal_packet_docs]]`.

### Out of scope (per packet boundaries)

- The behavioral **guard test** pinning "no-evidence contours surface no `answer_text`" — a code artifact, deferred to **Packet B**.
- `/sources` cited-only rendering + the empty-cited wording "Your last /ask answer didn't cite any specific notes." + the two distinct empty contours ("never asked" vs "asked, cited nothing") — **Packet B**.
- Removing the all-retrieved `Contributors:` footer (same empty-cited semantics) — **Packet C**.
- Semantic groundedness / factuality ("citations present but insufficient") — **Phase 7** track.
- Minting a dedicated invariant id; any `todo.md` milestone section (none exists for this milestone; not gated by a concrete need here).

## D-100 — Evidence-faithful attribution, Packet B: `/sources` renders only the LLM-cited chunks

### Context

D-098 exposed `AnswerResult.cited_chunk_ids` — the LLM's used-evidence subset, an I-9 subset of `AnswerContext.ordered_chunks` — as pure plumbing with no consumer. D-099 ratified the guardrail that an empty cited set never surfaces free-form `answer_text`. Packet B is the first consumer: it makes `/sources` report only the chunks the LLM actually cited, instead of the full retrieved set.

Before this packet, `Dispatcher._update_latest_sources` cached `answer.context.ordered_chunks` (the full post-RRF retrieved set) and cleared the entry on any empty contour by *popping the key*. That had two problems: `/sources` over-reported (every retrieved chunk, not the cited ones), and the pop conflated "no prior `/ask`" with "asked, but the answer cited nothing" — both surfaced the same `_REPLY_SOURCES_NONE` reply.

### Decision

`/sources` consumes `AnswerResult.cited_chunk_ids`:

- `_update_latest_sources` stores the **cited subset** — the chunks in `answer.context.ordered_chunks` whose `chunk_id ∈ answer.cited_chunk_ids` — in post-RRF `ordered_chunks` order (the subset relation holds by I-9). Every cited-empty contour (`cited_chunk_ids == ()` per D-099 — both `NO_EVIDENCE` paths, `PROVIDER_UNAVAILABLE`, `PARSE_FAILURE`, and the no-context contour) stores an empty tuple.
- The cache write is now **always-set**: every `/ask` assigns the entry (the `.pop`-on-empty clear path is gone), so **key presence** records that an `/ask` ran at all.
- `_dispatch_sources` branches on key presence:
  - key absent (no prior `/ask` this process) → `_REPLY_SOURCES_NONE` = "No selected chunks available — ask a question with /ask first." (unchanged).
  - key present, empty tuple (prior `/ask` cited nothing) → new `_REPLY_SOURCES_NONE_CITED` = "Your last /ask answer didn't cite any specific notes.".
  - key present, non-empty → render the cited chunks (header + `source_chunks`), unchanged adapter path.
- The behavioral **guard test** D-099 deferred here lands in `tests/test_dispatcher_sources.py`: parametrized over the five D-099 cited-empty contours, asserting the model's free-form `answer_text` does not appear in the `/ask` reply. It pins the ratified property only — the exact technical reply bodies stay pinned by the D-071 sibling guards in `tests/test_dispatcher_retrieval_fallback.py`.

This consumes the D-098 seam and the D-099 guardrail; it introduces **no new `/ask` answer-path semantics** and reclassifies no contour.

### Why

`/sources` is the milestone's evidence-faithful surface: it should show what the answer was built on, not everything retrieval surfaced. Reading `cited_chunk_ids` makes it faithful; the always-set/presence cache is the minimum mechanism that separates the two empty contours the previous pop conflated. Keeping the change in the dispatcher that already owns `_latest_sources` keeps it channel-neutral and confined.

### Consequence

- `/sources` now returns only the cited chunks for a grounded `/ask`, and a distinct reply when the last `/ask` cited nothing.
- `AnswerTrace.context_chunk_ids` still records the **full** retrieved context (a superset of the cited subset) — unchanged; operator forensics are unaffected.
- The `grounding_chunks` / `Contributors:` footer seam (D-091 / D-092) is untouched — Packet C.
- **Changed:** `src/memory_rag/services/dispatcher.py` (`_update_latest_sources`, `_dispatch_sources`, new `_REPLY_SOURCES_NONE_CITED`, docstrings); `tests/test_dispatcher_sources.py` (cited-only + both empty wordings + cited-empty guard); `tests/test_telegram_sources.py` (empty-cited inline delivery; `_FixedAnswerQueryService` now sets `cited_chunk_ids`); this entry; `docs/execution-map.md` (Packet B row); `docs/RUNBOOK.md` (§"Selected-chunks recall (`/sources`, D-036)"). The D-098 seam (I-9 citation subset) and the D-099 R-6 answer-reply guardrail directly relevant to these files are preserved; no schema / DDL / migration / config change. `[[feedback_minimal_packet_docs]]`, `[[feedback_full_gate_and_doc_truthfulness]]`, `[[feedback_doc_state_truthfulness]]`, `[[feedback_sibling_wording_guard_tests]]`.

### Out of scope (per packet boundaries)

- Removing the all-retrieved `Contributors:` footer (same empty-cited semantics) — **Packet C**.
- Human author names in `/drafts` — **Packet D**.
- Persisting the cited subset durably; cross-restart / multi-worker cache durability — unchanged D-036 follow-up triggers.
- Any `QueryService` / `AnswerResult` seam widening or new fields.
- Semantic groundedness / factuality — **Phase 7** track.
- `/sources` header-wording redesign and `/sources N` argument.

## D-101 — Evidence-faithful attribution, Packet C: remove the all-retrieved `Contributors:` footer from `/ask`

### Context

The "Evidence-faithful answer & source attribution" milestone (D-098 → D-099 → D-100)
makes `/ask` + `/sources` report only the evidence the LLM actually cited
(`cited_chunk_ids`). D-098 named **two** surfaces that over-claim by rendering the full
retrieved set — the on-demand `/sources` reply and the `/ask` `Contributors:` footer
(contract D-091, code D-092, keyed on `answer.context.ordered_chunks`). D-100 fixed the
first (cited-only `/sources`). That left a cross-surface inconsistency on the *same*
answer: `/sources` shows the cited subset while the footer still credits every retrieved
contributor.

The owner chose to resolve this not by re-keying the footer onto the cited subset but by
**removing it entirely** — making `/sources` (cited-only) the single user-facing
attribution surface, eliminating the divergence and the risk of a second attribution
layer drifting in future.

### Decision

The `/ask` `Contributors:` footer is **removed as a user-facing element**, and its
footer-only seam is fully deleted:

- The Telegram webhook no longer appends a `Contributors: …` footer to grounded `/ask`
  replies; the reply is the answer text alone (plus any existing evidence-strength
  trailer).
- `DispatchResult.grounding_chunks` (D-092) — produced only for the footer and consumed
  only by it — is removed, along with the `Dispatcher` ASK derivation that set it.
- `render_contributors_footer` (D-092) is deleted from
  `adapters/telegram/author_display.py`. The shared author-resolution helpers
  (`resolve_author_display_name`, `resolve_chunk_author_display`, `render_source_block`)
  and the store protocols stay — `/sources` still uses them.

This **supersedes the user-facing rendering of D-091 / D-092** while changing **no
invariant**: authorship is still carried only as the opaque `author_user_id` (I-6),
display names are still resolved adapter-side and requester-`community_id`-scoped (D-089;
I-1 / I-7). `AnswerTrace.context_chunk_ids` still records the full retrieved context for
operator forensics. The D-091 / D-092 entries stay as historical lineage; this entry is
the forward supersession.

### Why

After D-100, the footer and `/sources` disagreed on the same answer — exactly the
over-claiming the milestone exists to remove, now observable rather than latent. Full
removal (vs. re-keying the footer to the cited subset) is the owner's choice: it keeps a
single attribution surface, leaves no dormant attribution seam to drift, and keeps the
branch story simple — D-098 + D-099 + D-100 make `/ask` + `/sources` evidence-faithful,
and the redundant footer is withdrawn.

### Consequence

- Grounded `/ask` replies (incl. `WEAK_EVIDENCE` / `AMBIGUOUS`) no longer carry a
  `Contributors:` footer; `NO_EVIDENCE` / empty-query / `PROVIDER_UNAVAILABLE` /
  `PARSE_FAILURE` replies are behaviorally unchanged (they never carried one).
- `/sources` is unchanged (cited-only, D-100) and is now the sole user-facing
  attribution surface.
- **Changed (`src/`):** `adapters/telegram/webhook.py` (drop the footer append + import),
  `services/dispatcher.py` (drop the `grounding_chunks` derivation),
  `core/routing/models.py` (delete the `DispatchResult.grounding_chunks` field + docstring),
  `adapters/telegram/author_display.py` (delete `render_contributors_footer`).
- **Changed (`tests/`):** `tests/test_telegram_ask_contributors.py` (presence tests →
  an adapter-level absence guard), `tests/test_author_display_resolution.py` (drop the
  footer-unit section), `tests/test_end_to_end_smoke.py` (assert no footer),
  `tests/test_grouped_multi_diary.py` (drop the `grounding_chunks` seam test; multi-author
  I-6 coverage retained via `context.ordered_chunks`),
  `tests/test_dispatcher_retrieval_fallback.py` (drop the `grounding_chunks` assertions;
  retain a core "composes no footer" guard).
- **Docs:** this D-101 entry; `docs/execution-map.md` (Packet C row);
  `docs/RUNBOOK.md` (remove the live footer paragraph; edit the grouped-diary footer
  mention); `docs/INVARIANTS.md` (drop the now-false I-6 footer clause; I-6 itself
  unchanged). No schema / DDL / migration / config change; no new I-/R- number.
  `[[feedback_minimal_packet_docs]]`, `[[feedback_full_gate_and_doc_truthfulness]]`,
  `[[feedback_doc_state_truthfulness]]`, `[[feedback_decision_log_citation]]`.

### Out of scope (per packet boundaries)

- Any `/sources` change (already cited-only, D-100).
- Any `AnswerResult` / `QueryService` seam change or new field.
- Human author names in `/drafts` — **Packet D**.
- Any replacement attribution UI (badges, icons, per-claim markers) — separate future
  work, not introduced here.
- Semantic groundedness / factuality — **Phase 7** track.

## D-102 — Evidence-faithful attribution, Packet D: human author names in `/drafts`

### Context

The "Evidence-faithful answer & source attribution" milestone (D-098 → D-099 → D-100 → D-101)
has two halves (execution-map "Evidence-faithful answer & source attribution"): the cited-evidence
half — `/ask` + `/sources` report only the LLM-cited set — landed in Packets 1/A/B/C; the second
half, **"present authors as human names rather than opaque numeric ids,"** was the lone remaining
**Pending** packet (Packet D). After D-101 made `/sources` the sole human-name attribution surface
(D-086 resolution), `/drafts` still rendered the raw opaque id in its block header
(`📝 <iso> · author:<author_user_id> · id:<short>`), a live cross-surface inconsistency on the same
authors — the very over-claiming the milestone exists to remove, now in the *capture-recall* surface.

### Decision

`/drafts` renders the author as a resolved display name through the existing D-086 ladder, and the
header is trimmed to `📝 <created_at ISO> · <author>`:

- New **internal, adapter-only** helper `adapters/telegram/author_display._resolve_source_author_display(source, store, *, community_id)` — leading-underscore, **not** a public seam contract. Unlike
  `resolve_chunk_author_display`, a draft is already a `SourceMessage` carrying its own
  `(external_chat_id, external_message_id, edit_seq)` snapshot key, so the helper reads
  `get_author_display_input` **directly** — no `get_source_message` bridge — and applies the
  existing public `resolve_author_display_name`. No store protocol or resolver obligation is widened.
- `community_id` (the requester-scoped community, `inbound.community_id`) is a **defensive** scope
  check (`source.community_id != community_id → opaque floor`, never reading a foreign snapshot;
  Slice 8.1.2 / D-089). Drafts are already community-scoped by `list_recent_drafts(community_id)`, so
  this guards the seam, consistent with the D-088 defensive-scoping precedent.
- `adapters/telegram/webhook._render_draft_block` gains keyword-only `store` + `community_id`,
  resolves the author, and renders `📝 <iso> · <author>`. The previous `author:<id>` and
  `id:<short>` technical segments are **dropped** (owner-chosen header). A missing / withheld
  snapshot falls through to the opaque `user-<last8>` floor — never blank, never a raise.

### Why

After D-101, `/drafts` was the last surface still exposing the opaque numeric author id while
`/sources` showed human names — exactly the inconsistency this milestone removes. Reusing the
already-present D-086 resolver (rather than minting a parallel one) and reading the snapshot
directly off the draft `SourceMessage` is the smallest change that makes the two surfaces
consistent. Keeping the helper internal honors the approved boundary "reuse the `author_display`
seam without changing its interface." Authorship is unchanged: still carried only as the opaque
`author_user_id` (I-6); the display name is non-authoritative adapter-side presentation
(I-1 / I-7 preserved).

### Consequence

- **`src/`:** `adapters/telegram/author_display.py` (new internal `_resolve_source_author_display`
  + `SourceMessage` import; existing public functions / protocols untouched);
  `adapters/telegram/webhook.py` (import the helper; `_render_draft_block` resolves the author and
  drops the `author:`/`id:` segments; the `/drafts` call site threads `store=backend_store,
  community_id=inbound.community_id`).
- **`tests/`:** `tests/test_author_display_resolution.py` (a `_resolve_source_author_display` unit
  section: three tiers; floor on missing / both-null snapshot; floor + no snapshot read on community
  mismatch; happy-path key assertion); `tests/test_telegram_drafts.py` (the `get_backend_store`
  override wired to the shared store, a snapshot-seeding helper, a three-tier integration test
  asserting no `author:` / `id:` survive, and a byte-stable `_render_draft_block` format test).
- **Docs:** this D-102 entry; `docs/execution-map.md` (Packet D row → Implemented, pre-checkpoint);
  `docs/RUNBOOK.md` (new "`/drafts` author display (D-086 / D-098)" subsection). No schema / DDL /
  migration / config change; no new I-/R- number. I-1 / I-6 / I-7 / D-089 preserved.
- **Status: pre-checkpoint.** This entry and the execution-map Packet D row stay
  **Implemented / pre-checkpoint**; they flip to **Done** only after report / checkpoint — at which
  point the milestone's A/B/C/D rows are closed together. This packet does not assert the milestone
  closed in the working tree. `[[feedback_doc_state_truthfulness]]`, `[[feedback_minimal_packet_docs]]`,
  `[[feedback_full_gate_and_doc_truthfulness]]`, `[[feedback_decision_log_citation]]`.

### Out of scope (per packet boundaries)

- Re-keying or reviving the removed `Contributors:` footer (D-101) — `/sources` + `/drafts` are the
  attribution surfaces.
- Any `/sources` / `/ask` rendering or wording change; the D-099 guardrail.
- Persisting cited subsets / `AnswerTrace` changes; visibility / multi-diary (A-15 / A-14); any
  `/drafts` semantics change beyond the rendered author.
- Changing the `author_display` public seam shape or any store protocol.
- The milestone-closure Done-flips (A/B/C/D → Done) — a distinct checkpoint act after this packet.

## D-103 — Post-attribution user-surface cleanup, Packet 1: trim the draft-save confirmation reply

### Context

Post-merge UI testing of the Evidence-faithful attribution milestone (D-098 → D-102) surfaced three user-facing roughness findings on the surfaces that milestone touched or sits beside: the draft-save confirmation, the `/drafts` header, and the `/sources` header. They cohere as a small **product-baseline surface-polish** milestone (`fix/post-attribution-surface-cleanup`), sequenced ahead of resuming the in-flight Subject-scoping milestone (H-2..H-4) because they are confirmed defects on every interaction and cheapest to fix while the surfaces are warm. This is Packet 1 — the most self-contained of the three.

Today a successful plain-text draft store replies with a two-part string: `_format_draft_reply` (`services/dispatcher.py`) returned `f"{_DRAFT_REPLY_PREFIX}{suffix}. {_DRAFT_REPLY_HINT}"`, e.g. `"Stored as draft. Send /note <YYYY-MM-DD> on the first line to commit it as a note, or /ask to query."` The trailing `/note` + `/ask` hint is noise on every plain-text message.

### Decision

- **Trim the hint.** `_format_draft_reply` now returns `f"{_DRAFT_REPLY_PREFIX}{suffix}."` — the `/note` + `/ask` hint is removed and the unused `_DRAFT_REPLY_HINT` constant deleted (single consumer).
- **Keep the R-2 replay provenance suffix (owner-decided).** Fresh store → `"Stored as draft."`; idempotent re-delivery → `"Stored as draft (replay)."`. Only the hint is removed; the requested-vs-effective-path distinction stays visible in the reply (Fallback Rule). Replay provenance also remains in logs (`effective_path=replay`).

### Why

The hint repeated promotion instructions on every draft, duplicating `/start` (`_REPLY_START`) and `/help` (`_REPLY_HELP`), which already document how to promote a draft. Removing it leaves a clean confirmation. Keeping the `(replay)` suffix preserves the Fallback Rule's "make requested and effective path distinguishable" guarantee at the user surface.

### Consequence

- **`src/`:** `services/dispatcher.py` — `_format_draft_reply` trimmed; `_DRAFT_REPLY_HINT` deleted. `_DRAFT_REPLY_PREFIX` and the `suffix` logic unchanged.
- **`tests/`:** `tests/test_telegram_reply.py` (two assertions tightened to exact equality; new `test_draft_reply_wording_and_sibling_literals_are_pinned` byte-equality guard pinning the fresh/replay replies, asserting the removed hint sentence survives in no reply literal, and pinning the sibling literals `_REPLY_START` / `_REPLY_HELP` / `_REPLY_UNKNOWN` / `_REPLY_CLARIFY`); `tests/test_end_to_end_smoke.py` (the `"/note" in …` draft assertion replaced with exact equality). The nine other `startswith("Stored as draft")` assertions stay valid.
- **Docs:** this D-103 entry; `docs/execution-map.md` (new "Post-attribution user-surface cleanup" block, Packet 1 row — Implemented, pre-checkpoint); `QUICKSTART.md` (three `# → text:` examples trimmed to `"Stored as draft."` and the now-false "The reply tells the user how to promote the draft." sentence dropped). An older historical decision-log reply quote is left untouched (a stale `/entry` snapshot — past records are not rewritten). No schema / DDL / migration / config change; no new I-/R- number. R-2 preserved.
- **Status: Done.** This entry and the execution-map Packet 1 row are **Done** as of the milestone-closure checkpoint. `[[feedback_doc_state_truthfulness]]`, `[[feedback_sibling_wording_guard_tests]]`, `[[feedback_minimal_packet_docs]]`, `[[feedback_full_gate_and_doc_truthfulness]]`.

### Out of scope (per packet boundaries)

- `/drafts` date/author header formatting (Packet 2); `/sources` header removal (Packet 3).
- Subject scoping, retrieval behavior, author resolution; schema / migrations / core domain models.
- The milestone Done-flip checkpoint (a distinct act after this packet).

## D-104 — Post-attribution user-surface cleanup, Packet 2: trim the `/drafts` header to date + author only

### Context

Second packet of the post-attribution surface-polish milestone (`fix/post-attribution-surface-cleanup`; see D-103 for the milestone framing and the three findings). D-102 made the `/drafts` block header render the human author display name and trimmed it to `📝 <created_at> · <author>`, but used `created_at.isoformat()` — a full datetime + timezone suffix (e.g. `📝 2026-05-09T10:00:00+00:00 · @alice`). The time-of-day + offset is noise on a journaling surface where the calendar date is the meaningful field.

### Decision

- **Render the header date-only.** `_render_draft_block` (`adapters/telegram/webhook.py`) now builds the header with `draft.created_at.date().isoformat()` instead of `draft.created_at.isoformat()`, so `📝 <created_at full-ISO> · <author>` becomes `📝 <created_at date> · <author>` (`YYYY-MM-DD`). `SourceMessage.created_at` is a `datetime` (`core/domain/models.py`), so `.date().isoformat()` yields the calendar date of the stored UTC timestamp.
- **Everything else byte-unchanged.** Author resolution (the D-086 ladder `@username → first_name → opaque `user-<last8>` floor`, requester-`community_id`-scoped per D-089), the `· ` separator, the `\n\n` blank line, and the verbatim `{draft.raw_text}` body are untouched. This is an adapter-only rendering change.

### Why

The full ISO datetime exposed implementation detail (UTC offset, seconds) that the user does not need to read on every draft. A bare date keeps `/drafts` scannable and consistent with the date-first framing of the journal. Rendering the UTC `created_at`'s date (no timezone normalization or user-local conversion) keeps the change minimal and behavior-preserving for everything but the header precision — that asymmetry is deliberately left for a future packet if it ever matters.

### Consequence

- **`src/`:** `adapters/telegram/webhook.py` — one line in `_render_draft_block` (`.isoformat()` → `.date().isoformat()`). Sole caller (the `/drafts` outbound branch) and the helper signature are unchanged.
- **`tests/`:** `tests/test_telegram_drafts.py` — the `test_render_draft_block_format_is_byte_stable` expected literal updated from `"\U0001f4dd 2026-05-09T10:00:00+00:00 · @alice\n\nwalked the dog"` to `"\U0001f4dd 2026-05-09 · @alice\n\nwalked the dog"` (fixture `created_at=datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC)`). The nine other `/drafts` tests reference only the `· <author>` segment and stay green.
- **Docs:** this D-104 entry; `docs/execution-map.md` (Packet 2 row → Implemented, pre-checkpoint); `docs/RUNBOOK.md` (the `/drafts` author-display note's header literal `📝 <created_at ISO>` → `📝 <created_at date>` — a same-packet truthfulness fix, the change made the quoted literal false). The D-102 decision-log entry and execution-map row are historical and left untouched. No schema / DDL / migration / config change; no new I-/R- number. Supersedes only the header-format half of D-102; D-102's author-resolution decision stands.
- **Status: Done.** This entry and the execution-map Packet 2 row are **Done** as of the milestone-closure checkpoint. `[[feedback_doc_state_truthfulness]]`, `[[feedback_sibling_wording_guard_tests]]`, `[[feedback_minimal_packet_docs]]`, `[[feedback_full_gate_and_doc_truthfulness]]`.

### Out of scope (per packet boundaries)

- `/sources` header removal (Packet 3).
- Any author-resolution behavior change; the `created_at` source field, timezone normalization, or user-local time conversion.
- Subject scoping, retrieval behavior; schema / migrations / core domain models.
- The milestone Done-flip checkpoint (a distinct act after this packet).

## D-105 — Post-attribution user-surface cleanup, Packet 3: remove the `/sources` header line

### Context

Third and final packet of the post-attribution surface-polish milestone (`fix/post-attribution-surface-cleanup`; see D-103 for the milestone framing and the three findings). Packets 1 (D-103) and 2 (D-104) are landed. A populated `/sources` reply led with a header line — `_dispatch_sources` (`services/dispatcher.py`) returned `reply_text = f"Selected chunks for your last /ask ({len(chunks)} chunk(s)):"`, which the Telegram adapter packed ahead of the rendered source blocks. The chunk count is already implicit in each block's `(i/N)` index, so the header is redundant noise on every populated `/sources`.

### Decision

- **Drop the header on the populated branch.** `_dispatch_sources` now returns `reply_text=""` on the populated branch; the reply is the source blocks alone. `route`, the opaque `source_chunks` carried to the adapter, and `metadata` (incl. `returned=str(len(chunks))`) are unchanged.
- **No adapter or packer change.** The adapter packs `reply_text` + blocks via `pack_drafts_into_messages` (`adapters/telegram/drafts_packing.py`). Its existing `if not current:` branch already absorbs an empty header — the first block becomes the running message with no leading separator and no empty leading message; the `messages or [header]` fallback can only emit `[""]` when there are zero blocks, which the populated branch (past the `if not chunks:` guard) never reaches. The packer stays generic, so `/drafts` packing is unaffected.
- **Both empty contours byte-identical.** No prior `/ask` → `"No selected chunks available — ask a question with /ask first."` (`_REPLY_SOURCES_NONE`); last `/ask` cited nothing → `"Your last /ask answer didn't cite any specific notes."` (`_REPLY_SOURCES_NONE_CITED`). Only the populated header is removed.

### Why

The header duplicated information the user can already see: the per-block `[YYYY-MM-DD] (i/N)` line carries both ordering and the total `N`. Removing it leaves a clean blocks-only reply, consistent with the surface-polish framing of the milestone. Representing "no header" as an empty `reply_text` reuses the packer's existing empty-header behavior rather than adding an adapter branch.

### Consequence

- **`src/`:** `services/dispatcher.py` — `_dispatch_sources` populated branch returns `reply_text=""` (header line + its f-string deleted). No other `src/` change; the adapter and packer are untouched.
- **`tests/`:** `tests/test_dispatcher_sources.py` — the two populated header asserts tightened to `reply_text == ""`; the two empty-contour literals stay byte-pinned by the existing `test_sources_without_prior_ask_fails_closed` / `test_never_asked_and_cited_nothing_replies_are_byte_distinct` (sibling-wording guard already in place). `tests/test_telegram_sources.py` — the combined-message body assert now expects the first source block (`[2026-05-09] (1/2)`) with an explicit `"Selected chunks for your last /ask" not in body`; the oversized-split assert expects message 1 to start with `[2026-05-09] (1/3)` with the removed header absent from every message.
- **Docs:** this D-105 entry; `docs/execution-map.md` (Packet 3 row → Implemented, pre-checkpoint). `docs/RUNBOOK.md` and `QUICKSTART.md` are **not** touched — neither asserts a populated `/sources` header line, so the change makes no sentence there false (RUNBOOK's "`(i/N)` block header" phrase refers to the per-block date/index line, not the removed reply header). The historical D-036 reply-text quote and the D-098-era relocation note are left untouched — past records are not rewritten. No schema / DDL / migration / config change; no new I-/R- number. Supersedes only the header-presence half of D-036; D-036's cited-only selection and the D-086 author-resolution decisions stand.
- **Status: Done.** This entry and the execution-map Packet 3 row are **Done** as of the milestone-closure checkpoint; this closes the Post-attribution user-surface cleanup milestone (D-103 → D-105). `[[feedback_doc_state_truthfulness]]`, `[[feedback_sibling_wording_guard_tests]]`, `[[feedback_minimal_packet_docs]]`, `[[feedback_full_gate_and_doc_truthfulness]]`.

### Out of scope (per packet boundaries)

- Any change to the two empty-`/sources` contours beyond preserving their wording.
- Source-block body format, the `(i/N)` index, cited-only behavior, `_latest_sources` cache semantics, retrieval / answer-path, author resolution; schema / migrations / core domain models.
- Subject scoping (H-2..H-4) and any other milestone.
- The milestone Done-flip checkpoint and PR preparation (distinct acts after this packet).
