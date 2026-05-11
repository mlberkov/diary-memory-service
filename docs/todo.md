# Backlog

Top of list = pick next. Each item maps to a row in `docs/execution-map.md`. When a slice is done, remove it and add the next downstream slice.

## Phase 4 — Grounded answer pipeline (next)
- Owner: agent
- Map: execution-map 4.1 → 4.4
- Concrete: build the answer side of R-5 on top of the now-persisted retrieval-side traces (D-032). Context assembler over the merged `retrieval_hits`; versioned answer prompt; structured answer schema with explicit fallback modes (no-evidence, weak-evidence, ambiguous, provider-unavailable); evidence rendering in the Telegram reply. Persistence: `AnswerTrace(query_id, prompt_version, context_chunk_ids, answer_text, confidence_band, fallback_mode, model_name, token_counts, latency_ms, created_at)` — its own table, FK to `queries.query_id`.

## Next quality-decision packet — search-quality fork
- Owner: agent + human (decision boundary)
- Map: execution-map 3.3 follow-up
- Concrete: evaluate retrieval quality improvements against the D-025 baseline (exact dense scan + Postgres FTS `simple` + service-layer RRF). Decide between, at minimum: **BM25-grade sparse** (e.g. via the `pg_search` extension, the `bm25_catalog` extension, or an app-side BM25 over tokenized chunks); a **reranker / cross-encoder** layer; **Qdrant or another dedicated vector / search system**; multilingual sparse tuning beyond `simple` (e.g. mixed Russian/English support); the **3072-dim ANN strategy** (A-36b: halfvec + HNSW vs alternatives) when corpus scale demands it. Bound the packet — do not bundle all of these. Pick one or two with the largest expected lift, measure them, and record the rest as deferred.

## Slice 3.4 — Metadata filtering (after 3.3)
- Owner: agent
- Map: execution-map 3.4
- Concrete: layer family / child / visibility / date filters onto the existing `SearchRepository` legs without changing the retrieval shape. Coordinate with A-15 (visibility scopes).

## Schema evolution before non-local deployment
- No migration tool is wired yet (A-34). Local Postgres schema upgrades are destructive: pull a packet that changes columns and you must `docker compose down -v` to reset `diary_pg_data` before the bootstrap DDL applies. This is acceptable for the single-dev contour but must be replaced (Alembic or equivalent) before the first non-local deployment. D-024 added the pgvector image, `embedding_records`, and the `embedding_status` column; D-025 added the generated `chunk_text_tsv` column + GIN index — both required a destructive upgrade or an explicit `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...` step. Consider a dedicated packet once the next production-shaped slice is on the horizon.

## Reconciliation for failed embeddings (Phase 6 candidate)
- A-35 leaves failed embeddings sticky: a chunk with `embedding_status='failed'` stays that way until manual intervention. Once Phase 6 (provider hardening) is on the horizon, ship a reconciliation job that retries `failed` chunks with bounded backoff and a dead-letter strategy, plus the corresponding observability (logs / metrics on retry success/failure).

---

