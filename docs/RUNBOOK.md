# Runbook — Working in this Repo

## Roles
- **Human owner** — sets product direction, approves assumptions and decisions, owns merges.
- **AI agent (Claude Code, etc.)** — drafts docs, code, and tests under the rules in `AGENTS.md` and `CLAUDE.md`.

## Canonical loop

1. **Read.** Open the canonical docs in the order set by `CLAUDE.md`. Skim recent decision-log entries.
2. **Pick.** Take the top item in `docs/todo.md`. Confirm it maps to a row in `docs/execution-map.md`.
3. **Plan.** State the slice's goal, the files it will touch, the invariants involved, the test surface, and the fallback paths. Surface every assumption.
4. **Align docs.** If the slice implies new behavior not in the canonical docs, surface the mismatch and propose the smallest fix *before* coding.
5. **Implement.** Smallest viable end-to-end slice. Mock before real. Pure functions over services where possible.
6. **Verify.** Run `make check` (when it exists) and the slice's tests. Walk through the runtime invariants for the slice's path.
7. **Update docs.** `decision-log.md` for decisions, `assumptions.md` for new open items, `todo.md` for remaining work, `execution-map.md` for new files.
8. **Commit.** Phase-aligned, small, readable.

## When canonical docs disagree with a request
- Stop. Do not silently comply.
- Quote the specific canonical text and the conflicting request.
- Propose the smallest consistent resolution: either change the request, or update the canonical doc with a new decision-log entry.

## When a runtime fallback fires
- Confirm the requested vs effective path was logged (R-6).
- Confirm the answer carried the right `fallback_mode` (R-5).
- If neither held, treat as an incident: write a decision-log entry and add an invariant if needed.

## When provider behavior degrades (Phase 6+)
- Check provider call logs (R-7).
- Confirm bounded retries (R-9) actually triggered.
- Verify durable state is intact (raw `SourceMessage` rows present; no chunks orphaned).
- Reprocess from raw via the replay path; do not hand-fix derived state.

## Local commands

The toolchain is **Python 3.11 + uv + Ruff + Mypy + Pytest** (D-016 / D-017 / D-018). Slice 1.1 wired all targets below to real commands.

- `make init` — print `uv` and Python versions.
- `make sync` — `uv sync --all-extras`.
- `make format` — Ruff format + Ruff lint autofix.
- `make lint` — Ruff lint + format check (no writes).
- `make typecheck` — Mypy strict.
- `make test` — Pytest.
- `make check` — runs `lint` + `typecheck` + `test`.
- `make run` — boot the FastAPI shell on `127.0.0.1:8000` (Slice 1.1 `/health`; Telegram webhook in Slice 1.2).
- `make tree` — show the top of the repo tree.
- `make clean` — remove caches and build artifacts.

### Local Postgres
The canonical durable backend (D-022) runs via `docker compose up -d postgres`. Set `STORAGE_BACKEND=postgres` and the standard `POSTGRES_*` env vars. The compose image is `pgvector/pgvector:pg16` (D-024) so the `vector` extension is available for the embedding seam. See `QUICKSTART.md` "Durable local store (Postgres)" for the full smoke flow.

### Embedding backend (D-024)
Phase 3.1+3.2 ships with a dual contour:

- `EMBEDDING_BACKEND=mock` (default) — deterministic in-process stand-in. `model_name` on persisted rows is the literal string `mock`, so SQL inspection alone tells you which provider produced a row.
- `EMBEDDING_BACKEND=openai` — calls `text-embedding-3-large` with `dimensions=3072` explicitly. Requires `OPENAI_API_KEY`. Single attempt; no retries (Phase 6 owns hardening).

The boot gate (R-10) refuses to start when `EMBEDDING_DIMENSION` is not `3072`, when `EMBEDDING_BACKEND=openai` and `EMBEDDING_MODEL` is not `text-embedding-3-large`, when the OpenAI key is missing under the openai backend, or when the connected Postgres lacks the `vector` extension.

#### Failed embeddings
On any provider exception during ingest, the chunks remain persisted, their `embedding_status` flips to `failed`, and zero `embedding_records` are written for that source. The ingest result still returns `FallbackMode.NONE` because raw + chunks survived (I-2, I-3). Inspect:

