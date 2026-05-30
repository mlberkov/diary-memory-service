# Runbook — Working in this Repo

## Roles
- **Human owner** — sets product direction, approves assumptions and decisions, owns merges.
- **AI agent (Claude Code, etc.)** — drafts docs, code, and tests under the rules in `AGENTS.md` and `CLAUDE.md`.

## Canonical loop

1. **Read.** Open the canonical docs in the order set by `CLAUDE.md`. Skim recent decision-log entries.
2. **Pick.** Take the top item in `docs/todo.md`. Confirm it maps to a row in `docs/execution-map.md`. Honor the development-sequencing gate (D-043): do not pick a Stage-3 item until the Stage-2 exit criteria are met — see `docs/product/BuildPlan.md` "Development Sequencing".
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
- `EMBEDDING_BACKEND=openai` — calls `text-embedding-3-large` with `dimensions=3072` explicitly. Requires `OPENAI_API_KEY`. The call has an explicit per-attempt timeout and bounded retries — see "Provider resilience (D-047)" below.

The boot gate (R-10) refuses to start when `EMBEDDING_DIMENSION` is not `3072`, when `EMBEDDING_BACKEND=openai` and `EMBEDDING_MODEL` is not `text-embedding-3-large`, when the OpenAI key is missing under the openai backend, or when the connected Postgres lacks the `vector` extension.

#### Failed embeddings
On any provider exception during ingest, the chunks remain persisted, their `embedding_status` flips to `failed`, and zero `embedding_records` are written for that source. The ingest result still returns `FallbackMode.NONE` because raw + chunks survived (I-2, I-3).

Inspect failed chunks with the read-only reconciliation entrypoint (OP-3.1 / D-050):

```bash
python -m memory_rag.services.reconciliation --community <community_id> [--limit N]
```

It lists every chunk stuck at `embedding_status='failed'` for the community — oldest failure first — with its `chunk_id`, `source_message_id`, `note_date`, and `created_at`, plus the total count. `--limit` caps the listing (default `100`). The entrypoint targets the canonical Postgres backend and is read-only: it discovers and reports, it does not retry or transition any chunk. It supersedes the hand-run `psql` probe over `event_chunks`; that table's `embedding_status='failed'` rows remain the authoritative failure signal it reads.

Retry the failed chunks with the same entrypoint's `--retry` mode (OP-3.2a / D-051, OP-3.2b / D-052):

```bash
python -m memory_rag.services.reconciliation --community <community_id> --retry [--limit N]
```

`--retry` re-embeds the discovered failed chunks, grouped by `source_message_id` — the same per-source batching ingest uses — with one `EmbeddingClient.embed` call per group and OP-2's bounded backoff internal to the client. A group that embeds successfully has its `embedding_records` written and its chunks transitioned `failed → ready`; a group whose retry is exhausted is left at `embedding_status='failed'` with no state regression. The command prints a per-group report — `retried_chunks` / `succeeded` / `failed` / `groups` totals plus one `outcome=ready|failed` line per `source_message_id` — and emits `reconciliation.retry.group.ok` / `reconciliation.retry.group.failed` and `reconciliation.retry.summary` logs. `--limit` caps the retried slice exactly as in discovery mode. Without `--retry` the entrypoint stays the read-only discovery surface described above.

An exhausted retry group stays `failed` and remains discoverable, and is also routed to the dead-letter surface (OP-3.2b / D-052): `retry_failed_chunks` attempts a best-effort `indexing_dead_letters` write for the failed group. When that write succeeds, the `dead_letter_id` appears on the group's `outcome=failed` report line and in the `reconciliation.retry.group.failed` log; when it fails it is logged (`dead_letter.write_failed`) and swallowed, exactly as on the ingest path. The dead-letter write never gates or regresses the `failed` outcome.

Replay (R-2) does not re-embed.

#### Dead-letter surface (OP-2.2 / D-048, OP-3.2b / D-052)
On that same failure the service also **attempts** to persist one `indexing_dead_letters` row recording the failed indexing job: `source_message_id`, `community_id`, the affected `chunk_ids`, the `model_name`, and `error_class` (the exception class name only — no free-text exception payload). An exhausted `--retry` group writes a row here too (OP-3.2b), so the table records one row per failed indexing *attempt*. Inspect:

```bash
docker compose exec -T postgres psql -U postgres -d memory_rag -c \
  "SELECT dead_letter_id, source_message_id, model_name, error_class, created_at
     FROM indexing_dead_letters
    ORDER BY created_at DESC;"
```

The dead-letter write is **best-effort**: it runs *after* the `embedding_status='failed'` marking (on ingest) or *after* the group's `failed` outcome is decided (on retry), and a failure of its own is logged (`dead_letter.write_failed`) and swallowed. A row can therefore be absent even though the chunks are correctly `failed`. When the two disagree, treat `event_chunks.embedding_status = 'failed'` (the probe above) as the source of truth — it is the authoritative failure signal; the dead-letter table is a structured convenience layered on top. The table is append-only: the original ingest failure writes one row, and each exhausted `--retry` of that source appends another, so a source may accumulate several rows over time.

There is no automatic / scheduled retry — reconciliation is operator-run via the `--retry` mode above. OP-3 closed the A-35 reconciliation gap: OP-3.1 (D-050) landed the read-only discovery surface, OP-3.2a (D-051) the operator-run retry, and OP-3.2b (D-052) the exhausted-retry routing into this dead-letter surface. **A-35 is resolved.**

#### Schema migrations (OP-1 / D-045, D-046)
The Postgres schema is versioned. The migration history under `src/memory_rag/storage/postgres/migrations/` is the single canonical schema source — there is no `schema.sql`. Migrations are run by `yoyo-migrations` (raw-SQL migration files; psycopg v3 backend).

`PostgresDomainStore` applies all pending migrations to head when it is constructed, so a normal `docker compose up -d postgres` + service boot brings a fresh database up to the current schema with no extra step. To run migrations by hand:

```bash
python -m memory_rag.storage.postgres.migrations_runner apply
```

This is idempotent: a database already at head is left untouched.

**Adopting a pre-existing local volume.** A `memory_rag_pg_data` volume created before OP-1.1 already carries the baseline schema but has no migration-version table. Bring it into the versioned world once, without a destructive reset, by stamping the baseline as already applied:

```bash
python -m memory_rag.storage.postgres.migrations_runner stamp
```

`stamp` marks only the baseline migration as applied — it runs no DDL and touches no data. This is the only supported adoption path; run it once per old volume, then `apply` (or a normal service boot) handles every later migration. A destructive `docker compose down -v` is no longer required to take a schema change.

**Adding a migration.** Add a new file `migrations/NNNN.<slug>.sql` (next ordinal, raw SQL); it is picked up automatically by `apply` and by the bootstrap. Keep upgrades non-destructive — additive DDL, no data read/rewrite/drop.

Worked example — `0002.index-embedding-status.sql` (D-046), the first schema-changing upgrade on top of the baseline:

```sql
CREATE INDEX IF NOT EXISTS idx_event_chunks_embedding_status
    ON event_chunks(embedding_status);
```

Running the upgrade over a populated database needs no reset — `apply` (or a normal service boot) applies only the pending `0002` migration; existing rows are untouched:

```bash
python -m memory_rag.storage.postgres.migrations_runner apply
```

Use plain `CREATE INDEX` (not `CONCURRENTLY`): yoyo wraps each migration in a transaction, and `CONCURRENTLY` cannot run inside one.

### Chat backend (D-037)
Slice 4.5 ships with a dual contour:

- `CHAT_BACKEND=mock` (default) — deterministic in-process stand-in. `model_name` on persisted `AnswerTrace` rows is the literal string `mock`, so SQL inspection alone tells you which provider produced a row.
- `CHAT_BACKEND=openai` — calls `chat.completions.create` with `response_format={"type": "json_object"}` and `temperature=0`. Requires `OPENAI_API_KEY`. The call has an explicit per-attempt timeout and bounded retries — see "Provider resilience (D-047)" below.

The boot gate (R-10) refuses to start when `CHAT_BACKEND=openai` and `CHAT_MODEL` is not the canonical `gpt-4.1`, or when the OpenAI key is missing under the openai backend. The non-empty `model_name` check from D-034 is unchanged.

`OpenAIError` and `TimeoutError` from the SDK boundary are translated to `ChatProviderUnavailableError` so the existing D-035 grading writes the call as `FallbackMode.PROVIDER_UNAVAILABLE` and the dispatcher emits the retry-hint reply. `answer_text=""`, `token_counts={}`, `latency_ms=0` per D-035's truthful-trace table.

Live calls are not part of `make check`. The optional smoke `tests/test_chat_client_openai.py` is skipped unless `MEMORY_RAG_OPENAI_TEST_KEY` is set (same gating pattern as the live embedding smoke and the live Postgres tests).

### Provider resilience (D-047, D-049)
Both OpenAI adapters (embedding and chat) make every API call with an explicit per-attempt timeout and a bounded retry loop, so R-9 holds — there is no unbounded wait or retry. Four env knobs, shared by both adapters:

- `PROVIDER_TIMEOUT_SECONDS` (default `30.0`) — the per-attempt wall-clock budget.
- `PROVIDER_MAX_ATTEMPTS` (default `3`) — total attempts including the first; `1` disables retries.
- `PROVIDER_BACKOFF_BASE_SECONDS` (default `0.5`) — the base of the exponential inter-attempt wait.
- `PROVIDER_BACKOFF_CAP_SECONDS` (default `8.0`) — the ceiling on any single inter-attempt wait.

A retryable failure that is not the final attempt is followed by an inter-attempt wait: exponential backoff with full jitter (`base × 2^(attempt−1)`, clamped to the cap). When a 429 carries a server `Retry-After`, that delay is honored instead — also clamped to `PROVIDER_BACKOFF_CAP_SECONDS`, so total wait stays bounded. Only the numeric `Retry-After` form is parsed; a date-form or malformed header falls back to computed backoff. Worst-case bounded wall time for one provider call is `PROVIDER_TIMEOUT_SECONDS × PROVIDER_MAX_ATTEMPTS + PROVIDER_BACKOFF_CAP_SECONDS × (PROVIDER_MAX_ATTEMPTS − 1)` (106s at defaults). The SDK's own retry is disabled (`max_retries=0`) so this loop is the single retry authority. Timeouts, connection errors, 5xx, and rate limits (429) are retried; auth failures and other 4xx fail fast. The mock backends ignore all four knobs.

Each attempt logs a `provider.attempt` line (label, attempt number, outcome class, latency); a retryable attempt that is followed by a wait also carries `delay_ms` and `delay_source=computed|retry_after`. An exhausted call logs a distinct `provider.exhausted` line. To see provider-call behavior:

```bash
grep -E 'provider\.(attempt|exhausted)' <service-log>
```

A chat call that exhausts its retries surfaces to the user as the existing `FallbackMode.PROVIDER_UNAVAILABLE` retry-hint reply (D-035); an embedding call that exhausts its retries flips the affected chunks to `embedding_status='failed'` (A-35) — see "Failed embeddings" above.

### Webhook idempotency (R-2 / D-023)
Repeated delivery of the same Telegram message-state — same `(external_chat_id, external_message_id, edit_seq)` — does not create duplicate rows. The webhook returns the same functional 200 reply and logs `effective_path=replay` instead of `fresh`. Operationally, `effective_path=replay` is normal; investigate only if the *first* call for a given key never appears with `effective_path=fresh`.

### Retrieval traces (D-032)
Every `/ask` call writes one row to `queries` and zero-or-more rows to `retrieval_hits` so an operator can inspect what each leg saw and what survived RRF without rerunning the query. Successful retrieval persists per-leg rows (one per chunk in `dense_candidates`, one per chunk in `sparse_candidates`) plus merged rows (one per chunk in the RRF-fused top-k). `NO_EVIDENCE` (empty query or empty merged set) persists the `Query` row with zero `retrieval_hits` rows.

Most recent traces, full picture across legs:

```sql
SELECT q.query_id, q.created_at, q.query_text, q.fallback,
       h.leg, h.rank, h.score, h.chunk_id
  FROM queries q LEFT JOIN retrieval_hits h ON h.query_id = q.query_id
 WHERE q.community_id = '<chat_id>'
 ORDER BY q.created_at DESC, h.leg, h.rank
 LIMIT 50;
```

Failed answers only (queries where retrieval found nothing):

```sql
SELECT q.query_id, q.created_at, q.query_text
  FROM queries q
 WHERE q.community_id = '<chat_id>' AND q.fallback = 'no_evidence'
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
 WHERE q.community_id = '<chat_id>'
 ORDER BY q.created_at DESC
 LIMIT 20;
```

A-34 destructive-upgrade discipline applies: existing local Postgres volumes that pre-date the Slice 4.3b CHECK widening on `queries.fallback` and `answer_traces.fallback_mode` must be reset via `docker compose down -v` before the bootstrap DDL applies cleanly. Real provider adapters remain deferred to Phase 6.

### Real-answer end-to-end smoke (REAL-1 / D-073)
REAL-1 records the one-shot product-baseline proof that the wired OpenAI paths — D-024 embeddings + D-037 chat + boot gate — actually produce a grounded `/note` → retrieval → answer round-trip under the existing OP-2 bounded-retry / OP-4 backup / OP-5 inspection contours. It is **operator-deliberate, off-CI**, mirroring the OP-5 Postgres-mode pattern: `make check` runs no live OpenAI call, the gated `tests/test_chat_client_openai.py` and `tests/test_embedding_client_openai.py` are unchanged, and this procedure is invoked by the operator out-of-band.

REAL-1 lands in two halves: **REAL-1.0** (this subsection + the committed evidence-file template at `docs/real-answer-drill/real-answer-smoke-TEMPLATE.json` + the decision-log entry / todo / execution-map registrations) is the operator-procedure prep; **REAL-1.1** is the operator-execution packet that produces a populated dated `docs/real-answer-drill/real-answer-smoke-<YYYYMMDD>-evidence.json`. REAL-1.0 does **not** close REAL-1 on its own — closure depends on REAL-1.1's populated artifact.

#### Operator pre-conditions
- Postgres is up via the OP-1 migrations bootstrap (`docker compose --profile vps up -d --build` brings the whole stack up; `STORAGE_BACKEND=postgres` selects the canonical durable backend).
- `OPENAI_API_KEY` is available in the operator's secret store (real key, not a sandbox stub).
- Canonical env knobs are set: `STORAGE_BACKEND=postgres`, `EMBEDDING_BACKEND=openai`, `EMBEDDING_MODEL=text-embedding-3-large`, `EMBEDDING_DIMENSION=3072`, `CHAT_BACKEND=openai`, `CHAT_MODEL=gpt-4.1`, `TELEGRAM_WEBHOOK_SECRET=<set>`. `_verify_embedding_contour` and `_verify_chat_contour` in `src/memory_rag/app.py` abort start on any mismatch (R-10) — a successful `app.created` log line is the boot-gate green signal.
- The OP-2 bounded-retry / backoff defaults from D-047 / D-049 are active (no tuning is part of REAL-1); a transient 429 surfacing as `attempt=2/3 outcome=success` on a `provider.attempt` line is acceptable and is captured verbatim, not treated as a defect.
- Sync indexing (D-024) means a `/note` request returns 200 only after the embedding has been persisted, so the `/ask` call that follows can rely on `embedding_status='ready'` for the just-ingested chunks without an extra wait.