Closed in the Slice 3.5 retrieval-trace persistence packet (D-032):
- `src/diary_rag/core/diary/models.py` — `RetrievalLeg` (`StrEnum`), `Query`, `RetrievalHit` channel-neutral dataclasses; exported from `core/diary/__init__.py`.
- `src/diary_rag/services/retrieval.py` — `reciprocal_rank_fusion` now returns `list[FusedHit]` so the fused RRF score persists on merged rows; tie-breaking and `DEFAULT_RRF_K = 60` unchanged.
- `src/diary_rag/services/query_service.py` — `QueryService.__init__` takes `(repo, search_repo, embedding_client, *, top_k, candidate_k)`; every `answer()` call writes one `Query` row plus per-leg + merged `RetrievalHit` rows (per-leg score = RRF contribution `1.0 / (RRF_K + rank)`, merged score = fused RRF score). Empty-query and empty-merged paths still persist the `Query` row with zero hits. The `retrieval.hybrid` log line gains `query_id=…` and `fallback=…`.
- `src/diary_rag/storage/repository.py` — `DiaryRepository` Protocol gains `save_query`, `save_retrieval_hits`, `get_query`, `get_retrieval_hits_for_query` (the latter ordered by `(leg ASC, rank ASC)` for stable inspection).
- All three backends implement the new seam fully: `MockDiaryStore` (process-local dicts), `SqliteDiaryStore` (new `queries` + `retrieval_hits` tables in the in-file DDL), `PostgresDiaryStore` (new tables in `schema.sql` with `UNIQUE (query_id, chunk_id, leg)`, `idx_queries_family_id`, `idx_retrieval_hits_query_id`, FK to `event_chunks`). SQLite's retrieval-side `dense_candidates` / `sparse_candidates` continue to raise `NotImplementedError` (D-025 unchanged).
- `src/diary_rag/adapters/telegram/webhook.py` passes the store object twice into `QueryService` (it satisfies both `DiaryRepository` and `SearchRepository` structurally via `HybridDiaryStore`).
- New tests: `tests/test_storage_query_traces.py` covers mock + sqlite + postgres parity for save/get of queries and hits, ordering, no-evidence-with-zero-hits, and the `UNIQUE (query_id, chunk_id, leg)` constraint on sqlite/postgres.
- Extended tests: `tests/test_query_service.py` adds three persistence cases (successful-with-hits, no-evidence-with-zero-hits, empty-query-with-zero-hits); `tests/test_retrieval_rrf.py` updated to the new `FusedHit` shape plus a score-monotonicity assertion; `tests/test_end_to_end_smoke.py` extended with the two persistence assertions on the existing success and no-evidence cases; `tests/test_dispatcher_drafts.py`, `tests/test_telegram_export.py`, `tests/test_telegram_reply.py`, `tests/test_telegram_drafts.py`, `tests/test_end_to_end_smoke.py` updated for the new three-arg `QueryService` constructor.
- Docs: D-032 in `decision-log.md`. I-9 in `INVARIANTS.md` and R-5 in `RUNTIME-INVARIANTS.md` tightened in place to record that retrieval-side trace persistence is enforced; answer-side `AnswerTrace` still pending Phase 4. `RUNBOOK.md` gains a "Retrieval traces" subsection with two operator SQL one-liners (recent traces; no-evidence only) and the standard A-34 destructive-upgrade note. `execution-map.md` row 3.5 updated. `todo.md` opens Phase 4 (grounded answer pipeline) as the next slice.
- A-34 destructive-upgrade discipline applies to existing local Postgres volumes that pre-date the two new tables; reset with `docker compose down -v` or run the new `CREATE TABLE` / `CREATE INDEX` statements manually.
- **Explicitly not in this packet:** `AnswerTrace` persistence (Phase 4); metadata filtering / Slice 3.4; retrieval-quality changes; BM25 / reranker / Qdrant / halfvec / HNSW; user-facing `/trace` command; schema migration tooling; Telegram adapter wording; renames deferred under D-026; broader TechSpec §5 alignment for the deferred `Query.source_message_id` / `Query.author_user_id` / `RetrievalHit.score_dense|sparse|hybrid` fields.