```bash
docker compose exec -T postgres psql -U postgres -d theygrow_diary_rag -c \
  "SELECT chunk_id, source_message_id, chunk_text, embedding_status
     FROM event_chunks
    WHERE embedding_status = 'failed'
    ORDER BY created_at DESC;"
```

There is no auto-retry (A-35). Replay (R-2) does not re-embed. A future Phase-6 reconciliation packet will add bounded retries and a dead-letter strategy.

#### Destructive local schema upgrades
There is no migration tool yet (A-34). `schema.sql` is bootstrapped via `CREATE TABLE / CREATE INDEX IF NOT EXISTS`, which does **not** apply changes to columns or constraints on tables that already exist in a stale volume. When pulling a packet that adds or alters columns or constraints (e.g. D-023's `external_message_id`, `edit_seq`, and the `UNIQUE` idempotency constraint; D-024's pgvector image swap + `embedding_records` table + `event_chunks.embedding_status` column; D-025's generated `event_chunks.chunk_text_tsv` column + GIN index; R-2's `entry`→`note` rename — the `notes` table + its columns, `event_chunks.note_id`, and the `detected_route` CHECK now listing `'note'`), reset the local Postgres volume:

```
docker compose down -v
docker compose up -d postgres
```

This drops `diary_pg_data` along with any locally-ingested rows. If you want to keep local data, the smallest non-destructive workaround for the D-025 schema change is the explicit ALTER:

```sql
ALTER TABLE event_chunks ADD COLUMN IF NOT EXISTS chunk_text_tsv tsvector
  GENERATED ALWAYS AS (to_tsvector('simple', chunk_text)) STORED;
CREATE INDEX IF NOT EXISTS idx_event_chunks_chunk_text_tsv
  ON event_chunks USING GIN (chunk_text_tsv);
```

Production schema evolution must be solved before any non-local deployment.

### Chat backend (D-037)
Slice 4.5 ships with a dual contour:

- `CHAT_BACKEND=mock` (default) — deterministic in-process stand-in. `model_name` on persisted `AnswerTrace` rows is the literal string `mock`, so SQL inspection alone tells you which provider produced a row.
- `CHAT_BACKEND=openai` — calls `chat.completions.create` with `response_format={"type": "json_object"}` and `temperature=0`. Requires `OPENAI_API_KEY`. Single attempt; no retries (Phase 6 owns hardening, R-9).

The boot gate (R-10) refuses to start when `CHAT_BACKEND=openai` and `CHAT_MODEL` is not the canonical `gpt-4.1`, or when the OpenAI key is missing under the openai backend. The non-empty `model_name` check from D-034 is unchanged.

`OpenAIError` and `TimeoutError` from the SDK boundary are translated to `ChatProviderUnavailableError` so the existing D-035 grading writes the call as `FallbackMode.PROVIDER_UNAVAILABLE` and the dispatcher emits the retry-hint reply. `answer_text=""`, `token_counts={}`, `latency_ms=0` per D-035's truthful-trace table.

Live calls are not part of `make check`. The optional smoke `tests/test_chat_client_openai.py` is skipped unless `DIARY_RAG_OPENAI_TEST_KEY` is set (same gating pattern as the live embedding smoke and the live Postgres tests).

### Webhook idempotency (R-2 / D-023)
Repeated delivery of the same Telegram message-state — same `(external_chat_id, external_message_id, edit_seq)` — does not create duplicate rows. The webhook returns the same functional 200 reply and logs `effective_path=replay` instead of `fresh`. Operationally, `effective_path=replay` is normal; investigate only if the *first* call for a given key never appears with `effective_path=fresh`.

### Retrieval traces (D-032)
Every `/ask` call writes one row to `queries` and zero-or-more rows to `retrieval_hits` so an operator can inspect what each leg saw and what survived RRF without rerunning the query. Successful retrieval persists per-leg rows (one per chunk in `dense_candidates`, one per chunk in `sparse_candidates`) plus merged rows (one per chunk in the RRF-fused top-k). `NO_EVIDENCE` (empty query or empty merged set) persists the `Query` row with zero `retrieval_hits` rows.

Most recent traces, full picture across legs:

```sql
SELECT q.query_id, q.created_at, q.query_text, q.fallback,
       h.leg, h.rank, h.score, h.chunk_id
  FROM queries q LEFT JOIN retrieval_hits h ON h.query_id = q.query_id
 WHERE q.family_id = '<chat_id>'
 ORDER BY q.created_at DESC, h.leg, h.rank
 LIMIT 50;
```