#### Numbered run procedure
1. Export the canonical env knobs (above) into the shell or `.env`. Do not echo `OPENAI_API_KEY` / `TELEGRAM_BOT_TOKEN` / `TELEGRAM_WEBHOOK_SECRET` to a log file.
2. Bring the stack up: `docker compose --profile vps up -d --build` (or the equivalent local bring-up).
3. Confirm the boot-gate green signal: `docker compose logs app | grep app.created` and copy the verbatim line into `preflight_state.boot_log_line_verbatim`. Expected fields include `embedding_backend=openai embedding_dim=3072 chat_backend=openai chat_model=gpt-4.1`.
4. POST one `/note` via the QUICKSTART recipe — reuse the curl block from `QUICKSTART.md` lines 87–92 unchanged in shape, swapping the `X-Telegram-Bot-Api-Secret-Token: dev-secret` header for the real `$TELEGRAM_WEBHOOK_SECRET` and the canonical `chat`/`from` ids you intend to use throughout the smoke. Capture the verbatim 200 response body into `note_round_trip.response.body_text_verbatim`.
5. Confirm `embedding_status='ready'` for the just-ingested chunks via SQL (use the OP-3.1 inspection seam at `docs/RUNBOOK.md` §"Failed embeddings" — substitute `embedding_status='ready'`). Record the per-table deltas into `note_round_trip.post_ingest_row_counts` and the `embedding_records` sample shape into `note_round_trip.embedding_records_sample_row`.
6. POST one `/ask` via the QUICKSTART recipe — reuse the curl block from `QUICKSTART.md` lines 95–99 unchanged in shape, with the same secret and chat id, and a query that should match the saved note content. Capture the verbatim 200 response body into `ask_round_trip.response.user_facing_reply_verbatim`.
7. Capture the latest `answer_traces` row via the existing one-liner from §"Answer traces (D-034, D-035)" above, scoping to the test community and replacing `LIMIT 20` with `LIMIT 1`. Confirm `fallback_mode='none'`, `model_name='gpt-4.1'`, `prompt_version='v1'`, non-empty `context_chunk_ids`, `latency_ms > 0`, non-empty `token_counts`; copy the verbatim row into `ask_round_trip.answer_traces_row`.
8. Capture the two `provider.attempt` log lines (one embedding, one chat) via `docker compose logs app | grep -E 'provider\.(attempt|exhausted)'` and copy each verbatim into the relevant `*_round_trip.provider_attempt_log_line_verbatim` field. `attempt=2/3 outcome=success` is acceptable; `attempt=1/3 outcome=success` is the happy path.
9. Hand-assemble the dated working artifact: `cp docs/real-answer-drill/real-answer-smoke-TEMPLATE.json docs/real-answer-drill/real-answer-smoke-<YYYYMMDD>-evidence.json`, drop the top-level `"_template": true` flag, and replace every `<TO_FILL_BY_OPERATOR>` placeholder with the verbatim captured observation.
10. Run the redaction grep checklist below before committing.

#### Evidence-file shape
The artifact carries five top-level branches mirroring the D-068 cross-version-drill template precedent: `metadata` (capture date, environment, redaction notes), `preflight_state` (env-knob set with secrets redacted; verbatim `app.created` line), `note_round_trip` (the `/note` request / response / post-ingest row counts / `embedding_records` sample / `event_chunks` status transition / one `provider.attempt label=openai_embedding …` line), `ask_round_trip` (the `/ask` request / response / `queries` row / `retrieval_hits` row counts by leg / one `answer_traces` row / verbatim user-facing reply / one `provider.attempt label=openai_chat …` line), and `summary` (`note_round_trip_green` / `ask_round_trip_green` / `answer_grounded` / `closes_real_1_0` / `closes_real_1_1` / `closes_real_1` booleans + verdict string). The committed `out_of_scope_for_this_packet` block is preserved verbatim.

#### Redaction rule
Credential text — `$OPENAI_API_KEY`, `$TELEGRAM_BOT_TOKEN`, `$TELEGRAM_WEBHOOK_SECRET`, `$PUBLIC_HOSTNAME` (if part of the request URL or any captured log line), and the webhook URL path token — **must not appear in the captured evidence file**. Structural outcomes (status strings, log-line shapes, row counts, `fallback_mode='none'`, `model_name='gpt-4.1'`, numeric `latency_ms` magnitudes, `token_counts` integers) are captured verbatim; credential-bearing values are replaced by `<REDACTED>` or a `_redacted: true` flag. Pre-commit, grep the evidence artifact for the literal `$OPENAI_API_KEY`, `$TELEGRAM_BOT_TOKEN`, `$TELEGRAM_WEBHOOK_SECRET`, and `$PUBLIC_HOSTNAME` values and confirm none appear literally:

```bash
grep -E "$OPENAI_API_KEY|$TELEGRAM_BOT_TOKEN|$TELEGRAM_WEBHOOK_SECRET|$PUBLIC_HOSTNAME" \
  docs/real-answer-drill/real-answer-smoke-<YYYYMMDD>-evidence.json && echo "REDACTION FAILED" || echo "redaction grep clean"
```

#### Closure signal
Closure of **REAL-1** is by a populated dated `docs/real-answer-drill/real-answer-smoke-<YYYYMMDD>-evidence.json` produced by REAL-1.1 with all three of `summary.note_round_trip_green`, `summary.ask_round_trip_green`, and `summary.answer_grounded` set to `true` and `summary.closes_real_1: true`. REAL-1.0 does not close REAL-1 on its own — it lands the procedure + template + cross-doc registration so that REAL-1.1 is a single bounded operator action.

#### `make check` non-impact
This procedure makes no contribution to `make check`. No new gated test is added; the existing `tests/test_chat_client_openai.py` and `tests/test_embedding_client_openai.py` smokes (env-gated by `MEMORY_RAG_OPENAI_TEST_KEY`) are unchanged. The captured artifact is documentation evidence, not a CI input.

### Selected-chunks recall (`/sources`, D-036)
`/sources` exposes the **selected chunks as-is** for the chat's most recent `/ask` turn: the post-RRF top-k chunks `services/context_assembler.assemble_answer_context` produced and `build_answer_prompt` fed to the LLM — i.e. the same `chunk_id` list `AnswerTrace.context_chunk_ids` records, rendered with `note_date`, a 1-based `(i/N)` index, and the full `chunk_text` verbatim. The raw `chunk_id` is **not** surfaced to the user (D-069); operator forensics still join through `AnswerTrace.context_chunk_ids` via the SQL recipe in "Inspecting recent `/ask` retrieval traces (D-032)" above. The `(i/N)` marker is **per-last-`/ask` ephemeral ordering, not a stable cross-`/ask` identifier** — the index numbers the chunks within the current cached list in post-RRF order, and the cache is overwritten by the next `/ask`. It is not citations, not fine-grained attribution, and not the full pre-RRF candidate pool. Outbound delivery is one Telegram message by default and splits across multiple messages only when the 4096-char cap forces it (whole-block boundaries; `(part k/N)` footers on an oversized single chunk; identical packing semantics to `/drafts`). The `(i/N)` block header and the outbound `(part k/N)` packing footer live at distinct positions in the rendered message and do not collide.

The state behind `/sources` is a process-local `Dispatcher._latest_sources: dict[str, tuple[EventChunk, ...]]` keyed by `community_id`. The current FastAPI wiring at `adapters/telegram/webhook.py` makes `Dispatcher` a module-level singleton via `get_dispatcher()`, so `/ask` and a follow-up `/sources` are served by the same instance within one process. **Every `/ask` dispatch updates the cache**: non-empty `answer.context.ordered_chunks` overwrites; empty (empty-query, empty-retrieval `NO_EVIDENCE`, retrieval-unavailable on SQLite) clears. Non-`/ask` routes never touch the cache. `/sources` itself is read-only.

Fail-closed: when nothing is cached, `/sources` returns `"No selected chunks available — ask a question with /ask first."` via the inline `sendMessage` body — no outbound HTTP call. The fail-closed reply also fires after process restart and after any `/ask` that produced no retrieval.

Multi-worker caveat: each uvicorn worker / pod holds its own dispatcher singleton, so `/ask` on worker A followed by `/sources` on worker B will fail closed (or return stale chunks). The current contour is single-process local dev; promoting the cache to a durable seam (e.g. `DomainRepository.get_latest_answer_trace_for_family(community_id)` + per-chunk lookups via `get_event_chunk`) is the named follow-up trigger if the deployment shape flips.

Author attribution (forward note, D-081): `/sources` does **not** render author display names today. D-081 pins the contract for when it does — author display is resolved **only at the Telegram adapter seam** from host-supplied identity fields (`username → first_name → opaque short-ID`, non-authoritative); the core carries only the opaque `author_user_id`. `/sources` is the sole sanctioned display surface for that attribution this milestone; answer-reply (`/ask` reply) attribution is deferred (see `docs/assumptions.md` A-44).

### Retrieval-quality inspection harness (D-038)
`src/memory_rag/eval/retrieval/` ships a hand-curated harness that measures the D-025 baseline contour against a small fixture corpus + gold-query set. It is **inspection, not a gate** — the CLI exit code is always `0` regardless of the observed metrics.

Two modes share one metric shape (aggregate `recall@{5,10,20}`, `mrr@20`, `hit_rate`, `empty_rate`, `per_leg_recall@20.{dense,sparse,fused}`; per-query top-`candidate_k` chunk-id lists, diagnostic per-leg first-relevant-rank fields, and an explicit `reciprocal_rank_in_fused` numerator). See "Retrieval hit-rate / empty-rate" below for the two OP-5.2a metrics:

- **Mock mode.** Runs under `make check` via `tests/test_retrieval_harness_shape.py`. Shape-only assertions, no quality thresholds. Also smokeable directly:

  ```bash
  uv run python -m memory_rag.eval.retrieval --mode mock
  ```

- **Postgres mode (operator baseline).** Truncates `embedding_records`, `event_chunks`, `notes`, `source_messages` on the connected DSN, then re-ingests `eval/retrieval/corpus.jsonl` through the canonical `DomainService.ingest` path. Point the DSN at a **dedicated eval database** so production data is never touched:

  ```bash
  MEMORY_RAG_PG_TEST_DSN=postgresql://... \
  EMBEDDING_BACKEND=openai \
  OPENAI_API_KEY=... \
  uv run python -m memory_rag.eval.retrieval --mode postgres --json | tee snapshot.json
  ```

  Live OpenAI is used on the **corpus side** at ingest time because D-025's dense leg filters by `model_name` and the cached query embeddings are pinned to `text-embedding-3-large` — mixing models is silently broken (the harness aborts on `model_name` mismatch rather than returning zero hits). Live OpenAI on the corpus side is acceptable here because the operator chose this run deliberately; `make check` never enters this path.

  After the run, paste the aggregate metrics plus 2–3 illustrative per-query rows into the D-038 "Baseline snapshot (observed)" subsection in `docs/decision-log.md` — framed as observed values for the D-025 contour, not as a must-beat threshold for any future packet.

#### Retrieval hit-rate / empty-rate (OP-5.2a / D-057)
The harness report carries two retrieval-coverage aggregates alongside recall / MRR. Both are **inspection only** — observed values, no thresholds, the CLI exit code stays `0`. They appear in the human report under the `Aggregate (...)` block and in the `--json` output's `aggregate` object.

- **`hit_rate`** — of the gold queries that *have* expected chunks, the fraction whose fused result list surfaced at least one of them. Answers "of the answerable queries, how often did retrieval surface something relevant?" Its **denominator is the non-empty-gold queries only** — negative queries (empty `expected_handles`) are excluded because they cannot produce a hit, and counting them would only dilute the rate. This non-empty-gold denominator is what keeps `hit_rate` distinct from `per_leg_recall@20.fused`, which divides by *all* queries. The human report annotates the line `(denominator: non-empty-gold queries only)`.
- **`empty_rate`** — the fraction of *all* gold queries whose fused result list came back empty (retrieval returned zero candidates — both the dense and sparse legs empty). It counts every query, answerable or negative. The human report annotates the line `(denominator: all queries)`.

Where to look: run the harness in mock mode and read the `hit_rate` / `empty_rate` lines, or inspect `aggregate.hit_rate` / `aggregate.empty_rate` in `--json`. For the OP-5 observability set the denominator split is explicit — that set has **21 total gold queries, 19 of them non-empty** (2 negatives, "did I go skiing this winter" and "notes about my tax return"), so `hit_rate` is computed over **19** while `empty_rate` is computed over **21**:

```bash
uv run python -m memory_rag.eval.retrieval --mode mock \
  --gold eval/retrieval/observability/gold.json \
  --corpus eval/retrieval/observability/corpus.jsonl
```

#### Groundedness proxy (answer-path, fallback-derived, inspection only)
The harness's second half (OP-5.2b / D-058) drives `QueryService.answer` over every gold query (`RouteKind.ASK`) and renders a groundedness section under the retrieval aggregates — title matches this subsection verbatim so an operator reading the CLI report can find this prose at a glance. The section appears in the human report after the retrieval `Aggregate` block, and as a nested `groundedness` object in the `--json` output's top-level `HarnessReport`.

**This is a proxy metric, not a citation-coverage or factuality score.** It is derived from `AnswerResult.fallback`, which by D-035 (one decision per call) is a faithful projection of the I-9 enforcement outcome — the harness does not look at the LLM's `cited_chunk_ids` directly (that field is computed and I-9-validated inside `parse_structured_answer` but discarded; exposing it on `AnswerResult` for true citation-coverage metrics is recorded as a deferred follow-up in D-058). The documented mapping:

- **Grounded** — `FallbackMode ∈ {NONE, WEAK_EVIDENCE, AMBIGUOUS}`. These are exactly the three contours that by the D-035 parse contract carry a **non-empty** `cited_chunk_ids` ⊆ `AnswerContext.ordered_chunks` (the I-9 citation-subset). The answer text is backed by retrieved evidence.
- **Not grounded** — `NO_EVIDENCE` (empty retrieval or LLM-declared no_evidence — empty citations), `PROVIDER_UNAVAILABLE` (no answer produced), and `PARSE_FAILURE` (catches `FabricatedCitationError` — the I-9 citation-subset *violation* contour — and malformed JSON). The I-9-violation contour is folded into `PARSE_FAILURE` and remains ungrounded, by design.

What the section reports, line by line:

