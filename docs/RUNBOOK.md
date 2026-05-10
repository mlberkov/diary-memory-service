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
There is no migration tool yet (A-34). `schema.sql` is bootstrapped via `CREATE TABLE / CREATE INDEX IF NOT EXISTS`, which does **not** apply changes to columns or constraints on tables that already exist in a stale volume. When pulling a packet that adds or alters columns (e.g. D-023's `external_message_id`, `edit_seq`, and the `UNIQUE` idempotency constraint; or D-024's pgvector image swap + `embedding_records` table + `event_chunks.embedding_status` column), reset the local Postgres volume:

```
docker compose down -v
docker compose up -d postgres
```

This drops `diary_pg_data` along with any locally-ingested rows. Production schema evolution must be solved before any non-local deployment.

### Webhook idempotency (R-2 / D-023)
Repeated delivery of the same Telegram message-state — same `(external_chat_id, external_message_id, edit_seq)` — does not create duplicate rows. The webhook returns the same functional 200 reply and logs `effective_path=replay` instead of `fresh`. Operationally, `effective_path=replay` is normal; investigate only if the *first* call for a given key never appears with `effective_path=fresh`.

### Telegram in local development
Webhook only (D-019). Expose the local process via a tunnel (e.g. `ngrok`, `cloudflared`) and register the tunnel URL with the bot. There is no polling fallback.

## Useful reads when stuck
- Workflow & recovery: this file.
- What must hold at runtime: `docs/RUNTIME-INVARIANTS.md`.
- Data shape rules: `docs/INVARIANTS.md`.
- Open questions: `docs/assumptions.md`.
- Why things are the way they are: `docs/decision-log.md`.