Failed answers only (queries where retrieval found nothing):

```sql
SELECT q.query_id, q.created_at, q.query_text
  FROM queries q
 WHERE q.family_id = '<chat_id>' AND q.fallback = 'no_evidence'
 ORDER BY q.created_at DESC
 LIMIT 20;
```

The `score` column carries the RRF contribution per leg (`1.0 / (RRF_K + rank)` with `RRF_K = 60`) on dense/sparse rows and the fused RRF score on merged rows; backend-native scores (cosine distance, `ts_rank_cd`) are intentionally not surfaced (D-025 / D-032). `model_name` carries the embedding model on dense and merged rows and the FTS dictionary string `"simple"` on sparse rows.

A-34 destructive-upgrade discipline applies: existing local Postgres volumes that pre-date the `queries` and `retrieval_hits` tables must be reset via `docker compose down -v` before the bootstrap DDL applies cleanly.

### Answer traces (D-034, D-035)
Every `/ask` reply writes one row to `answer_traces` (FK to `queries.query_id`, UNIQUE on `query_id`) so an operator can inspect the LLM-side outcome and provenance per reply. `Query.fallback` and `AnswerTrace.fallback_mode` are always equal — the service writes them as one decision per call (D-035).

`fallback_mode` values and what each one means:

- `none` — success. `answer_text` is the LLM-produced reply; `context_chunk_ids` mirrors the chunks sent; `latency_ms` / `token_counts` come from the provider.
- `no_evidence` — two sub-paths share this value:
  - **Empty retrieval** (also empty query): `context_chunk_ids` is empty, `answer_text` is `""`, `latency_ms=0`, `token_counts={}` — no LLM call ran.
  - **LLM marker**: retrieval returned chunks but the model emitted `uncertainty="no_evidence"`. The trace keeps the retrieved `context_chunk_ids` for forensics and `answer_text` is the LLM's response. The dispatcher reply distinguishes the two paths.
- `weak_evidence` — LLM emitted `uncertainty="uncertain"`. Trace has the LLM output and the retrieved context.
- `ambiguous` — LLM emitted `uncertainty="ambiguous"`. Trace has the LLM output and the retrieved context.
- `provider_unavailable` — the chat client raised `ChatProviderUnavailableError`. `answer_text=""`, `token_counts={}`, `latency_ms=0`; `context_chunk_ids` is what *would* have been sent.
- `parse_failure` — the chat returned text that `parse_structured_answer` rejected. `answer_text` is `response.raw_text` (truthful provenance for forensics); `token_counts` and `latency_ms` come from the response.

Most recent answer traces joined to their query:

```sql
SELECT q.created_at, q.query_text, a.fallback_mode, a.model_name,
       a.latency_ms, a.prompt_version, a.context_chunk_ids, a.answer_text
  FROM queries q JOIN answer_traces a ON a.query_id = q.query_id
 WHERE q.family_id = '<chat_id>'
 ORDER BY q.created_at DESC
 LIMIT 20;
```

A-34 destructive-upgrade discipline applies: existing local Postgres volumes that pre-date the Slice 4.3b CHECK widening on `queries.fallback` and `answer_traces.fallback_mode` must be reset via `docker compose down -v` before the bootstrap DDL applies cleanly. Real provider adapters remain deferred to Phase 6.

### Selected-chunks recall (`/sources`, D-036)
`/sources` exposes the **selected chunks as-is** for the chat's most recent `/ask` turn: the post-RRF top-k chunks `services/context_assembler.assemble_answer_context` produced and `build_answer_prompt` fed to the LLM — i.e. the same `chunk_id` list `AnswerTrace.context_chunk_ids` records, rendered with `note_date`, `chunk_id`, and the full `chunk_text` verbatim. It is not citations, not fine-grained attribution, and not the full pre-RRF candidate pool. Outbound delivery is one Telegram message by default and splits across multiple messages only when the 4096-char cap forces it (whole-block boundaries; `(part k/N)` footers on an oversized single chunk; identical packing semantics to `/drafts`).

