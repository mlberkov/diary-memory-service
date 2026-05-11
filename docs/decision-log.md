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