- **`groundedness_rate`** — fraction of **answerable** queries (non-empty `expected_handles`) whose graded answer is grounded. **Denominator is the non-empty-gold queries only**, mirroring `hit_rate` from OP-5.2a — negatives correctly returning `NO_EVIDENCE` are excluded so they do not dilute the rate. The human report annotates the line `(proxy: fallback-derived; denominator: non-empty-gold queries only)`.
- **`fallback_mode_counts`** — a sorted breakdown of every `FallbackMode.value` seen across **all** queries (negatives included), summing to the total query count. This is the full distribution of answer-path outcomes at a glance.

Caveats to read the number with:

- The proxy reads `≥ hit_rate` in mock mode whenever retrieval surfaces *any* chunk, relevant or not — the `MockChatClient` cites every context chunk confidently and grades `NONE`, which is exactly the proxy's documented limit (it cannot distinguish a citation of a gold-relevant chunk from a citation of an irrelevant one). On the OP-5 observability set (21 queries, 19 non-empty-gold) `groundedness_rate ≈ 0.684` is the mock-mode observed value; real discriminating signal appears with a real chat provider under Postgres mode.
- Postgres-mode invocation reuses the operator-selected `CHAT_BACKEND` (defaulting to `mock`); the harness does not force a live OpenAI call. The Postgres clean-state ritual extends its `TRUNCATE` to `answer_traces` / `retrieval_hits` / `queries` so an operator answer-harness run starts from a clean eval DB.
- The metric is **inspection only**. CLI exit stays `0` regardless of `groundedness_rate`. `make check` does not gate on it.

#### Cost & latency (wall-clock + provider-reported tokens, inspection only)
The harness's third aggregate (OP-5.3 / D-059) reports provider-reported token totals and wall-clock latency at two boundaries. Title matches the CLI section verbatim so an operator reading the human report can find this prose at a glance. The section appears in the human report after the groundedness block, and as a nested `cost_latency` object in the `--json` output's top-level `HarnessReport`.

**What is measured, line by line:**

- **`total_prompt_tokens` / `total_completion_tokens` / `total_tokens`** — sums of provider-reported token counts across every answer-path call, derived from `ChatResponse.token_counts` (`.get("prompt", 0)` + `.get("completion", 0)`) captured per call by a `RecordingChatClient` shim that wraps the operator-selected chat client. "Provider-reported" is the honest framing: the harness reports whatever the chat client returned. Under `MockChatClient` the counts are character-count approximations (per `ChatResponse` docstring), **not** real-tokenizer counts — read mock-mode numbers as deterministic but not comparable to real-provider tokens. Under a real chat backend (operator-selected via `CHAT_BACKEND` in Postgres mode), the counts come from the provider's API response.
- **`mean_total_tokens_per_call`** — mean of `prompt_tokens + completion_tokens` over the rows that recorded tokens. The line carries `(denominator: answer-path calls with non-empty token_counts, n=<int>)`. `n` excludes rows whose contour short-circuited before invoking the chat client (`NO_EVIDENCE` / empty-query / `PROVIDER_UNAVAILABLE` — D-035), so those rows do not pull the per-call mean downward.
- **`retrieval_latency_ms` mean / p50 / max** — wall-clock around the per-query `dense + sparse + RRF` block inside `run_harness`, measured with `time.perf_counter`. **The query-embedding lookup is intentionally excluded from this boundary** because mock mode obtains query embeddings via a live `MockEmbeddingClient.embed` call while Postgres mode reads from the pinned `eval/retrieval/embeddings_cache.json` — including the lookup would contaminate the metric with that mode-asymmetric cost. Denominator is **all queries** (every row contributes one sample); the line carries `(denominator: all queries)`.
- **`answer_latency_ms` mean / p50 / max** — wall-clock around the per-query `QueryService.answer(...)` call inside `run_answer_harness`, measured with `time.perf_counter`. This covers the whole answer path (retrieval + chat + persistence), not just the chat call. Denominator is **all queries**.

**Read the numbers with these caveats:**

- **`p50` is included as a small-sample robustness check at the current ~20-21 query gold-set size.** Median resists a single slow outlier that would pull the mean. **`p95` is intentionally omitted** — at ~20 samples it would be too noisy to be meaningful. A future packet may add p95 when the gold set grows.
- **Aggregate latency is wall-clock only.** The provider-attributed `ChatResponse.latency_ms` is still the canonical chat-call latency persisted on `AnswerTrace` (D-034 / D-035) — that is **trace-level provenance, not an aggregate metric in this report**. The wall-clock around `query_service.answer(...)` and the persisted `ChatResponse.latency_ms` measure different layers (whole answer-call vs provider call) and are deliberately not surfaced as co-equal aggregate signals.
- **Latency numbers are non-deterministic and machine-dependent.** They reflect the host running the harness; do not read them as regression targets. Mock-mode token totals, by contrast, are deterministic (mock derives `token_counts` from character counts).
- **No misattribution across calls.** The `RecordingChatClient` shim's `consume_last()` returns the most recent `ChatResponse` *and clears the slot*; the harness reads one consume per row. On a no-chat-call contour the consume returns `None`, the row gets zero tokens, and a prior response cannot leak onto it. `tests/test_retrieval_harness_cost_latency.py::test_recorder_no_misattribution_across_calls` pins this contract.
- **Inspection only.** CLI exit stays `0` regardless of any observed value. `make check` does not gate on cost or latency. No production telemetry change, no live OpenAI in `make check`, no schema or migration. `_TRUNCATE_TABLES` is unchanged — OP-5.2b already covers the answer-path tables.

Where to look: run the harness in mock mode and read the `Cost & latency (...)` block, or inspect `cost_latency.cost` / `cost_latency.latency` in `--json`. The same Postgres-mode invocation as for the groundedness proxy renders cost/latency over the same operator-selected chat client (no live OpenAI is forced).

#### Query-embeddings cache (`eval/retrieval/embeddings_cache.json`)
The cache pins query embeddings to a specific `text-embedding-3-large` @ 3072-dim point-in-time output so the Postgres run is reproducible without contacting OpenAI on the query side. Regenerate is an operator-only ritual:

```bash
OPENAI_API_KEY=... uv run python -m memory_rag.eval.retrieval.regenerate_embeddings [--force]
```

`--force` is required to overwrite an existing cache because regenerating **invalidates prior baseline snapshots** — the model output drifts. The script writes `model_name` and `dimension` into the file; the Postgres-mode CLI checks these against the configured corpus-side embedding client and aborts on mismatch.

The cache is **not** committed by the D-038 implementation packet — it is produced by this ritual. Postgres-mode refuses to start if the cache is missing.

#### Gold-set handle contract
`expected_handles` entries in `eval/retrieval/gold.json` use the form `"{external_message_id}#{event_index}"` where `event_index` is the 0-based ordinal of the produced `EventChunk` within the source message after `DomainService.ingest` chunks it. This is internal to the harness only — it is **not** a business event id, **not** a Telegram message id, **not** any external domain identifier. It exists because `chunk_id` is uuid4 at ingest time. The same contract applies unchanged to the OP-5 observability set below.

#### Gold-set fixtures — D-038 baseline vs OP-5 observability (D-056)
The harness ships **two** fixture pairs, kept distinct:

- **Frozen D-038 baseline set** — `eval/retrieval/gold.json` + `eval/retrieval/corpus.jsonl` (12 queries). Role: the D-025 baseline-measurement set. Used by the still-pending D-038 Postgres baseline capture above and later baseline-vs-quality comparisons. Frozen — do not edit it to grow coverage.
- **OP-5 observability set** — `eval/retrieval/observability/gold.json` + `eval/retrieval/observability/corpus.jsonl` (~21 queries / 19-message corpus, curated for coverage diversity: negatives, multilingual, paraphrase, single/multi-hit). Role: the expanded evaluability set the rest of OP-5 builds on.

**Invocation contract — default vs explicit.** The **default** mock invocation (`--mode mock`, no path flags) loads the **frozen D-038 baseline** pair. The **observability** set must always be selected explicitly:

```bash
uv run python -m memory_rag.eval.retrieval --mode mock \
  --gold eval/retrieval/observability/gold.json \
  --corpus eval/retrieval/observability/corpus.jsonl
```

A Postgres-mode run over the observability set additionally points `--embeddings-cache` at `eval/retrieval/observability/embeddings_cache.json`, and its cache is regenerated with the matching paths:

```bash
OPENAI_API_KEY=... uv run python -m memory_rag.eval.retrieval.regenerate_embeddings \
  --gold eval/retrieval/observability/gold.json \
  --cache eval/retrieval/observability/embeddings_cache.json [--force]
```

Mock-mode shape coverage in `tests/test_retrieval_harness_shape.py` is parametrized over **both** pairs under `make check`.

### Hybrid retrieval (D-025)
`/ask` runs the baseline hybrid path: a single query-embedding call followed by dense + sparse legs against `SearchRepository`, fused with service-layer RRF. Every retrieval call logs `retrieval.hybrid community_id=… model=… dense_n=… sparse_n=… merged_n=…` so an operator can confirm both legs ran. A successful answer reply is `result.answer_text` alone — no trailer line (D-069 dropped the prior `(hybrid retrieval — dense+sparse RRF)` trailer as user-facing ranking-method jargon; the equivalent operator signal stays in the `retrieval.hybrid` log line). `WEAK_EVIDENCE` and `AMBIGUOUS` still append their plain-English explanatory trailers (`(weak evidence — model expressed uncertainty)` / `(ambiguous question — refine and ask again)`). The dispatcher's empty-evidence `FallbackMode.NO_EVIDENCE` surface returns `"Nothing in your saved notes matched 'X'. Try rephrasing the question, or use words that appear in your notes."` — neutral about cause, with two short question-side nudges.

Postgres is the only canonical retrieval backend. When `STORAGE_BACKEND=sqlite`, `SqliteDomainStore.dense_candidates` / `sparse_candidates` raise `NotImplementedError`; the dispatcher catches that, logs `retrieval.unavailable reason=… community_id=…`, and returns `NO_EVIDENCE`. Operators running SQLite see ingest work and `/ask` always fall back — that is the canonical contour, not a bug.

BM25, reranker, Qdrant, halfvec/HNSW (A-36b), and multilingual sparse tuning (A-37) are deferred to the next quality-decision packet.

### Telegram in local development
Webhook only (D-019). Expose the local process via a tunnel (e.g. `ngrok`, `cloudflared`) and register the tunnel URL with the bot. There is no polling fallback.

### Command surface (D-028, D-030, D-031, D-036, D-078)
The Telegram code path exposes `/note`, `/ask`, `/sources`, `/drafts`, and `/export`, with absence of an explicit command defaulting to **draft** (D-028). The explicit `/draft` command was removed in D-030 — drafts are created only by the no-command default and recalled via `/drafts`. `/sources` (D-036) returns the chunks retrieval selected for the chat's most recent `/ask`.

Operationally: the draft floor (R-13) means no inbound message is silently discarded, even when routing confidence is low. The webhook log line records `lifecycle=draft|note|query|other` so an operator can see which lifecycle state each delivery resolved to. `DomainService` emits `draft.persisted source_message_id=… community_id=… effective_path=fresh|replay` when the draft path commits. CLARIFY (D-020) remains a valid reply shape for the rare case where a heuristic would actively conflict with intent, but the classifier no longer emits CLARIFY for plain text; raw persistence is unconditional.

Routing contract (D-078, enforced in code by D-079): command-less plain text routes only to the draft floor — the heuristic plain-text NOTE (first-line ISO date) and ASK (question shape) auto-routes are retired, and NOTE/ASK are reached only via explicit `/note` / `/ask`. The live classifier now routes every command-less plain-text message to the draft floor (a dated body is persisted raw as a draft, a question-shaped message is persisted raw as a draft); the webhook still records `route_source=heuristic` for these so command-vs-heuristic provenance is preserved (R-11).

#### `/note` first-line date format (D-070)
The explicit `/note` dispatcher path normalizes a small whitelist of near-ISO first-line tokens to canonical `YYYY-MM-DD` before the strict parser runs. Accepted forms (zero-padded only):

- `YYYY-MM-DD` (recommended canonical form, e.g. `2026-05-09`)
- `YYYY/MM/DD`, `YYYY.MM.DD`
- `DD-MM-YYYY`, `DD/MM/YYYY`, `DD.MM.YYYY`

**DD-first inputs are always interpreted as DD/MM/YYYY by intentional product convention** — there is no fallback heuristic and no per-input ambiguity branch. Concrete pin: `05/09/2026` → `2026-09-05` (5 September 2026, never 9 May 2026). The same convention applies to the other DD-first separators.

Rejected categories (fall through to the user-facing error below):

- Unpadded month or day: `2026-5-9`, `9/5/2026`, etc.
- Mixed separators: `2026-05/09`, `09.05-2026`.
- Natural-language or relative dates: `May 9 2026`, `today`, `yesterday`.
- Impossible calendar dates: `2026-02-30`, `30-02-2026`.

User-facing failure UX: when the first line does not match the whitelist, the reply is exactly `"First line must be a date like 2026-05-09. Got: '<first-line>'."`. The raw `SourceMessage` is still recorded (I-15); no `Note` or `EventChunk` is created. Operator script for the parent: "Send `/note 2026-05-09` on the first line, then one event per line." If the parent prefers DD-first, remind them DD/MM/YYYY is the convention so May/September do not get swapped.

Scope note: this normalization is applied only on the explicit `/note` dispatch path. There is no longer a plain-text NOTE auto-route — `core/routing/classifier.py` routes all command-less plain text to the draft floor (D-078, enforced in code by D-079), so a dated plain-text line is persisted as a draft, never auto-committed as a NOTE. The `/note`-without-explicit-date → "today" companion remains deferred to a later packet of the Stage-1 capture/routing baseline correction.

Schema upgrade note: the `source_messages.detected_route` CHECK constraint extended from `{start, help, note, ask, clarify, unknown}` to `{start, help, note, ask, draft, clarify, unknown}` (D-028). Per A-34, existing local Postgres volumes must be reset with `docker compose down -v` before the new CHECK applies; SQLite has no enum constraint on the column. Until the reset is performed, inserts with `detected_route='draft'` raise a CHECK violation against the live Postgres backend.

### Raw-data durability and recovery (D-027, D-053, D-054, D-055)
Raw `SourceMessage` is the highest-tier durability surface (I-15). D-053 (OP-4.1) resolved A-40 — the backup mechanism and the recovery objectives below are the committed contour. D-054 (OP-4.2) wired the backup automation for the reference Postgres shape (see "Backup automation" below). D-055 (OP-4.3) added the restore tooling and executed the first restore drill — the recovery objectives below are a **measured result** for the reference/local shape (see "Restore drill" below), not just a target.