Closed in the Slice 3.3 baseline hybrid retrieval packet (D-025):
- `src/diary_rag/storage/search_repository.py` — `SearchRepository` Protocol (`dense_candidates`, `sparse_candidates`) + `HybridDiaryStore` (combined ingest + retrieval).
- `src/diary_rag/services/retrieval.py` — pure service-layer Reciprocal Rank Fusion (RRF, k=60); no calibration, no reranker.
- Postgres dense leg: exact family-scoped scan over `vector(3072)` with `embedding <=> %s::vector`, `embedding_status='ready'` + `model_name` filter. No HNSW; A-36 replaced by A-36b (halfvec/HNSW deferred to next quality-decision packet).
- Postgres sparse leg: generated stored column `event_chunks.chunk_text_tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', chunk_text)) STORED` + GIN index; `websearch_to_tsquery('simple', $q)` ranked by `ts_rank_cd`. A-37 (sparse dictionary `simple`) opened.
- Mock backend: deterministic dense (cosine + 0.5 distance threshold so unrelated queries don't fabricate matches) and sparse (whitespace token overlap). `MockEmbeddingClient` provenance unchanged.
- SQLite backend: `dense_candidates` / `sparse_candidates` raise `NotImplementedError`; dispatcher catches and returns `FallbackMode.NO_EVIDENCE` with a `retrieval.unavailable` log line. SQLite remains opt-in for ingest.
- `DiaryRepository.search_chunks` removed; `DiaryRepository.get_event_chunk(chunk_id)` added as the small chunk-by-id read primitive.
- `QueryService` rewritten: constructor takes `SearchRepository` + `EmbeddingClient`; embeds query once; calls both legs; RRF-merges; logs `retrieval.hybrid family_id=… model=… dense_n=… sparse_n=… merged_n=…`. Two new `Settings` knobs: `retrieval_top_k` (5), `retrieval_candidate_k` (20).
- Dispatcher: reply trailer changes to `(hybrid retrieval — dense+sparse RRF)`; the no-evidence reply drops the substring parenthetical.
- Docs: D-025 in `decision-log.md`. A-6, A-29, A-36 closed (A-36 replaced by A-36b). A-37 opened. I-8 updated in place to record that hybrid retrieval is now enforced rather than declared. R-4 updated to record the `ready`-only filter on dense.
- New tests: `tests/test_retrieval_rrf.py`, `tests/test_search_repository_mock.py`, `tests/test_search_repository_postgres.py`, `tests/test_dispatcher_retrieval_fallback.py`. Existing tests adjusted: `test_query_service.py` rewritten around hybrid; substring assertions removed from `test_postgres_store.py` / `test_sqlite_store.py`; `test_end_to_end_smoke.py` trailer updated; `test_indexing_pipeline.py` uses `get_event_chunk` instead of substring.
- **Explicitly not in this packet:** BM25, reranker / cross-encoder, Qdrant or any external vector/search system, halfvec / HNSW migration, metadata filters (3.4), retrieval traces (3.5), multilingual sparse tuning, query-embedding caching, migration tool (A-34 unchanged).

Closed in the Phase 3.1+3.2 embedding-adapter + sync-indexing packet (D-024):
- `core/embeddings/{client,models}.py` — `EmbeddingClient` Protocol, `EmbeddingRecord`, `EmbeddingStatus`.
- `adapters/embeddings/{mock,openai_client,factory}.py` — `MockEmbeddingClient` (honest `model_name="mock"`, dimension=3072), `OpenAIEmbeddingClient` (`text-embedding-3-large`, passes `dimensions=3072` explicitly), and the single `build_embedding_client(settings)` factory used by both the boot gate and the dispatcher.
- `DiaryRepository` Protocol gains `save_embedding_records`, `count_embedding_records_for_source`, `set_chunk_embedding_status`; all three backends (mock / sqlite / postgres) implement them.
- Postgres schema: `CREATE EXTENSION vector`, `embedding_records` with `vector(3072)`, `event_chunks.embedding_status TEXT NOT NULL DEFAULT 'pending'` with CHECK on the StrEnum. No ANN index — pgvector's HNSW/IVFFlat cap at 2000 dim (A-36 deferred to Slice 3.3).
- SQLite: `embedding_records` with little-endian f32 `BLOB`; same `embedding_status` column and CHECK.
- `DiaryService.ingest` calls the embedding client after `save_event_chunks` commits; success → `EmbeddingRecord` rows + `embedding_status='ready'`; failure → `embedding_status='failed'` + zero records + `FallbackMode.NONE` (I-2, I-3); replay short-circuits before the embedding step (R-2 extension).
- `create_app` boot gate (R-10 partial): refuses to start when `EMBEDDING_DIMENSION ≠ 3072`, when `EMBEDDING_BACKEND=openai` with the wrong model or no API key, or when `STORAGE_BACKEND=postgres` and the connected database lacks the `vector` extension.
- `docker-compose.yml`: `postgres:16-alpine` → `pgvector/pgvector:pg16`. Destructive volume reset required (A-34).
- `pyproject.toml`: `openai` and `pgvector` runtime deps; mypy `ignore_missing_imports` for `pgvector.*`.
- `.env.example`: new `EMBEDDING_BACKEND`, default `EMBEDDING_MODEL=text-embedding-3-large`, `EMBEDDING_DIMENSION=3072`.
- New tests: `test_embedding_client_mock.py`, `test_indexing_pipeline.py` (parametrised across mock / sqlite / postgres backends), `test_boot_dimension_gate.py`. Optional/manual: `test_embedding_client_openai.py` (gated by `DIARY_RAG_OPENAI_TEST_KEY`; **not** in the standard packet gate). Extended `test_diary_service.py` for fresh-ingest / replay / failure paths.
- Docs: D-024 in `decision-log.md`. Closed A-5 / A-7 / A-8; opened A-35 (sync indexing, no auto-retry) and A-36 (3072-dim ANN strategy is open). R-10 wording tightened in `RUNTIME-INVARIANTS.md`. RUNBOOK, QUICKSTART, README, execution-map updated.

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
