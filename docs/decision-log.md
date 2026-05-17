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