- **Daily backup window.** A nightly physical base backup (`pg_basebackup`) runs in the `03:00–05:00` local-time window. The base backup is cluster-wide — it covers raw `source_messages` plus the `notes` / `event_chunks` lineage scaffolding, the append-only `indexing_dead_letters` audit surface, and every other table.
- **Stronger-than-nightly recovery primitive.** Continuous WAL archiving (`archive_command`, `archive_timeout` ≈ 5 min) on top of the base backup enables point-in-time recovery to any moment between the last base backup and the failure. For the reference/local Postgres deployment (`docker-compose.yml`) this base-backup + WAL-archiving primitive is the committed mechanism; the managed-cloud and self-hosted shapes use the provider- or operator-owned equivalent PITR (the specific managed provider is still open — A-41).
- **Recovery objectives for raw data.** RPO ≤ 5 minutes (at most ~5 minutes of raw writes lost) and RTO ≤ 1 hour (raw `SourceMessage` data recoverable within an hour of the recovery decision).
- **Retention.** Base backups are retained 30 days; archived WAL is retained long enough to cover the oldest retained base backup, so PITR is possible to any point in the trailing ~30-day window.
- **Restore drill.** A restore drill — recovering raw `SourceMessage` data from a base backup and exercising PITR from archived WAL — is run once before the first non-local deployment, then quarterly thereafter. The OP-4.3 drill (2026-05-19) executed it for the reference/local shape: full restore and PITR both recovered the expected raw rows well inside the RPO/RTO targets. See "Restore drill (OP-4.3 / D-055)" below.

Because the base backup is physical and cluster-wide, derived state (embeddings, indexes, retrieval traces, answer traces) restores alongside raw with no replay step; replay from raw under the active parser/embedding versions (I-12) remains a fallback recovery path. Raw loss is unrecoverable, so operational policy treats raw retention as the highest tier.

#### Backup automation (OP-4.2 / D-054)
For the reference Postgres shape (`docker-compose.yml`), WAL archiving is **always on**: the `postgres` service `command:` sets `wal_level=replica`, `archive_mode=on`, `archive_timeout=300`, and an `archive_command` that copies every completed WAL segment into the `memory_rag_pg_archive` volume at `/archive/wal`. The nightly base-backup runner is **opt-in**.

- **Enable the runner.** `make backup-up` (or `docker compose --profile backup up -d`) starts the `pg_backup` sidecar. It runs exactly one long-running `scheduler.sh` process per container; once per calendar day, inside the `BACKUP_WINDOW_START`–`BACKUP_WINDOW_END` local-time window (default `03`–`05`, `TZ`-driven), it takes a base backup then prunes retention. `restart: unless-stopped` keeps it running across host restarts.
- **Run a backup now (one-off).** `make backup-run` runs a single base backup; `make backup-prune` runs retention pruning once. Use only these (or the equivalent `docker compose run --rm --entrypoint sh pg_backup …`) for manual runs — never start a second `scheduler.sh`, which would create a competing scheduler. `backup.sh` and `prune.sh` share an exclusive `flock` on `/archive/.backup.lock`, so a manual run that races the scheduler logs `pg_backup.lock.busy` and exits without overlapping.
- **Where artifacts live.** Base backups: `/archive/base/base-<UTC-ISO8601>/` (tar+gzip, with `backup_manifest` and a `START_WAL` marker) in the `memory_rag_pg_archive` volume. Archived WAL: `/archive/wal/`. Inspect with `docker compose exec postgres ls -la /archive/base /archive/wal`.
- **When did the last backup succeed?** `/archive/last_success.json` records the UTC timestamp, base-backup directory, and prune summary of the last clean cycle; `/archive/last_failure.json` is written on a failed cycle and removed on the next success. Read with `docker compose exec postgres cat /archive/last_success.json`.
- **Logs.** `docker compose logs pg_backup` shows the scheduler. A healthy cycle logs `pg_backup.cycle.begin` → `pg_backup.base.ok` → `pg_backup.prune.ok` → `pg_backup.cycle.ok`; a failed cycle logs `pg_backup.cycle.error stage=backup|prune`; a skipped overlapping run logs `pg_backup.lock.busy`.
- **Retention.** Base backups older than `BASE_RETENTION_DAYS` (default 30) are deleted; `pg_archivecleanup` then drops archived WAL older than the oldest *retained* base backup. With no retained base backup, no WAL is pruned (fail-safe).

Operational warnings:
- **Enable the runner, or WAL grows without bound.** WAL archiving is always on, but only the `pg_backup` runner prunes `/archive/wal`. If the `backup` profile is never started, archived WAL accumulates indefinitely; if `/archive/wal` fills, `archive_command` fails and Postgres holds WAL in `pg_wal` on the data volume — the real disk-pressure path.
- **Enabling archiving needs a Postgres restart.** `archive_mode` / `wal_level` take effect only on a full restart (`docker compose up -d` recreates the `postgres` container). Later edits touching only `archive_command` / `archive_timeout` are reload-able (`SELECT pg_reload_conf();`). Enabling OP-4.2 on a *pre-existing* local volume additionally needs a `docker compose down -v` reset — the `host replication` `pg_hba.conf` rule the backup runner needs is added by an initdb-time hook that runs only at first cluster bootstrap (the A-34 precedent).
- **`docker compose down -v` destroys backups.** `down -v` removes *all* project volumes, including `memory_rag_pg_archive`. For an off-box archive, bind-mount `/archive` to host or external storage instead of relying on the named volume.

#### Restore drill (OP-4.3 / D-055)
Recovering raw `SourceMessage` data from the OP-4.2 artifacts — a base backup plus replayed archived WAL — runs through `scripts/pg_restore/restore.sh` and the opt-in `pg_restore` Compose service (profile `restore`). The same tooling serves the executed drill, the quarterly rerun, and ad-hoc operator restores. It is **not** part of `make check`.

`restore.sh` is operator-grade: it prepares a recovered Postgres data directory on the dedicated, throwaway `memory_rag_pg_restore_data` scratch volume — never the live `memory_rag_pg_data`. It refuses to run against an apparently-live cluster, prints the plan before any write, and a real restore requires an explicit `--yes`.

- **Plan / dry-run first.** `make restore-plan RESTORE_ARGS="--backup-dir=/archive/base/base-<ts> --target=latest"` validates the base backup and archived WAL and prints the plan without changing anything. List available base backups with `docker compose exec postgres ls /archive/base`.
- **Full restore (replay all WAL).** `make restore-run RESTORE_ARGS="--backup-dir=/archive/base/base-<ts> --target=latest --yes"` prepares the recovered data directory; then `docker compose --profile restore up -d pg_restore` starts the recovered cluster (it performs WAL replay and promotes; the `pg_isready` healthcheck flips healthy when recovery completes).
- **Point-in-time recovery.** Pass `--target-timestamp=<ISO-8601>` instead of `--target=latest` to recover to a chosen instant. Use the no-space ISO form, e.g. `--target-timestamp=2026-05-19T06:40:03+00` — a space in the timestamp would be split into a separate argument.
- **Inspect the recovered cluster.** It listens on `RESTORE_PORT` (default `5433`), off the live `5432`. Verify raw rows with `docker compose exec pg_restore psql -U postgres -d memory_rag -c "SELECT count(*) FROM source_messages;"`.
- **Tear down.** `docker compose --profile restore down` stops the recovered cluster (keeps the scratch volume for a re-restore); `docker compose --profile restore down -v` also drops it.
- **Evidence.** Each run writes `/archive/restore_logs/restore-<ts>.log` and a `last_restore.json` marker (status, backup used, recovery target, prep duration). After a drill, record the measured RPO/RTO in a compact evidence file under `docs/op4-drill/` — `op4.3-<YYYYMMDD>-evidence.json` is the OP-4.3 baseline; a quarterly rerun adds a new dated file. The evidence file holds only safe identifiers and counts (no raw payloads, no full Postgres logs).

**Measured result (OP-4.3 drill, 2026-05-19, reference/local shape — `docs/op4-drill/op4.3-20260519-evidence.json`):** a full restore recovered all 15 synthetic raw rows in **5 s**; a PITR restore recovered exactly the pre-target rows in **3 s** — both far inside the **RTO ≤ 1 h** target. WAL archived by a forced switch has a loss window of ~0; an un-switched write is force-archived within `archive_timeout=300`, bounding worst-case raw-write loss at ≤ 5 min — the **RPO ≤ 5 min** target. Both targets **met**. Re-run the drill once before the first non-local deployment, then quarterly, comparing each new evidence file against this baseline.

- **`restore.sh` tracks the OP-4.2 backup format.** It depends on the `base-<ts>/{base.tar.gz,backup_manifest,START_WAL}` layout and the flat `/archive/wal` directory. If a later packet changes the backup format or `/archive` layout, `restore.sh` must change with it.

### Raw export (D-027)
The user can export their raw `SourceMessage` data on demand in JSON (stable field names, ISO timestamps) or TXT (one record per block). The export is scope-bounded the same way retrieval is (R-3 / R-14) and records its own provenance (export id, scope, time range, format, requester). Derived state is not in the minimum export contract — raw is sufficient to reconstruct everything else.

Per-host delivery channels (Telegram file reply, HTTP download endpoint, host-app screen) and the request shape are bracketed as A-39. The implementation lands in its own packet.

## Self-hosted VPS reference shape (DEPLOY-1 / D-060)
D-060 (DEPLOY-1.1) establishes the self-hosted VPS + Telegram contour as the first implemented reference deployment shape, for a single-community pilot. Implementation lands in the DEPLOY-1.x follow-up packets; this section names the **invariants** an operator can rely on for the DEPLOY-1 shape regardless of which DEPLOY-1.x packet ultimately wires it.

- **OS family:** Debian / Ubuntu LTS.
- **Tenancy:** single-community / single-tenant default for the first pilot.
- **Reachability:** public DNS + HTTPS required (not optional). Plain-HTTP pilots are not a DEPLOY-1 shape.
- **Raw-data durability:** off-box backup destination required (S3-compatible or equivalent). A local-only backup is not a sufficient DEPLOY-1 contour — the off-box sink wires the OP-4 WAL + base-backup primitives ("Raw-data durability and recovery" above) to off-box storage.
- **Operator model:** an operator-facing, idempotent install/upgrade script is the canonical bootstrap path. It brings a clean VPS from zero to a working deployment and upgrades it later with a clear status outcome.

Tool-level details (which reverse proxy / TLS terminator, which backup tool, installer language and UX) are **current defaults** revisable in DEPLOY-1.x and not yet pinned. Operator-facing commands and the install script land alongside DEPLOY-1.4 / DEPLOY-1.5 / DEPLOY-1.6.

See `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` for the invariants (mirrored), current defaults, and the DEPLOY-1.x packet sequence; the managed-cloud reference deployment (DEPLOY-2) is deferred there and reopens A-41 when pulled.

### VPS runtime shape (DEPLOY-1.2 / D-061)

DEPLOY-1.2 lands the first runnable VPS runtime contour: an app container plus a one-shot `app_init` migration runner that reuses OP-1 migrations and the OP-4 archive volume shape unchanged. No reverse proxy, no public TLS, no installer, and no off-box backup wiring yet — those land in DEPLOY-1.3..1.6. The two new compose services (`app_init` and `app`) are gated by `profiles: ["vps"]`, so a bare `docker compose up` is unchanged from today (postgres + pg_archive_init only).

The bounded runtime-shape validation uses the **single canonical `docker compose --profile vps` path**:

```bash
# Step 1 — operator env. OPENAI_API_KEY may stay empty for /health.
cp .env.example .env

# Step 2 — build the app image and bring up the vps profile.
docker compose --profile vps up -d --build

# Step 3 — confirm service states.
docker compose --profile vps ps
#   expected:
#     postgres   running (healthy)
#     app_init   exited (0)
#     app        running

# Step 4 — confirm migrations were applied.
docker compose --profile vps logs app_init | grep -F \
  "Postgres migrations applied to head."

# Step 5 — confirm /health.
curl -fsS http://127.0.0.1:8000/health
#   expected (HTTP 200):
#   {"status":"ok","version":"<pkg-version>","env":"local"}
```

Teardown: `docker compose --profile vps down` (without `-v` to preserve the Postgres / archive volumes).

The app port is bound to `127.0.0.1` on the VPS host only. DEPLOY-1.3 (D-062) fronts the app with Caddy and adds the public DNS + HTTPS surface; the loopback publish is retained as an operator-only bypass-the-proxy inspection path. Off-box backup wiring lands in DEPLOY-1.6 — the archive volume `memory_rag_pg_archive` and the OP-4 base / WAL primitives are unchanged from OP-4. The compose-level `STORAGE_BACKEND=postgres` and `POSTGRES_HOST=postgres` overrides on both `app_init` and `app` ensure the VPS contour boots against the real Postgres backend regardless of operator `.env` defaults; the migrations runner is idempotent, so re-issuing `up -d --build` re-runs `app_init` and exits 0 a second time without touching a head-already database.

### Reverse-proxy + TLS contour (DEPLOY-1.3 / D-062)

DEPLOY-1.3 fronts the DEPLOY-1.2 `app` service with a Caddy reverse-proxy that terminates TLS and obtains / renews Let's Encrypt certificates automatically. The `caddy` service is gated by the same `profiles: ["vps"]` as `app_init` / `app`, so a bare `docker compose up` stays byte-equivalent to today (postgres + pg_archive_init only) and the single canonical bring-up path is unchanged: `docker compose --profile vps up -d --build`.

Only two Caddy defaults are relied on: automatic HTTPS for the declared site (provisions + renews a certificate via ACME against `ACME_EMAIL`) and the automatic HTTP → HTTPS redirect for a site declared with an HTTPS host. **No HSTS, no security headers, no rate limits, no `tls internal` fallback** — any further hardening is out of scope for DEPLOY-1.3.

**Operator pre-conditions for the public-TLS contour:**

- A DNS A and/or AAAA record for `$PUBLIC_HOSTNAME` resolves to the VPS host.
- Inbound TCP `80` and `443` are open on the VPS firewall (Caddy needs `:80` for the ACME HTTP-01 challenge and for the HTTP → HTTPS redirect, and `:443` for HTTPS itself).
- `PUBLIC_HOSTNAME` and `ACME_EMAIL` are set in `.env`. **If either is empty or invalid, the public-TLS contour does not come up cleanly and there is no HTTP-only fallback path** — this is an intentional honest failure of the VPS public-TLS contour, not silent degradation.

**Loopback `http://127.0.0.1:8000/health` is operator-only bypass-the-proxy inspection, not a packet-acceptance signal.** A successful loopback `/health` only means `app` itself is up; it does **not** mean the DEPLOY-1.3 public-TLS contour is healthy. The decisive public-contour evidence is the operator smoke below: `https://$PUBLIC_HOSTNAME/health` + HTTP → HTTPS redirect on `:80`.

**Packet-closing local inspection (does not require real DNS or a real-VPS host):**