The state behind `/sources` is a process-local `Dispatcher._latest_sources: dict[str, tuple[EventChunk, ...]]` keyed by `family_id`. The current FastAPI wiring at `adapters/telegram/webhook.py` makes `Dispatcher` a module-level singleton via `get_dispatcher()`, so `/ask` and a follow-up `/sources` are served by the same instance within one process. **Every `/ask` dispatch updates the cache**: non-empty `answer.context.ordered_chunks` overwrites; empty (empty-query, empty-retrieval `NO_EVIDENCE`, retrieval-unavailable on SQLite) clears. Non-`/ask` routes never touch the cache. `/sources` itself is read-only.

Fail-closed: when nothing is cached, `/sources` returns `"No selected chunks available — ask a question with /ask first."` via the inline `sendMessage` body — no outbound HTTP call. The fail-closed reply also fires after process restart and after any `/ask` that produced no retrieval.

Multi-worker caveat: each uvicorn worker / pod holds its own dispatcher singleton, so `/ask` on worker A followed by `/sources` on worker B will fail closed (or return stale chunks). The current contour is single-process local dev; promoting the cache to a durable seam (e.g. `DomainRepository.get_latest_answer_trace_for_family(family_id)` + per-chunk lookups via `get_event_chunk`) is the named follow-up trigger if the deployment shape flips.

### Retrieval-quality inspection harness (D-038)
`src/diary_rag/eval/retrieval/` ships a hand-curated harness that measures the D-025 baseline contour against a small fixture corpus + gold-query set. It is **inspection, not a gate** — the CLI exit code is always `0` regardless of the observed metrics.

Two modes share one metric shape (aggregate `recall@{5,10,20}`, `mrr@20`, `per_leg_recall@20.{dense,sparse,fused}`; per-query top-`candidate_k` chunk-id lists, diagnostic per-leg first-relevant-rank fields, and an explicit `reciprocal_rank_in_fused` numerator):

- **Mock mode.** Runs under `make check` via `tests/test_retrieval_harness_shape.py`. Shape-only assertions, no quality thresholds. Also smokeable directly:

  ```bash
  uv run python -m diary_rag.eval.retrieval --mode mock
  ```

- **Postgres mode (operator baseline).** Truncates `embedding_records`, `event_chunks`, `notes`, `source_messages` on the connected DSN, then re-ingests `eval/retrieval/corpus.jsonl` through the canonical `DomainService.ingest` path. Point the DSN at a **dedicated eval database** so production data is never touched:

  ```bash
  DIARY_RAG_PG_TEST_DSN=postgresql://... \
  EMBEDDING_BACKEND=openai \
  OPENAI_API_KEY=... \
  uv run python -m diary_rag.eval.retrieval --mode postgres --json | tee snapshot.json
  ```

  Live OpenAI is used on the **corpus side** at ingest time because D-025's dense leg filters by `model_name` and the cached query embeddings are pinned to `text-embedding-3-large` — mixing models is silently broken (the harness aborts on `model_name` mismatch rather than returning zero hits). Live OpenAI on the corpus side is acceptable here because the operator chose this run deliberately; `make check` never enters this path.

  After the run, paste the aggregate metrics plus 2–3 illustrative per-query rows into the D-038 "Baseline snapshot (observed)" subsection in `docs/decision-log.md` — framed as observed values for the D-025 contour, not as a must-beat threshold for any future packet.

#### Query-embeddings cache (`eval/retrieval/embeddings_cache.json`)
The cache pins query embeddings to a specific `text-embedding-3-large` @ 3072-dim point-in-time output so the Postgres run is reproducible without contacting OpenAI on the query side. Regenerate is an operator-only ritual:

```bash
OPENAI_API_KEY=... uv run python -m diary_rag.eval.retrieval.regenerate_embeddings [--force]
```

`--force` is required to overwrite an existing cache because regenerating **invalidates prior baseline snapshots** — the model output drifts. The script writes `model_name` and `dimension` into the file; the Postgres-mode CLI checks these against the configured corpus-side embedding client and aborts on mismatch.

The cache is **not** committed by the D-038 implementation packet — it is produced by this ritual. Postgres-mode refuses to start if the cache is missing.

#### Gold-set handle contract
`expected_handles` entries in `eval/retrieval/gold.json` use the form `"{external_message_id}#{event_index}"` where `event_index` is the 0-based ordinal of the produced `EventChunk` within the source message after `DomainService.ingest` chunks it. This is internal to the harness only — it is **not** a business event id, **not** a Telegram message id, **not** any external domain identifier. It exists because `chunk_id` is uuid4 at ingest time.

