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