```bash
# 1. Operator env. PUBLIC_HOSTNAME and ACME_EMAIL must be set for the full
#    --profile vps bring-up; the compose-config parse below uses whatever
#    values .env contains.
cp .env.example .env

# 2. Compose-config parse — confirms the caddy service is declared, the
#    .env knobs interpolate, ports 80:80 + 443:443 are mapped, and the
#    Caddyfile + caddy_data + caddy_config mounts are present.
docker compose --profile vps config

# 3. Caddyfile syntactic validity, with operator-shaped sample values.
docker run --rm \
    -e PUBLIC_HOSTNAME=example.com \
    -e ACME_EMAIL=ops@example.com \
    -v "$PWD/configs/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" \
    caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile
#   expected: "Valid configuration" and exit 0.

# 4. Bare-`up` byte-equivalence — confirms `caddy` is profile-gated and
#    does not regress the DEPLOY-1.2 property that a bare `up` is
#    unchanged from today.
docker compose up -d
docker compose ps
#   expected: postgres (healthy) + pg_archive_init (exited 0) only —
#   no app_init / app / caddy.
docker compose down

# 5. Operator-side convenience (NOT the closure signal): full vps bring-up
#    + loopback inspection still works.
docker compose --profile vps up -d --build
docker compose --profile vps ps
#   expected: postgres running (healthy), app_init exited (0),
#             app running, caddy running.
curl -fsS http://127.0.0.1:8000/health
#   expected (HTTP 200): {"status":"ok","version":"<pkg-version>","env":"local"}
#   This is operator-only bypass-the-proxy inspection, not closure evidence.
```