### Hybrid retrieval (D-025)
`/ask` runs the baseline hybrid path: a single query-embedding call followed by dense + sparse legs against `SearchRepository`, fused with service-layer RRF. Every retrieval call logs `retrieval.hybrid family_id=… model=… dense_n=… sparse_n=… merged_n=…` so an operator can confirm both legs ran. The dispatcher reply trailer for a successful answer is `(hybrid retrieval — dense+sparse RRF)`; an empty merged set returns `FallbackMode.NO_EVIDENCE` with the plain "No memories matched 'X'." reply.

Postgres is the only canonical retrieval backend. When `STORAGE_BACKEND=sqlite`, `SqliteDomainStore.dense_candidates` / `sparse_candidates` raise `NotImplementedError`; the dispatcher catches that, logs `retrieval.unavailable reason=… family_id=…`, and returns `NO_EVIDENCE`. Operators running SQLite see ingest work and `/ask` always fall back — that is the canonical contour, not a bug.

BM25, reranker, Qdrant, halfvec/HNSW (A-36b), and multilingual sparse tuning (A-37) are deferred to the next quality-decision packet.

### Telegram in local development
Webhook only (D-019). Expose the local process via a tunnel (e.g. `ngrok`, `cloudflared`) and register the tunnel URL with the bot. There is no polling fallback.

### Command surface (D-028, D-030, D-031, D-036)
The Telegram code path exposes `/note`, `/ask`, `/sources`, `/drafts`, and `/export`, with absence of an explicit command defaulting to **draft** (D-028). The explicit `/draft` command was removed in D-030 — drafts are created only by the no-command default and recalled via `/drafts`. `/sources` (D-036) returns the chunks retrieval selected for the chat's most recent `/ask`.

Operationally: the draft floor (R-13) means no inbound message is silently discarded, even when routing confidence is low. The webhook log line records `lifecycle=draft|note|query|other` so an operator can see which lifecycle state each delivery resolved to. `DomainService` emits `draft.persisted source_message_id=… family_id=… effective_path=fresh|replay` when the draft path commits. CLARIFY (D-020) remains a valid reply shape for the rare case where a heuristic would actively conflict with intent, but the classifier no longer emits CLARIFY for plain text; raw persistence is unconditional.

Schema upgrade note: the `source_messages.detected_route` CHECK constraint extended from `{start, help, note, ask, clarify, unknown}` to `{start, help, note, ask, draft, clarify, unknown}` (D-028). Per A-34, existing local Postgres volumes must be reset with `docker compose down -v` before the new CHECK applies; SQLite has no enum constraint on the column. Until the reset is performed, inserts with `detected_route='draft'` raise a CHECK violation against the live Postgres backend.

### Raw-data durability and recovery (D-027)
Raw `SourceMessage` is the highest-tier durability surface (I-15). The target operational contour:

- daily backup window (target: `03:00–05:00` local time) covering at minimum `source_messages` plus enough relational scaffolding to restore `SourceMessage → Note → EventChunk` lineage,
- a stronger-than-nightly recovery primitive (continuous WAL archiving, point-in-time recovery, streaming replicas, or a managed-cloud equivalent — selected per deployment shape).

Specific backup tooling and RPO/RTO targets remain bracketed as A-40. Derived state (embeddings, indexes, retrieval traces, answer traces) is reproducible from raw under the active parser/embedding versions; raw loss is unrecoverable, so operational policies treat raw retention as the highest tier.

### Raw export (D-027)
The user can export their raw `SourceMessage` data on demand in JSON (stable field names, ISO timestamps) or TXT (one record per block). The export is scope-bounded the same way retrieval is (R-3 / R-14) and records its own provenance (export id, scope, time range, format, requester). Derived state is not in the minimum export contract — raw is sufficient to reconstruct everything else.

Per-host delivery channels (Telegram file reply, HTTP download endpoint, host-app screen) and the request shape are bracketed as A-39. The implementation lands in its own packet.

## Useful reads when stuck
- Workflow & recovery: this file.
- Architecture, adapter axes, deployment shapes: `docs/ARCHITECTURE.md`.
- What must hold at runtime: `docs/RUNTIME-INVARIANTS.md`.
- Data shape rules: `docs/INVARIANTS.md`.
- Open questions: `docs/assumptions.md`.
- Why things are the way they are: `docs/decision-log.md`.