**Real-VPS operator smoke (the decisive public-contour evidence; NOT a packet-closing gate — clean-VPS pilot smoke is DEPLOY-1.7's responsibility):**

Run from a host outside the VPS (laptop, separate cloud host, etc.), with `$PUBLIC_HOSTNAME` resolving to the VPS and inbound 80/443 open:

```bash
# Public HTTPS probe — terminates at Caddy on the VPS and reverse-proxies
# to app:8000 over the compose network.
curl -fsS -o /dev/null -w '%{http_code}\n' "https://$PUBLIC_HOSTNAME/health"
#   expected: 200

# HTTP -> HTTPS redirect — Caddy's automatic redirect for a site declared
# with an HTTPS host.
curl -sI "http://$PUBLIC_HOSTNAME/health"
#   expected: HTTP/1.1 301 (or 308) with `Location: https://$PUBLIC_HOSTNAME/health`.

# Caddy cert-obtained / TLS handshake-success evidence — read the logs
# (the exact log-line shape is not pinned).
docker compose --profile vps logs caddy
```

If either the public HTTPS probe or the HTTP → HTTPS redirect probe fails, the contour is **not** healthy regardless of what `curl http://127.0.0.1:8000/health` returns on the VPS itself.

Teardown: `docker compose --profile vps down` (without `-v` — Caddy cert + ACME state lives in the `caddy_data` named volume, and `down -v` would force a fresh ACME issuance on the next bring-up, eventually hitting Let's Encrypt rate limits).

### Installer / upgrade script (DEPLOY-1.4 / D-063)

DEPLOY-1.4 wraps the DEPLOY-1.2 + DEPLOY-1.3 bring-up in an operator-facing, idempotent, non-interactive bash installer at `scripts/installer/deploy.sh`. The single canonical operator command becomes `./scripts/installer/deploy.sh` — the installer reads the operator-filled `.env`, preflights, runs the unchanged `docker compose --profile vps up -d --build`, probes the result honestly, and records its outcome in an installer-owned per-host state file. Re-running the installer on an already-installed VPS is non-destructive and idempotent.

**Operator pre-conditions (mirror DEPLOY-1.2 / 1.3, plus the installer surface):**

- Docker and the **Docker Compose v2 plugin** are installed on the host (the installer refuses if `docker compose version` exits non-zero — legacy `docker-compose` v1 is unsupported).
- The repo is cloned to a working directory on the VPS — `Dockerfile`, `docker-compose.yml`, and `pyproject.toml` are co-located (the installer auto-`cd`s to that directory from any cwd).
- `.env` exists at the repo root and has non-empty values for `POSTGRES_PASSWORD`, `PUBLIC_HOSTNAME`, and `ACME_EMAIL` — the three keys the `vps`-profile public-TLS contour requires per DEPLOY-1.3 / D-062. Empty values fail preflight; there is no degraded fallback path.
- DNS for `$PUBLIC_HOSTNAME` resolves to the VPS host and inbound TCP 80 + 443 are open on the VPS firewall — same conditions as the DEPLOY-1.3 real-VPS operator smoke.

**Configuration-versioning seam (the D-060 mitigation):**

- The script carries an `INSTALLER_CONFIG_VERSION=1` constant.
- The state file `.installer-state.json` next to the repo root carries the deployed view as `installer_config_version`. It is installer-owned — operators do not edit it. It is gitignored alongside its sibling failure marker `.installer-state.last_failure.json`.
- On each run the script compares the two views:
  - Equal → idempotent re-run; reapplies the canonical bring-up and refreshes `last_install_timestamp`.
  - Deployed < script → applies the appropriate `migrate_v<old>_to_v<new>` helpers in order, then re-applies, then bumps the stored version. At v1 only `migrate_to_v1` exists (a no-op stamp on a fresh install).
  - Deployed > script → **refused** with `deploy.upgrade.error deployed config v<N> is newer than this installer v1; upgrade the installer before re-running`; exits non-zero without invoking `docker compose up`; writes `.installer-state.last_failure.json`; leaves `.installer-state.json` byte-equivalent.
- Future DEPLOY-1.x packets that swap or add a default (e.g., DEPLOY-1.6 pinning the backup-tool default) bump `INSTALLER_CONFIG_VERSION` and add a new `migrate_v<old>_to_v<new>` helper rather than rewriting the installer.

**Honest status outcome — `loopback_health` is mandatory; `public_tls_probe` is best-effort.** Consistent with DEPLOY-1.3 / D-062, the installer never inflates the loopback `/health` success into a public-TLS claim:

- After a successful `docker compose up`, the installer polls `http://127.0.0.1:8000/health` (bounded retry: 15 × 2 s = up to 30 s). A non-200 result fails the run, writes the failure marker, and exits non-zero. This loopback probe confirms `app` came up — it is **not** public-TLS closure evidence.
- The installer then attempts `https://$PUBLIC_HOSTNAME/health` only when `PUBLIC_HOSTNAME` is set AND resolves on the host (a single `getent hosts` lookup). The outcome is recorded as one of `"ok"` / `"failed"` / `"skipped (PUBLIC_HOSTNAME unset)"` / `"skipped (hostname did not resolve)"`. A skipped or failed public-TLS probe does **not** fail the run — the decisive clean-VPS public-contour evidence remains DEPLOY-1.7's responsibility.

**Subcommands:**

```bash
# Canonical operator command — install on a fresh host, idempotent re-run
# on an installed host, runs migration helpers when the deployed config is
# older than the installer.
./scripts/installer/deploy.sh

# Preflight only — reads inputs, writes nothing. Exits 0 if all
# preconditions are satisfied; non-zero with the same `deploy.preflight.error
# ...` diagnostic as the install path otherwise.
./scripts/installer/deploy.sh --check

# Print .installer-state.json, or "not installed (no .installer-state.json
# at <repo>)" if absent. Exits 0.
./scripts/installer/deploy.sh --status

# Print INSTALLER_CONFIG_VERSION (the installer's view). Exits 0.
./scripts/installer/deploy.sh --version

# Print usage.
./scripts/installer/deploy.sh --help
```

**Packet-closing local inspection (does not require a real VPS or real DNS):**

```bash
# 1. Syntactic validity.
bash -n scripts/installer/deploy.sh
#   expected: exit 0, no output.

# 2. Subcommand smoke (no state writes).
./scripts/installer/deploy.sh --version    # expected: "2" (was "1" pre-DEPLOY-1.5 / D-064)
./scripts/installer/deploy.sh --help       # expected: usage block (includes --unregister-webhook)
./scripts/installer/deploy.sh --status     # expected: "not installed (...)" on first run

# 3. Preflight error path — missing .env. Writes neither state file.
rm -f .env .installer-state.json .installer-state.last_failure.json
./scripts/installer/deploy.sh --check
#   expected (exit 1):
#   deploy.preflight.error missing .env at <repo>/.env — copy .env.example ...

# 4. Preflight error path — required keys empty. Writes neither state file.
cp .env.example .env
./scripts/installer/deploy.sh --check
#   expected (exit 1):
#   deploy.preflight.error .env is missing or empty for required keys:
#     PUBLIC_HOSTNAME ACME_EMAIL TELEGRAM_BOT_TOKEN TELEGRAM_WEBHOOK_SECRET — fill them ...

# 5. Preflight ok path — all five required keys filled. Writes nothing.
sed -i 's/^PUBLIC_HOSTNAME=$/PUBLIC_HOSTNAME=example.com/; \
        s/^ACME_EMAIL=$/ACME_EMAIL=ops@example.com/; \
        s/^TELEGRAM_BOT_TOKEN=$/TELEGRAM_BOT_TOKEN=placeholder-bot-token/; \
        s/^TELEGRAM_WEBHOOK_SECRET=$/TELEGRAM_WEBHOOK_SECRET=placeholder-secret/' .env
./scripts/installer/deploy.sh --check
#   expected (exit 0):
#   deploy.preflight.ok installer_config_version=2 repo_root=<repo>

# 6. Bare-up byte-equivalence — DEPLOY-1.4 / 1.5 do not regress DEPLOY-1.2 / 1.3.
docker compose config --services | sort
#   expected: pg_archive_init, postgres
docker compose --profile vps config --services | sort
#   expected: app, app_init, caddy, pg_archive_init, postgres

# 7. Future-version refusal — does not invoke `docker compose up`.
cat > .installer-state.json <<'JSON'
{ "installer_config_version": 99,
  "selected_defaults": { "reverse_proxy": "caddy", "installer_impl": "bash", "backup_tool": null },
  "last_install_timestamp": "2099-01-01T00:00:00Z",
  "last_outcome": "success",
  "loopback_health": "ok", "public_tls_probe": "ok",
  "webhook_registration": { "status": "registered (https://example.com/telegram/webhook)", "url": "https://example.com/telegram/webhook", "attempted_at": "2099-01-01T00:00:00Z" } }
JSON
./scripts/installer/deploy.sh
#   expected (exit 1):
#   deploy.upgrade.error deployed config v99 is newer than this installer
#     v2; upgrade the installer before re-running
#   .installer-state.last_failure.json is written; .installer-state.json is
#   left byte-equivalent to the hand-edited input.
rm -f .installer-state.json .installer-state.last_failure.json
```

**Real-VPS operator smoke (the decisive public-contour evidence; NOT a packet-closing gate — clean-VPS pilot smoke + the upgrade drill is DEPLOY-1.7's responsibility):**

Run from the VPS itself, after the operator pre-conditions are satisfied (now also including the two Telegram credential keys per DEPLOY-1.5 / D-064):

```bash
./scripts/installer/deploy.sh
#   expected (exit 0):
#   deploy.install.ok upgraded v0->v2 loopback_health=ok public_tls_probe="ok"
#     webhook_registration="registered (https://<host>/telegram/webhook)"
#   (or "already_at_v2 re-applied ..." on a second invocation)

./scripts/installer/deploy.sh --status
#   expected: .installer-state.json contents with
#   "installer_config_version": 2, "last_outcome": "success",
#   "loopback_health": "ok", "public_tls_probe": "ok",
#   "webhook_registration": { "status": "registered (...)", "url": "...", "attempted_at": "..." }.
```

The decisive public-contour evidence (HTTPS `/health` probe + HTTP → HTTPS redirect) remains as documented in the DEPLOY-1.3 subsection above — the installer wraps the bring-up; it does not redefine that closure evidence.

**Teardown** is unchanged from DEPLOY-1.3: `docker compose --profile vps down` (without `-v`). `.installer-state.json` survives a teardown, so the next `./scripts/installer/deploy.sh` is an idempotent re-run, not a fresh install. To force a true fresh install, also remove `.installer-state.json` (this does not delete data — the Postgres / archive / Caddy named volumes still survive).

### Telegram webhook registration (DEPLOY-1.5 / D-064)

DEPLOY-1.5 folds Telegram webhook registration into the canonical install flow and adds an `--unregister-webhook` teardown subcommand. The webhook is registered against the DEPLOY-1.3 public-TLS contour (`https://$PUBLIC_HOSTNAME/telegram/webhook`) using the operator-filled `TELEGRAM_WEBHOOK_SECRET`; the result is recorded honestly in `.installer-state.json` under a new `webhook_registration` block. `INSTALLER_CONFIG_VERSION` bumps `1 → 2`; existing v1 deployments advance via the no-op `migrate_v1_to_v2` stamp on the next install run.

**Operator pre-conditions (extend DEPLOY-1.4's set):**

- `.env` has non-empty values for `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` — both are now part of `REQUIRED_ENV_KEYS` and empty values fail preflight (same error shape as the existing three keys).
- The operator generates `TELEGRAM_WEBHOOK_SECRET` out of band (e.g. `openssl rand -hex 32`) and writes it into `.env`. The installer reads `.env` and does not write it (D-063-confirmed UX).
- The DEPLOY-1.3 public-TLS contour is reachable (`https://$PUBLIC_HOSTNAME/health` returns 200) — webhook registration depends on it.

**Lifecycle (initial / rotation / teardown):**

- **Initial registration.** `./scripts/installer/deploy.sh` runs `setWebhook` against `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook` with `url=https://${PUBLIC_HOSTNAME}/telegram/webhook` and `secret_token=${TELEGRAM_WEBHOOK_SECRET}` after the loopback + public-TLS probes succeed. Bounded retry: 3 attempts × 2 s = up to 6 s. The `webhook_registration` block in `.installer-state.json` records one of:
  - `"registered (https://<host>/telegram/webhook)"` — Telegram returned `"ok":true`.
  - `"skipped (public_tls_probe=<value>)"` — the upstream public-TLS probe was not `ok`, so webhook registration was not attempted.
  - `"failed (<short reason ≤200 chars>)"` — Telegram returned a non-ok response or the 6 s budget expired. The reason field is the first 200 characters of the response body (or a synthetic timeout message).
- **Rotation.** Re-run `./scripts/installer/deploy.sh`. Telegram's `setWebhook` is idempotent — a repeated call overwrites the prior URL and secret. To rotate the webhook secret: edit `TELEGRAM_WEBHOOK_SECRET` in `.env`, then re-run the installer; `docker compose --profile vps up -d --build` recreates the `app` container so the new secret takes effect on the receiving side at the same time.
- **Teardown.** `./scripts/installer/deploy.sh --unregister-webhook` calls `deleteWebhook` against the bot token in `.env`. On `"ok":true` it clears the `webhook_registration` block in `.installer-state.json` (setting `status="unregistered"`, `url=null`, fresh `attempted_at`) and exits 0 with `deploy.webhook.unregistered ok`. On a Telegram non-ok response or filesystem error it exits non-zero and leaves the state file untouched. The clearing step is skipped when `.installer-state.json` is absent (the API call still runs).

**Honest registration outcome.** Webhook registration is **best-effort** — a failure does not fail the install run on its own; `last_outcome="success"` still requires only the mandatory loopback `/health` to be `"ok"`. This mirrors the DEPLOY-1.4 honest-distinction contract for `public_tls_probe`. The three honest verdicts are surfaced separately in the state file and in the `deploy.install.ok ...` log line.

**Packet-closing local inspection (does not require a real VPS, real DNS, or a real Telegram bot):**

```bash
# 1. Syntactic validity.
bash -n scripts/installer/deploy.sh
#   expected: exit 0, no output.

# 2. Version + help reflect the bump.
./scripts/installer/deploy.sh --version    # expected: "2"
./scripts/installer/deploy.sh --help       # expected: usage block lists --unregister-webhook

# 3. Preflight surfaces the two new keys.
rm -f .env .installer-state.json .installer-state.last_failure.json
cp .env.example .env
./scripts/installer/deploy.sh --check
#   expected (exit 1):
#   deploy.preflight.error .env is missing or empty for required keys:
#     POSTGRES_PASSWORD PUBLIC_HOSTNAME ACME_EMAIL TELEGRAM_BOT_TOKEN
#     TELEGRAM_WEBHOOK_SECRET — fill them ...
#   (POSTGRES_PASSWORD only appears here if .env.example's "postgres" default
#   was overwritten with an empty value; the unmodified .env.example carries
#   POSTGRES_PASSWORD=postgres, which passes preflight non-empty.)

# 4. Preflight passes once all five keys are filled.
sed -i 's/^POSTGRES_PASSWORD=postgres$/POSTGRES_PASSWORD=postgres-secret/; \
        s/^PUBLIC_HOSTNAME=$/PUBLIC_HOSTNAME=example.com/; \
        s/^ACME_EMAIL=$/ACME_EMAIL=ops@example.com/; \
        s/^TELEGRAM_BOT_TOKEN=$/TELEGRAM_BOT_TOKEN=placeholder-bot-token/; \
        s/^TELEGRAM_WEBHOOK_SECRET=$/TELEGRAM_WEBHOOK_SECRET=placeholder-secret/' .env
./scripts/installer/deploy.sh --check
#   expected (exit 0):
#   deploy.preflight.ok installer_config_version=2 repo_root=<repo>

# 5. --unregister-webhook refuses cleanly when credentials are absent.
rm -f .env
./scripts/installer/deploy.sh --unregister-webhook
#   expected (exit 1):
#   deploy.webhook.error missing .env at <repo>/.env — fill TELEGRAM_BOT_TOKEN before unregistering

cp .env.example .env   # TELEGRAM_BOT_TOKEN is still empty in .env.example
./scripts/installer/deploy.sh --unregister-webhook
#   expected (exit 1):
#   deploy.webhook.error TELEGRAM_BOT_TOKEN unset in .env — cannot call deleteWebhook

rm -f .env

# 6. Forward-version refusal at the v2 installer.
cat > .installer-state.json <<'JSON'
{ "installer_config_version": 99,
  "selected_defaults": { "reverse_proxy": "caddy", "installer_impl": "bash", "backup_tool": null },
  "last_install_timestamp": "2099-01-01T00:00:00Z",
  "last_outcome": "success",
  "loopback_health": "ok", "public_tls_probe": "ok",
  "webhook_registration": { "status": "registered (https://example.com/telegram/webhook)", "url": "https://example.com/telegram/webhook", "attempted_at": "2099-01-01T00:00:00Z" } }
JSON
./scripts/installer/deploy.sh
#   expected (exit 1):
#   deploy.upgrade.error deployed config v99 is newer than this installer
#     v2; upgrade the installer before re-running
rm -f .installer-state.json .installer-state.last_failure.json

# 7. Bare-up byte-equivalence preserved at the v2 installer.
docker compose config --services | sort
#   expected: pg_archive_init, postgres
docker compose --profile vps config --services | sort
#   expected: app, app_init, caddy, pg_archive_init, postgres
```

**Real-VPS operator smoke (NOT a packet-closing gate — clean-VPS pilot smoke + the upgrade drill is DEPLOY-1.7's responsibility):**

Run from the VPS itself, after all five required keys are filled (with a real bot token + secret):

```bash
./scripts/installer/deploy.sh
#   expected (exit 0):
#   deploy.install.ok upgraded v0->v2 loopback_health=ok public_tls_probe="ok"
#     webhook_registration="registered (https://<host>/telegram/webhook)"

./scripts/installer/deploy.sh --status
#   expected: .installer-state.json with
#   "installer_config_version": 2, "last_outcome": "success",
#   "loopback_health": "ok", "public_tls_probe": "ok",
#   "webhook_registration": {
#     "status": "registered (https://<host>/telegram/webhook)",
#     "url": "https://<host>/telegram/webhook",
#     "attempted_at": "<ISO>"
#   }.

./scripts/installer/deploy.sh --unregister-webhook
#   expected (exit 0):
#   deploy.webhook.unregistered ok
#   (.installer-state.json now records webhook_registration.status="unregistered",
#   url=null, attempted_at=<now>; Telegram getWebhookInfo returns an empty URL.)
```

A real Telegram update sent to `https://<host>/telegram/webhook` after the canonical install is then handled by the FastAPI receiver per D-019 / A-26 (the existing webhook secret comparison is fail-closed). The end-to-end round-trip is exercised by DEPLOY-1.7.

### Off-box backup sink (DEPLOY-1.6 / D-065)

DEPLOY-1.6 wires the existing OP-4.2 `/archive/base` + `/archive/wal` artifacts to an operator-supplied S3-compatible destination via a new `pg_offbox_uploader` sidecar service running `rclone sync`. The DEPLOY-1 §2 invariant ("off-box backup destination required") is the closure signal for DEPLOY-1.7's clean-VPS pilot smoke; DEPLOY-1.6 wires the seam and surfaces honest probe / upload outcomes.

**Operator pre-conditions (additive to the DEPLOY-1.4 / 1.5 pre-conditions):**

- An S3-compatible bucket exists (AWS S3, Cloudflare R2, Backblaze B2, Wasabi, MinIO, …) and the operator has access-key credentials with object read / write on it.
- `.env` carries the off-box knobs in the new "Off-box backup sink (DEPLOY-1.6 / D-065)" section (see `.env.example`):
  - `BACKUP_S3_BUCKET` — target bucket name (required to enable off-box).
  - `BACKUP_S3_ENDPOINT` — S3-compatible endpoint URL; leave blank for AWS S3 itself; set for R2 / B2 / Wasabi / MinIO.
  - `BACKUP_S3_PATH_PREFIX` — object prefix; defaults to `archive` (artifacts land at `<prefix>/base/...` and `<prefix>/wal/...`).
  - `BACKUP_S3_ACCESS_KEY_ID` / `BACKUP_S3_SECRET_ACCESS_KEY` — credentials.
  All five knobs are **optional** — none join `REQUIRED_ENV_KEYS`. With them unset, both the installer probe and the uploader log `skipped (...)` outcomes and `pg_backup.cycle.ok` semantics are unaffected.

**Installer probe (`offbox_backup_probe`).** The canonical `./scripts/installer/deploy.sh` (DEPLOY-1.4) runs an active off-box probe after the DEPLOY-1.5 webhook-registration step: a one-shot `timeout 6 docker run --rm -e RCLONE_CONFIG_OFFBOX_* rclone/rclone:1.66 lsd offbox:<bucket>` against the configured remote, preceded by a separate `timeout 60 docker pull -q rclone/rclone:1.66` step that runs only when `docker image inspect` reports the image absent. The probe is best-effort — a non-`ok` outcome never fails the install; `last_outcome="success"` still requires only the mandatory loopback `/health` to be `"ok"` (mirrors `public_tls_probe` / `webhook_registration` semantics). The outcome is recorded in `.installer-state.json` under `offbox_backup_probe` as one of:

```
"ok"                                          # bucket reachable, credentials accepted
"skipped (BACKUP_S3_BUCKET unset)"            # operator opted out
"skipped (BACKUP_S3_ACCESS_KEY_ID unset)"     # bucket set, credentials missing
"skipped (BACKUP_S3_SECRET_ACCESS_KEY unset)" # bucket set, credentials missing
"failed (<short reason ≤200 chars>)"          # rclone lsd did not return 0
```

…and surfaced in the final `deploy.install.ok ... offbox_backup_probe="..."` log line alongside `public_tls_probe` and `webhook_registration`. The first invocation pays up to the 60 s pull budget for the rclone image; subsequent invocations reuse the cached image and only spend the 6 s probe budget.

**Off-box uploader lifecycle.** The `pg_offbox_uploader` service (image `rclone/rclone:1.66`, gated by `profiles: ["backup"]`) starts alongside the existing `pg_backup` sidecar when the operator runs:

```sh
docker compose --profile backup up -d
#   memory_rag_pg_backup           (OP-4.2 nightly base-backup runner)
#   memory_rag_pg_offbox_uploader  (DEPLOY-1.6 / D-065 off-box uploader)
```

The uploader is a long-running poll loop (polls `/archive/last_success.json` every 600 s). When it observes a previously-unseen cycle timestamp, it runs `rclone sync /archive/base remote:<bucket>/<prefix>/base` then `rclone sync /archive/wal remote:<bucket>/<prefix>/wal` and records the outcome in `/archive/last_offbox.json`. `rclone sync` is idempotent — already-present files at the remote are skipped, so a cold-start re-upload only transfers what has changed. The uploader **never writes** to `/archive/base`, `/archive/wal`, or `/archive/last_success.json` — only `/archive/last_offbox.json`. A sink failure does NOT degrade `pg_backup.cycle.ok` or the OP-4.2 durable signal at `/archive/last_success.json`.

**Inspect what the uploader is doing.**

```sh
docker compose logs pg_offbox_uploader
#   healthy cycle:
#     pg_backup.offbox.start bucket=<…> endpoint=<…> prefix=archive poll_seconds=600
#     pg_backup.offbox.begin base=base-2026-05-21T03:00:00Z ts=<…>
#     pg_backup.offbox.ok base=base-2026-05-21T03:00:00Z
#   missing credentials (logged once per state change, not once per poll):
#     pg_backup.offbox.skipped reason=BACKUP_S3_BUCKET unset
#     pg_backup.offbox.skipped reason=BACKUP_S3_ACCESS_KEY_ID unset
#     pg_backup.offbox.skipped reason=BACKUP_S3_SECRET_ACCESS_KEY unset
#   sink failure (categorized — never echoes credentials):
#     pg_backup.offbox.error stage=<base|wal> reason=<auth_failed|network|remote_error|temporary|fatal> rc=<n>

docker compose exec pg_backup cat /archive/last_offbox.json
#   {
#     "timestamp": "<UTC ISO matching last_success.json>",
#     "base_backup": "base-2026-05-21T03:00:00Z",
#     "status": "ok",
#     "error": null
#   }
```

**What to do when the sink probe says `failed (...)`.**

1. Re-read the reason text on the `deploy.install.ok ... offbox_backup_probe="failed (...)"` log line — it is the first 200 characters of rclone's stderr. Common causes: bucket does not exist; credentials denied; endpoint URL typo; bucket region mismatch.
2. Confirm the five `BACKUP_S3_*` knobs are filled correctly in `.env` — secrets are never auto-rotated by the installer (the installer reads `.env` and does not write it, per D-063).
3. Re-run `./scripts/installer/deploy.sh` after the fix — the probe re-runs and the state file is rewritten with the new verdict.
4. If the canonical install reported `offbox_backup_probe="ok"` but the uploader subsequently logs `pg_backup.offbox.error`, the most common cause is a credential rotation between the install and the next cycle. Update `.env`, then `docker compose --profile backup restart pg_offbox_uploader` to pick up the new values.

**Packet-closing local inspection (no real S3 endpoint required).** Mirrors the DEPLOY-1.4 / 1.5 packet-closing blocks above; included here so an operator can verify the DEPLOY-1.6 seam shape on a dev host before pointing it at a real bucket.

```sh
./scripts/installer/deploy.sh --version
#   expected (exit 0):
#   3

# Profile parity — pg_offbox_uploader must NOT appear under --profile vps
# (the installer's bring-up) and must appear under --profile backup.
docker compose --profile vps config --services | sort
#   expected (exit 0):
#   app app_init caddy pg_archive_init postgres
docker compose --profile backup config --services | sort
#   expected (exit 0):
#   pg_archive_init pg_backup pg_offbox_uploader postgres

# Bare-up byte-equivalence preserved.
docker compose config --services | sort
#   expected (exit 0):
#   pg_archive_init postgres

# Future-version refusal still works at v3.
# 1) hand-edit .installer-state.json:installer_config_version to 99
# 2) ./scripts/installer/deploy.sh
#   expected (exit 1):
#   deploy.upgrade.error deployed config v99 is newer than this installer v3 ...
#   (.installer-state.last_failure.json written; .installer-state.json byte-equivalent to input)
```

**Real-VPS operator smoke (NOT a packet-closing gate; clean-VPS pilot smoke + the off-box-backup §2-invariant verification is DEPLOY-1.7's responsibility):**

- From a clean Debian / Ubuntu LTS VPS with the DEPLOY-1.5 pre-conditions plus the five `BACKUP_S3_*` knobs filled against a reachable S3-compatible bucket: `./scripts/installer/deploy.sh` exits 0 with `deploy.install.ok ... offbox_backup_probe="ok"`; `--status` shows the v3 state file with `"selected_defaults.backup_tool": "rclone"` and `"offbox_backup_probe": "ok"`.
- `docker compose --profile backup up -d` starts both `pg_backup` and `pg_offbox_uploader`; after the next nightly cycle (or a manual `make backup-run`), `docker compose logs pg_offbox_uploader` shows the `pg_backup.offbox.begin → pg_backup.offbox.ok` sequence; the remote bucket contains `<prefix>/base/base-<ts>/...` and `<prefix>/wal/...`; `/archive/last_offbox.json` records `status=ok` with the same `timestamp` and `base_backup` as `/archive/last_success.json`.
- Sink-failure additivity smoke: stopping the S3 endpoint mid-upload (or rotating in a bogus credential) yields `pg_backup.offbox.error stage=<base|wal> reason=<class> rc=<n>`; `/archive/last_success.json` is unchanged; `pg_backup.cycle.ok` is still the most recent cycle outcome in `docker compose logs pg_backup`; `/archive/last_offbox.json` records `status=error` with a categorized reason — no credential text appears in the log.

### Local-only upgrade-drill preflight (DEPLOY-1.7-preflight / D-066)

DEPLOY-1.7-preflight adds a local-only upgrade-drill harness at `scripts/installer/drill_upgrade_local.sh` that exercises the D-063 configuration-versioning seam (`INSTALLER_CONFIG_VERSION` + the `migrate_v<old>_to_v<new>` chain) against **real prior packet commits** via a sandboxed git worktree under `mktemp -d`. The harness de-risks the seam locally — it does **not** close DEPLOY-1.7 and DEPLOY-1 remains open. The decisive clean-VPS → working-pilot smoke + the real off-box-backup verification + the real Telegram webhook round-trip + the real public-DNS / ACME-issued cert path all stay DEPLOY-1.7's responsibility.

**Operator pre-conditions:**

- Dev host with Docker + Compose v2 + `git` + `mktemp` + `python3` on `PATH`.
- The main repo is a working git checkout (the harness uses `git worktree add` against the main repo's `.git` directory).
- The three prior packet commits are reachable in the local repo (`7cb96fa` — DEPLOY-1.4; `e435e1a` — DEPLOY-1.5; `0aef179` — DEPLOY-1.6). On a freshly-cloned shallow clone, `git fetch --unshallow` once.
- **No** clean-working-tree requirement: the harness operates entirely inside its throwaway worktree and never modifies the main repo working tree.

**How to run:**

```sh
./scripts/installer/drill_upgrade_local.sh
```

Single command, no flags. The harness:

1. Resolves the main repo root via the same `Dockerfile + docker-compose.yml + pyproject.toml` co-located predicate that `scripts/installer/deploy.sh` uses (line 93 of deploy.sh).
2. Creates a throwaway worktree at `$(mktemp -d -t deploy1-preflight-drill-XXXXXX)/repo` via `git worktree add --detach <path> HEAD` and prints its absolute path on stdout.
3. Exports `COMPOSE_PROJECT_NAME=deploy1-preflight-drill` so named volumes survive across legs (the v1 → v2 → v3 chain advances against persisted Postgres + archive state) and the drill's Docker objects stay isolated from any operator compose project running against the main repo with the default project name.
4. Runs three legs in order: leg 1 = `7cb96fa` (DEPLOY-1.4, `INSTALLER_CONFIG_VERSION=1`); leg 2 = `e435e1a` (DEPLOY-1.5, `INSTALLER_CONFIG_VERSION=2`); leg 3 = `0aef179` (DEPLOY-1.6, `INSTALLER_CONFIG_VERSION=3`). For each leg the harness `git checkout`s the commit inside the worktree, regenerates `.env` with benign values (non-resolvable `PUBLIC_HOSTNAME=deploy1-preflight.invalid`, placeholder Telegram credentials, unset `BACKUP_S3_*`), invokes the worktree-local `./scripts/installer/deploy.sh`, snapshots `.installer-state.json` + `.installer-state.last_failure.json` verbatim, captures the final `deploy.install.ok ...` line, and records the elapsed wall-clock.
5. Skips `docker compose down` between legs — leaving services running mimics the real "upgrade an already-running install" operator path and lets the next leg's `docker compose --profile vps up -d --build` rebuild the changed image layers while reusing healthy volumes.
6. After leg 3, `docker compose --profile vps down` (no `-v` — volumes survive for operator post-mortem).
7. Assembles the evidence artifact at `docs/deploy1-drill/deploy1-upgrade-drill-<YYYYMMDD>-evidence.json` (UTC date) from the per-leg captures inside the worktree, via an embedded `python3` step.
8. On success, the EXIT trap removes the worktree + tempdir. On failure / interrupt, it leaves both in place and prints the absolute path so the operator can inspect, then run `git -C <main-repo> worktree remove --force <path>` manually.

**What the harness confirms locally:**

- `installer_config_version` chain advance: `0 → 1 → 2 → 3` across the three legs, on real prior-version installer + runtime state (not hand-edited state files — per `[[feedback_real_prior_version_evidence]]`).
- State-file shape transitions per leg (observed verbatim in the captured `state_file_after` snapshots in the evidence artifact): the v1 state file does not carry `webhook_registration` or `offbox_backup_probe`; the v2 state file carries `webhook_registration` but not `offbox_backup_probe`; the v3 state file carries both `offbox_backup_probe` and the `selected_defaults.backup_tool="rclone"` flip from `null`.
- Migration helper ordering (`migrate_to_v1` → `migrate_v1_to_v2` → `migrate_v2_to_v3` fired in expected sequence) — inferred from the chain advance.

**What the harness does NOT confirm (DEPLOY-1.7's responsibility):**

- Real public DNS for `PUBLIC_HOSTNAME` + ACME-issued cert.
- Real Telegram `setWebhook` → FastAPI receiver round-trip.
- Real S3-compatible bucket reachability + `rclone sync` of `/archive/base` + `/archive/wal` artifacts.

The probe verdicts the installer emits in this environment (`public_tls_probe`, `webhook_registration`, `offbox_backup_probe`) are captured **verbatim** under `observed_probes` per leg in the evidence artifact, and classified as `operator_dependent`. They are recorded as observations — the harness does not pre-assert their exact strings.

**Caddy noise advisory.** The non-resolvable `*.invalid` `PUBLIC_HOSTNAME` deliberately fails the ACME-HTTP-01 challenge; Caddy retries indefinitely and emits errors to its log. This is the mechanism by which `probe_public_tls` returns a non-`ok` outcome and is one of the `operator_dependent` conditions the drill records, not a failure of the harness.

**Where evidence lives.** The committed artifact is `docs/deploy1-drill/deploy1-upgrade-drill-<YYYYMMDD>-evidence.json` (UTC-dated; parallel to `docs/op4-drill/op4.3-<YYYYMMDD>-evidence.json`). Per-leg leg logs and verbatim state-file snapshots live inside the worktree at `<worktree>/.preflight-drill-logs/` and `<worktree>/.preflight-drill-evidence/` during the run; on success, they are removed with the worktree.

**Cleanup model.** Docker volumes (under `COMPOSE_PROJECT_NAME=deploy1-preflight-drill`) are not removed automatically — the operator can run `docker compose --project-name deploy1-preflight-drill --profile vps down -v` to clean them, scoped to the drill's project name so any other compose project's state is untouched.

**This harness de-risks the configuration-versioning seam locally — DEPLOY-1.7 remains the closure packet for DEPLOY-1.**

### Clean-VPS pilot smoke (DEPLOY-1.7a / D-067)

DEPLOY-1.7a closes the clean-VPS → working-pilot smoke and the off-box backup §2-invariant verification halves of the DEPLOY-1.7 scope split (see D-067 and the `SELF-HOSTED-DEPLOYMENT-ROADMAP.md` §4 row split). Closure is by the committed evidence artifact at `docs/deploy1-drill/deploy1-pilot-smoke-<YYYYMMDD>-evidence.json` (UTC-dated; parallel to `docs/deploy1-drill/deploy1-upgrade-drill-<YYYYMMDD>-evidence.json` from D-066), exercising **real public DNS + ACME-issued cert**, **real Telegram `setWebhook` → FastAPI round-trip**, and a **real S3-compatible bucket** off-box upload + additivity smoke. The v2 → v3 cross-version upgrade drill against a real previously-installed v2 VPS stays out of scope here — see DEPLOY-1.7b for that closure leg.

**Operator pre-conditions:**

- Clean Debian / Ubuntu LTS VPS reachable on its public hostname; DNS A/AAAA records for `$PUBLIC_HOSTNAME` already in place and resolving from the public internet so Caddy's ACME-HTTP-01 challenge can succeed.
- `.env` populated per the §"Installer / upgrade script (DEPLOY-1.4 / D-063)" + §"Telegram webhook registration (DEPLOY-1.5 / D-064)" + §"Off-box backup sink (DEPLOY-1.6 / D-065)" subsections: `PUBLIC_HOSTNAME`, `ACME_EMAIL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, and **all five `BACKUP_S3_*` knobs** pointing at a reachable S3-compatible bucket the operator owns.
- A Telegram client (mobile or desktop) signed in as a user able to talk to the bot.

**How to run:**

```sh
# 1. Install / upgrade on the clean VPS.
bash scripts/installer/deploy.sh

# 2. Snapshot the installer state file verbatim into the evidence artifact.
cat .installer-state.json

# 3. Confirm the public health endpoint and capture its body.
curl -sS https://$PUBLIC_HOSTNAME/health

# 4. Send /start to the bot from a Telegram client. From the app container's
#    logs, capture the `telegram.webhook ... route=start ...` log line and the
#    matching access log `POST /telegram/webhook 200`. Note the wall-clock
#    latency between the client send and the user-visible reply.
docker compose logs --tail=200 app | grep telegram.webhook

# 5. Note that `getUpdates` against the bot token returns HTTP 409 while the
#    webhook is active — EXPECTED, not a defect.
curl -sS https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getUpdates

# 6. Off-box happy path: wait for one full nightly cycle (or run a one-off
#    `make backup-run` to trigger it), then capture the uploader's begin/ok
#    log lines + the cursor file + a remote listing summary.
docker compose logs --tail=50 pg_offbox_uploader | grep pg_backup.offbox
docker compose exec pg_backup cat /archive/last_offbox.json
# Use `rclone lsf` or the operator's S3 client to summarize <prefix>/base/...
# and <prefix>/wal/... presence (object counts, not contents).

# 7. Off-box additivity smoke: force an upload failure (stop endpoint / revoke
#    credentials / break network), trigger another cycle, capture the cursor
#    flipping to status=error, confirm last_success.json is unchanged, and
#    confirm pg_backup.cycle.ok is still emitted.
docker compose exec pg_backup cat /archive/last_offbox.json
docker compose exec pg_backup cat /archive/last_success.json
docker compose logs --tail=50 pg_backup | grep pg_backup.cycle
```

The result is assembled by hand into the evidence artifact at `docs/deploy1-drill/deploy1-pilot-smoke-<YYYYMMDD>-evidence.json`. See the parallel D-066 artifact `docs/deploy1-drill/deploy1-upgrade-drill-20260522-evidence.json` for the shape precedent; the DEPLOY-1.7a artifact carries two top-level branches — `pilot_smoke` (installer state, `/health` body, Telegram round-trip + observed latency, `getUpdates=409` framing) and `offbox_backup_verification` (happy path + additivity smoke) — plus `out_of_scope_for_this_packet` and a `summary` with `closes_deploy_1_7a: true`, `closes_deploy_1_7: false`, `closes_deploy_1: false`.

**Redaction rule (mandatory).** No credential text, bucket name, endpoint URL, prefix value, public hostname, or Telegram URL token may appear in the captured evidence file. Capture structural outcomes (status strings, log-line shapes, `"ok"` / `"error"` transitions, the boolean additivity assertions) **verbatim**; replace identifying values with `<REDACTED>` or a `_redacted: true` flag. Pre-commit, grep the artifact for the literal `$PUBLIC_HOSTNAME`, `$BACKUP_S3_BUCKET`, `$BACKUP_S3_ENDPOINT`, `$BACKUP_S3_PATH_PREFIX`, `$BACKUP_S3_ACCESS_KEY_ID`, `$BACKUP_S3_SECRET_ACCESS_KEY`, and `$TELEGRAM_BOT_TOKEN` values and confirm none appear literally.

**getUpdates=409 framing.** Telegram documents `setWebhook` and `getUpdates` as mutually exclusive: while a webhook is registered, `getUpdates` returns HTTP 409 (`Conflict: can't use getUpdates method while there is an active webhook`). The smoke captures this verbatim in the evidence artifact as **expected with webhook active**, not as a defect.

**DEPLOY-1.7a closes the pilot-smoke + off-box §2-invariant verification halves of DEPLOY-1.7. DEPLOY-1.7b (v2 → v3 cross-version upgrade drill on a real previously-installed v2 VPS) is the sole canonical remaining packet for DEPLOY-1 closure.**

### v2 → v3 cross-version upgrade drill (DEPLOY-1.7b / D-068)

DEPLOY-1.7b closes the v2 → v3 cross-version upgrade drill against a real previously-installed v2 VPS — the operator-side migration evidence the DEPLOY-1.7-preflight harness (D-066, local) and the DEPLOY-1.7a clean-VPS pilot smoke (D-067, real-VPS but new install) cannot produce. This subsection lands the operator procedure + a committed evidence-file template ahead of the drill itself; the drill is operator-dependent because it requires a real v2-installed VPS that the development environment cannot synthesize. Closure is by the populated evidence artifact at `docs/deploy1-drill/deploy1-cross-version-drill-<YYYYMMDD>-evidence.json` (UTC-dated; populated from the committed template `docs/deploy1-drill/deploy1-cross-version-drill-TEMPLATE.json`), exercising the **real v2 → v3 migration helper** (`migrate_v2_to_v3` at `scripts/installer/deploy.sh`) and the four signals re-probed across the version boundary: `loopback_health`, `public_tls_probe`, `webhook_registration`, and `offbox_backup_probe`.

**Operator pre-conditions:**

- A **real previously-installed v2 VPS** — Debian / Ubuntu LTS host whose installer was originally run from commit `e435e1a` (DEPLOY-1.5, `INSTALLER_CONFIG_VERSION=2`) and whose live `.installer-state.json` reads `installer_config_version: 2` at drill-start. The DEPLOY-1.7-preflight harness's `e435e1a` leg is **not** a substitute — the preflight is a sandboxed worktree without public DNS / Telegram / real S3, and the v2 → v3 migration evidence DEPLOY-1.7b closes is the real-operator one.
- The current branch (DEPLOY-1.6+ — i.e. a commit at `INSTALLER_CONFIG_VERSION=3`) checked out in the repo working tree on the VPS.
- `.env` populated with the **same env-key groups** as DEPLOY-1.7a (RUNBOOK §"Clean-VPS pilot smoke (DEPLOY-1.7a / D-067)"): `PUBLIC_HOSTNAME`, `ACME_EMAIL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, and all five `BACKUP_S3_*` knobs pointing at a reachable S3-compatible bucket the operator owns. DNS A/AAAA records for `$PUBLIC_HOSTNAME` already in place and resolving so Caddy's ACME-HTTP-01 challenge continues to succeed across the upgrade.
- A Telegram client (mobile or desktop) signed in as a user able to talk to the bot, for the `/start` round-trip re-probe.

**How to run:**

```sh
# 1. On the live v2 VPS, snapshot the installer state file verbatim into the
#    evidence artifact's pre_upgrade_state.installer_state_snapshot branch.
#    Expected: installer_config_version: 2, selected_defaults.backup_tool: null,
#    no offbox_backup_probe field. Redact credential-bearing values before
#    pasting into the artifact.
cat .installer-state.json

# 2. Move the working tree to the current DEPLOY-1.6+ ref (INSTALLER_CONFIG_VERSION=3).
git fetch && git checkout <current DEPLOY-1.6+ ref>

# 3. Run the unchanged installer. Capture the verbatim deploy.install.ok line
#    for the evidence artifact's observed_migration.deploy_install_ok_line_verbatim;
#    expected shape:
#    deploy.install.ok upgraded v2->v3 loopback_health=<value> public_tls_probe=<value> webhook_registration=<value> offbox_backup_probe=<value>
bash scripts/installer/deploy.sh

# 4. Snapshot the post-upgrade installer state file into the evidence artifact's
#    post_upgrade_state.installer_state_snapshot branch. Assert: installer_config_version
#    flipped 2 → 3; selected_defaults.backup_tool: "rclone" (materialized by migrate_v2_to_v3
#    per the D-063 / D-065 seam); a new offbox_backup_probe field is present.
cat .installer-state.json

# 5. Re-probe loopback_health — verify the loopback /health body shape.
curl -sS http://127.0.0.1:8000/health

# 6. Re-probe public_tls_probe — verify the public /health body shape across the upgrade.
curl -sS https://$PUBLIC_HOSTNAME/health

# 7. Re-probe webhook_registration — send /start from the Telegram client and capture
#    the canonical telegram.webhook log line + matching POST /telegram/webhook 200
#    access log + observed /start round-trip latency.
docker compose logs --tail=200 app | grep telegram.webhook

# 8. Note that getUpdates against the bot token continues to return HTTP 409 while
#    the webhook is active across the upgrade — EXPECTED, not a defect (same framing
#    as DEPLOY-1.7a).
curl -sS https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getUpdates

# 9. Re-probe offbox_backup_probe — wait for one full nightly cycle (or run a
#    one-off make backup-run) after the upgrade, then capture the uploader's
#    begin/ok log lines + the /archive/last_offbox.json cursor (status=ok).
docker compose logs --tail=50 pg_offbox_uploader | grep pg_backup.offbox
docker compose exec pg_backup cat /archive/last_offbox.json
```

The result is assembled by hand by copying the committed template `docs/deploy1-drill/deploy1-cross-version-drill-TEMPLATE.json` to a UTC-dated working filename `docs/deploy1-drill/deploy1-cross-version-drill-<YYYYMMDD>-evidence.json`, dropping the top-level `"_template": true` flag, replacing every `<TO_FILL_BY_OPERATOR>` placeholder with the verbatim captured observation, and running the redaction grep checklist below.

The evidence artifact carries **four top-level branches** — `pre_upgrade_state` (the verbatim v2 `.installer-state.json` fields), `observed_migration` (the verbatim `deploy.install.ok upgraded v2->v3 …` line, the `migrate_v2_to_v3` fired flag, the exit code), `post_upgrade_state` (the verbatim v3 `.installer-state.json` fields plus the four re-probed signals), and `summary` (the `closes_deploy_1_7b` / `closes_deploy_1_7` / `closes_deploy_1` booleans + verdict) — plus `metadata` and `out_of_scope_for_this_packet`. Shape parallels `docs/deploy1-drill/deploy1-pilot-smoke-20260527-evidence.json` (D-067) for redaction conventions and `docs/deploy1-drill/deploy1-upgrade-drill-20260522-evidence.json` (D-066) for the "verbatim observed outcomes" framing.

**Redaction rule (mandatory).** No credential text, bucket name, endpoint URL, prefix value, public hostname, or Telegram URL token may appear in the captured evidence file. Capture structural outcomes (status strings, log-line shapes, `"ok"` / `"error"` transitions, the `installer_config_version` 2 → 3 transition) **verbatim**; replace identifying values with `<REDACTED>` or a `_redacted: true` flag. Pre-commit, grep the artifact for the literal `$PUBLIC_HOSTNAME`, `$BACKUP_S3_BUCKET`, `$BACKUP_S3_ENDPOINT`, `$BACKUP_S3_PATH_PREFIX`, `$BACKUP_S3_ACCESS_KEY_ID`, `$BACKUP_S3_SECRET_ACCESS_KEY`, and `$TELEGRAM_BOT_TOKEN` values and confirm none appear literally. Same checklist as the DEPLOY-1.7a / D-067 subsection.

**DEPLOY-1.7b operator-procedure prep (D-068) is the docs landing — the operator drill against a real previously-installed v2 VPS is the sole remaining step to close DEPLOY-1.7b and DEPLOY-1.**

### DEPLOY-1 closure procedure (post-REAL-1) (D-076)

DEPLOY-1 closes by one operator-run procedure against the **already-deployed v3 VPS contour** — the same contour DEPLOY-1.7a (D-067) validated and REAL-1.1 (D-074) exercised end-to-end with real OpenAI. No new install, no new image, no new logging contract: D-076 lands the docs-first preparation (operator procedure + committed evidence-file template) for the operator drill, and DEPLOY-1.7b is **moved to DEPLOY-2 prep** by the same packet — the §"v2 → v3 cross-version upgrade drill (DEPLOY-1.7b / D-068)" subsection above and its committed template (`docs/deploy1-drill/deploy1-cross-version-drill-TEMPLATE.json`) are retained verbatim for DEPLOY-2 use, but the v2 → v3 cross-version drill is no longer a DEPLOY-1 closure dependency.

DEPLOY-1 closure lands in two halves: **D-076** (this subsection + the committed evidence-file template at `docs/deploy1-drill/deploy1-closure-post-real1-TEMPLATE.json` + the §4 / §6 roadmap update + cross-doc registrations) is the operator-procedure prep; the **operator drill** is the live capture that produces a populated dated `docs/deploy1-drill/deploy1-closure-post-real1-<YYYYMMDD>-evidence.json` and closes DEPLOY-1. D-076 does **not** close DEPLOY-1 on its own — closure depends on that populated artifact.

A-43 (logs-first observability scope) was pinned and closed in parallel by D-077: the closure procedure captures **only the existing log families already emitted by the deployed contour** — `pg_backup.*` (from `scripts/pg_backup/scheduler.sh` and `scripts/pg_offbox_uploader/uploader.sh`), Caddy access logs at the reverse-proxy contour (DEPLOY-1.3 / D-062), the app-side `telegram.webhook` line emitted by `src/memory_rag/adapters/telegram/webhook.py`, the `retrieval.hybrid` family emitted by `src/memory_rag/services/retrieval.py`, and the `answer.*` family emitted by `src/memory_rag/services/query_service.py` / `services/dispatcher.py`. **Captured verbatim, not invented**; no new logging contract is forced in `src/`.

#### Operator pre-conditions

- The deployed v3 VPS contour from DEPLOY-1.7a is up and reachable on its public hostname: `.installer-state.json` reads `installer_config_version: 3` and `last_outcome: "success"`; DNS A/AAAA records for `$PUBLIC_HOSTNAME` resolve from the public internet; Caddy's ACME-issued certificate continues to validate.
- `.env` populated per the §"Installer / upgrade script (DEPLOY-1.4 / D-063)" + §"Telegram webhook registration (DEPLOY-1.5 / D-064)" + §"Off-box backup sink (DEPLOY-1.6 / D-065)" subsections — `PUBLIC_HOSTNAME`, `ACME_EMAIL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, and all five `BACKUP_S3_*` knobs — plus the canonical REAL-1 env knobs (§"Real-answer end-to-end smoke (REAL-1 / D-073)" pre-conditions): `STORAGE_BACKEND=postgres`, `EMBEDDING_BACKEND=openai`, `EMBEDDING_MODEL=text-embedding-3-large`, `EMBEDDING_DIMENSION=3072`, `CHAT_BACKEND=openai`, `CHAT_MODEL=gpt-4.1`, and a real `OPENAI_API_KEY` in the operator's secret store.
- A Telegram client signed in as a user able to talk to the bot, for the `/note` → `/ask` round-trip.
- The OP-2 bounded-retry / backoff defaults from D-047 / D-049 are active (no tuning is part of D-076).

#### Numbered run procedure

1. Snapshot the live installer state file verbatim into the evidence artifact's `installer_state` branch. Expected: `installer_config_version: 3`, `selected_defaults.backup_tool: "rclone"`, `last_outcome: "success"`, all four probe fields (`loopback_health`, `public_tls_probe`, `offbox_backup_probe`, `webhook_registration.status`) showing `ok` / `registered`. Redact the webhook URL token before pasting.

   ```sh
   cat .installer-state.json
   ```

2. Capture the verbatim **`pg_backup.*` family** lines (A-43 pin) for `live_probes.pg_backup_family`. Wait for one full nightly cycle (or trigger one via `make backup-run`) so all three lines (`pg_backup.cycle.ok`, `pg_backup.offbox.begin`, `pg_backup.offbox.ok`) are present:

   ```sh
   docker compose logs --tail=50 pg_backup pg_offbox_uploader | grep pg_backup
   ```

3. Capture one verbatim **Caddy access-log line** (A-43 pin) for `live_probes.caddy_access`. The line is the `POST /telegram/webhook 200` access entry produced when the bot receives an update through the reverse-proxy contour:

   ```sh
   docker compose logs --tail=200 caddy | grep "POST /telegram/webhook"
   ```

4. Send `/note` from the Telegram client (date + one content line; reuse the REAL-1 procedure's `/note` shape from §"Real-answer end-to-end smoke (REAL-1 / D-073)"). Capture the verbatim 200 response body into `post_real1_round_trip.note.response_shape.body_text_verbatim`. Then capture the verbatim **`telegram.webhook` line** (A-43 pin) for `live_probes.telegram_webhook`:

   ```sh
   docker compose logs --tail=200 app | grep telegram.webhook
   ```

5. Send `/ask` from the Telegram client (a query that should match the saved note). Capture the verbatim 200 response body into `post_real1_round_trip.ask.response_shape.user_facing_reply_verbatim`. Then capture the verbatim **`retrieval.hybrid` line** and one verbatim **`answer.*` line** (A-43 pins) for `live_probes.retrieval_hybrid` and `live_probes.answer_path`:

   ```sh
   docker compose logs --tail=200 app | grep retrieval.hybrid
   docker compose logs --tail=200 app | grep -E 'answer\.'
   ```

   Capture the latest `answer_traces` row via the existing one-liner from §"Answer traces (D-034, D-035)" with `LIMIT 1` into `post_real1_round_trip.answer_traces_row_shape`. Confirm `fallback_mode='none'`, `model_name='gpt-4.1'`, `prompt_version='v1'`, non-empty `context_chunk_ids`, `latency_ms > 0`, non-empty `token_counts`. Capture the two `provider.attempt` lines (embedding + chat) into `post_real1_round_trip.provider_attempt_line_shape.*_line_verbatim`.

6. Hand-assemble the dated working artifact: `cp docs/deploy1-drill/deploy1-closure-post-real1-TEMPLATE.json docs/deploy1-drill/deploy1-closure-post-real1-<YYYYMMDD>-evidence.json`, drop the top-level `"_template": true` flag, replace every `<TO_FILL_BY_OPERATOR>` placeholder with the verbatim captured observation. Then run the redaction grep checklist below before committing.

#### Evidence-file shape

The artifact carries six top-level branches: `metadata` (capture date, environment, redaction notes), `installer_state` (verbatim `.installer-state.json` after the canonical install on the deployed VPS — `installer_config_version: 3`, `selected_defaults`, `last_outcome`, the four probe fields), `live_probes` (the five A-43-pinned existing log families captured verbatim — `pg_backup_family`, `caddy_access`, `telegram_webhook`, `retrieval_hybrid`, `answer_path`), `post_real1_round_trip` (one `/note` + one `/ask` round-trip envelope structurally identical to REAL-1.1's evidence so closure is directly comparable — request shape / response shape / `answer_traces` row shape / `provider.attempt` line shapes), `summary` (`closure_signals_observed`, `post_real1_round_trip_green`, `a43_logs_first_surface_emitting`, `closes_deploy_1`, `verdict`), and `out_of_scope_for_this_packet`. The committed `out_of_scope_for_this_packet` block is preserved verbatim.

#### Redaction rule

No credential text, bucket name, endpoint URL, prefix value, public hostname, Telegram URL token, or OpenAI key may appear in the captured evidence file. Capture structural outcomes (status strings, log-line shapes, `update_id` integers, `fallback_mode` values, numeric `latency_ms` magnitudes, `token_counts` integers) **verbatim**; replace identifying values with `<REDACTED>` or a `_redacted: true` flag. Pre-commit, grep the artifact for the literal `$PUBLIC_HOSTNAME`, `$BACKUP_S3_BUCKET`, `$BACKUP_S3_ENDPOINT`, `$BACKUP_S3_PATH_PREFIX`, `$BACKUP_S3_ACCESS_KEY_ID`, `$BACKUP_S3_SECRET_ACCESS_KEY`, `$TELEGRAM_BOT_TOKEN`, `$TELEGRAM_WEBHOOK_SECRET`, and `$OPENAI_API_KEY` values and confirm none appear literally:

```bash
grep -E "$PUBLIC_HOSTNAME|$BACKUP_S3_BUCKET|$BACKUP_S3_ENDPOINT|$BACKUP_S3_PATH_PREFIX|$BACKUP_S3_ACCESS_KEY_ID|$BACKUP_S3_SECRET_ACCESS_KEY|$TELEGRAM_BOT_TOKEN|$TELEGRAM_WEBHOOK_SECRET|$OPENAI_API_KEY" \
  docs/deploy1-drill/deploy1-closure-post-real1-<YYYYMMDD>-evidence.json && echo "REDACTION FAILED" || echo "redaction grep clean"
```

#### Closure signal

DEPLOY-1 closes by a populated dated `docs/deploy1-drill/deploy1-closure-post-real1-<YYYYMMDD>-evidence.json` with `summary.closure_signals_observed`, `summary.post_real1_round_trip_green`, `summary.a43_logs_first_surface_emitting`, and `summary.closes_deploy_1` all `true`. The closure flag is anchored on the still-green REAL-1.1 evidence at `docs/real-answer-drill/real-answer-smoke-20260528-evidence.json` (D-074), the still-green DEPLOY-1.7a evidence at `docs/deploy1-drill/deploy1-pilot-smoke-20260527-evidence.json` (D-067), and the new closure-procedure evidence together. D-076 does not close DEPLOY-1 on its own — it lands the procedure + template + cross-doc registration so that the operator run is a single bounded action.

#### `make check` non-impact

This procedure makes no contribution to `make check`. No new gated test is added; the existing `tests/test_chat_client_openai.py` and `tests/test_embedding_client_openai.py` smokes (env-gated by `MEMORY_RAG_OPENAI_TEST_KEY`) are unchanged. The captured artifact is documentation evidence, not a CI input.

## Useful reads when stuck
- Workflow & recovery: this file.
- Architecture, adapter axes, deployment shapes: `docs/ARCHITECTURE.md`.
- What must hold at runtime: `docs/RUNTIME-INVARIANTS.md`.
- Data shape rules: `docs/INVARIANTS.md`.
- Open questions: `docs/assumptions.md`.
- Why things are the way they are: `docs/decision-log.md`.
