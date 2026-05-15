# Quickstart

> **Milestone 1 complete.** Telegram webhook + ingest, durable PostgreSQL backend behind `DomainRepository` (D-022),
> idempotent ingest on `(external_chat_id, external_message_id, edit_seq)` (D-023), sync chunk embedding
> indexing on pgvector with `text-embedding-3-large` @ 3072 dim (D-024), and **baseline hybrid retrieval**
> (`SearchRepository` with exact dense family-scoped scan + Postgres FTS `tsvector('simple')` + service-layer
> RRF, D-025) are all wired. BM25, rerankers, and external vector/search systems (Qdrant et al.) are
> explicitly deferred to the next quality-decision packet. See `docs/todo.md` for what's next.

## Read first

```bash
git clone <this repo>
cd telegram-dairy
$EDITOR AGENTS.md
```

Read order: `AGENTS.md` → `CLAUDE.md` → `docs/product/PRD.md` → `docs/product/BuildPlan.md` → `docs/product/TechSpec.md` → `docs/decision-log.md`.

Then look at `docs/RUNBOOK.md` for how work is done here, and `docs/todo.md` for what's next. For the canonical `community` / `subject` vocabulary, see `docs/GLOSSARY.md` (D-041).

## Local bootstrap

Tooling is locked: Python 3.11 (D-016), `uv` (D-017), Ruff + Mypy + Pytest (D-018).

Prerequisites: `uv` installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`). `uv` will pick up or install the Python 3.11 interpreter pinned in `.python-version`.

```bash
uv sync --all-extras       # install runtime + dev deps; creates .venv
cp .env.example .env       # optional at Slice 1.1; fill in as later slices need it
make check                 # ruff (lint + format check) + mypy + pytest
make run                   # boot the FastAPI shell on http://127.0.0.1:8000
curl http://127.0.0.1:8000/health
# {"status":"ok","version":"0.0.0","env":"local"}
```

Available `make` targets: `init`, `sync`, `format`, `lint`, `typecheck`, `test`, `check`, `run`, `tree`, `clean`.

### Required environment

See `.env.example` for the full list. Currently used:

- `TELEGRAM_BOT_TOKEN` — bot identity (Phase 1.2+)
- `TELEGRAM_WEBHOOK_SECRET` — required for `/telegram/webhook` to accept any call (A-26)
- `OPENAI_API_KEY` — required when `EMBEDDING_BACKEND=openai` (D-024)
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- `EMBEDDING_BACKEND` — `mock` (default) or `openai` (D-024)
- `EMBEDDING_MODEL` — `text-embedding-3-large` (D-024)
- `EMBEDDING_DIMENSION` — `3072` (D-024); boot gate refuses any other value
- `RETRIEVAL_TOP_K` — final evidence count returned to the answer pipeline (D-025; default `5`)
- `RETRIEVAL_CANDIDATE_K` — per-leg candidate pool size for dense + sparse before RRF (D-025; default `20`)
- `CHAT_MODEL` (value not yet chosen — see `docs/assumptions.md` A-9)

### Required services

- **PostgreSQL with pgvector** — `docker-compose.yml` runs `pgvector/pgvector:pg16` (D-024). The dense `embedding_records.embedding` column is `vector(3072)`; the sparse leg uses a generated `event_chunks.chunk_text_tsv` column with a GIN index (D-025).
- **Outbound network access to OpenAI** — required only when `EMBEDDING_BACKEND=openai`. The mock backend has no external dependencies and is the default everywhere except production.

### Telegram transport

The bot uses a **webhook receiver in all environments** (D-019). Local development requires a public URL pointing at the local process — use a tunnel such as `ngrok` or `cloudflared`. Long-polling is not supported.

#### Local smoke against the webhook

```bash
export TELEGRAM_WEBHOOK_SECRET=dev-secret
make run    # FastAPI on http://127.0.0.1:8000

# 401 — missing or wrong header
curl -i -X POST http://127.0.0.1:8000/telegram/webhook \
  -H "Content-Type: application/json" \
  -d '{"update_id":1,"message":{"message_id":1,"date":1715300000,"chat":{"id":42},"from":{"id":7},"text":"/start"}}'

# 200 — sendMessage payload returned in the response body
curl -X POST http://127.0.0.1:8000/telegram/webhook \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: dev-secret" \
  -d '{"update_id":1,"message":{"message_id":1,"date":1715300000,"chat":{"id":42},"from":{"id":7},"text":"/start"}}'
# → {"method":"sendMessage","chat_id":42,"text":"Welcome — diary mode. ..."}
```

#### Mock diary smoke (`/note` then `/ask`)

The mock store lives in process memory: state survives across requests within one `make run` and resets on restart.

```bash
# 1. Ingest a multi-line dated entry
curl -s -X POST http://127.0.0.1:8000/telegram/webhook \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: dev-secret" \
  -d '{"update_id":1,"message":{"message_id":1,"date":1715300000,"chat":{"id":42},"from":{"id":7},"text":"/note 2026-05-09\nHad a calm morning\nTried a new book"}}'
# → {"method":"sendMessage","chat_id":42,"text":"Saved 2 events for 2026-05-09."}

# 2. Ask — baseline hybrid retrieval (dense + sparse + RRF) returns the matching line with its date
curl -s -X POST http://127.0.0.1:8000/telegram/webhook \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: dev-secret" \
  -d '{"update_id":2,"message":{"message_id":2,"date":1715300100,"chat":{"id":42},"from":{"id":7},"text":"/ask book"}}'
# → text: "Found 1 memory:\n- [2026-05-09] Tried a new book\n(hybrid retrieval — dense+sparse RRF)"

# 3. Ask with no match → explicit no-evidence fallback (no fabricated answer)
curl -s -X POST http://127.0.0.1:8000/telegram/webhook \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: dev-secret" \
  -d '{"update_id":3,"message":{"message_id":3,"date":1715300200,"chat":{"id":42},"from":{"id":7},"text":"/ask snowstorm"}}'
# → text: "No memories matched 'snowstorm'."

# 4. Non-ISO first line → INVALID_INPUT reply; raw SourceMessage is still recorded
curl -s -X POST http://127.0.0.1:8000/telegram/webhook \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: dev-secret" \
  -d '{"update_id":4,"message":{"message_id":4,"date":1715300300,"chat":{"id":42},"from":{"id":7},"text":"/note not-a-date\nfoo"}}'
# → text: "Mock /note needs an ISO date (YYYY-MM-DD) on the first line. Got: 'not-a-date'."
```

#### Heuristic plain-text routing (`/note` / `/ask` optional)

Plain text without a slash command is classified by `core.routing.classifier`: a dated body becomes an entry, a question becomes an ask, anything else gets a clarification reply. Heuristic-routed replies carry an explicit marker so the user can see what happened (D-006, R-6, R-11).

```bash
# 5. Dated plain text — heuristic ENTRY
curl -s -X POST http://127.0.0.1:8000/telegram/webhook \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: dev-secret" \
  -d '{"update_id":5,"message":{"message_id":5,"date":1715300400,"chat":{"id":42},"from":{"id":7},"text":"2026-05-10\nLearned a new recipe\nWalked 5km"}}'
# → text: "Saved 2 events for 2026-05-10.\n(routed as note — send /note next time to be explicit)"

# 6. Plain question — heuristic ASK (terminal "?" stripped before hybrid retrieval)
curl -s -X POST http://127.0.0.1:8000/telegram/webhook \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: dev-secret" \
  -d '{"update_id":6,"message":{"message_id":6,"date":1715300500,"chat":{"id":42},"from":{"id":7},"text":"recipe?"}}'
# → text: "Found 1 memory:\n- [2026-05-10] Learned a new recipe\n(hybrid retrieval — dense+sparse RRF)\n(routed as question — send /ask next time to be explicit)"

# 7. Ambiguous text — CLARIFY (no persistence, no guessed route)
curl -s -X POST http://127.0.0.1:8000/telegram/webhook \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: dev-secret" \
  -d '{"update_id":7,"message":{"message_id":7,"date":1715300600,"chat":{"id":42},"from":{"id":7},"text":"recipe yesterday"}}'
# → text: "I couldn't tell if that's a diary entry or a question. Send /note <YYYY-MM-DD> on the first line then your events to record it, or /ask <your question> to query."
```

#### Durable local store (Postgres)

`STORAGE_BACKEND=postgres` is the canonical durable backend (D-007 / D-022). It writes through `PostgresDomainStore` to the local Postgres provided by `docker-compose.yml`. Schema is bootstrapped on first boot from `src/diary_rag/storage/postgres/schema.sql` via `CREATE TABLE / CREATE INDEX IF NOT EXISTS`. Default backend is still `memory`; SQLite (below) remains an opt-in non-default backend.

```bash
# 0. Bring up Postgres (compose defaults work without a custom .env)
docker compose up -d postgres
docker compose ps             # wait until "healthy"

# 1. Point the app at it
export TELEGRAM_WEBHOOK_SECRET=dev-secret
export STORAGE_BACKEND=postgres
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=theygrow_diary_rag
export POSTGRES_USER=postgres
export POSTGRES_PASSWORD=postgres

make run                      # uvicorn boots; first call bootstraps schema

# 2. Ingest a multi-line dated entry
curl -s -X POST http://127.0.0.1:8000/telegram/webhook \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: dev-secret" \
  -d '{"update_id":1,"message":{"message_id":1,"date":1715300000,"chat":{"id":42},"from":{"id":7},"text":"/note 2026-05-09\nWalked the dog\nTried a new book"}}'
# → text: "Saved 2 events for 2026-05-09."

# 3. Verify rows landed in Postgres
docker compose exec -T postgres psql -U postgres -d theygrow_diary_rag -c \
  "SELECT
     (SELECT count(*) FROM source_messages)   AS sources,
     (SELECT count(*) FROM diary_entries)     AS entries,
     (SELECT count(*) FROM event_chunks)      AS chunks,
     (SELECT count(*) FROM embedding_records) AS embeddings;"
# → sources=1 entries=1 chunks=2 embeddings=2

# 3a. Verify embedding contour (D-024): status flipped to 'ready',
#     model_name and vector dimension are correct.
docker compose exec -T postgres psql -U postgres -d theygrow_diary_rag -c \
  "SELECT ec.chunk_id, ec.event_index, ec.embedding_status,
          er.model_name, er.dimension, vector_dims(er.embedding) AS vec_dim
     FROM event_chunks ec
     LEFT JOIN embedding_records er USING (chunk_id)
    ORDER BY ec.event_index;"
# → embedding_status=ready, model_name=mock, dimension=3072, vec_dim=3072
#   (model_name='text-embedding-3-large' when EMBEDDING_BACKEND=openai)

# 4. Stop uvicorn (Ctrl+C); rerun `make run` with the same env
#    (the docker-compose volume keeps the DB across app restarts)

# 5. Ask after restart — evidence survives, baseline hybrid retrieval ranks via RRF
curl -s -X POST http://127.0.0.1:8000/telegram/webhook \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: dev-secret" \
  -d '{"update_id":2,"message":{"message_id":2,"date":1715300100,"chat":{"id":42},"from":{"id":7},"text":"/ask book"}}'
# → text: "Found 1 memory:\n- [2026-05-09] Tried a new book\n(hybrid retrieval — dense+sparse RRF)"

# Cleanup
docker compose down           # stop, keep volume
docker compose down -v        # also drop diary_pg_data
```

The reply trailer now reads "hybrid retrieval — dense+sparse RRF" (D-025); the application server logs `retrieval.hybrid family_id=… model=… dense_n=… sparse_n=… merged_n=…` for every `/ask`.

#### Durable local store (SQLite — opt-in, ingest only)

`STORAGE_BACKEND=sqlite` writes through `SqliteDomainStore` to a single file at `SQLITE_PATH` (default `./data/diary.db`). Schema is bootstrapped on first boot via `CREATE TABLE IF NOT EXISTS`. Useful for offline dev / tests; the canonical durable path is Postgres (D-022). **Retrieval is not supported on SQLite (D-025):** `/ask` against a SQLite-backed app raises `NotImplementedError` internally and the dispatcher returns `NO_EVIDENCE`. Use Postgres if you want `/ask` to actually retrieve evidence.

```bash
export TELEGRAM_WEBHOOK_SECRET=dev-secret
export STORAGE_BACKEND=sqlite
export SQLITE_PATH=./data/diary.db   # default; override anywhere writable

mkdir -p data
make run    # boots uvicorn, creates ./data/diary.db on first call

# 1. Ingest — same payload shape as the mock smoke above
curl -s -X POST http://127.0.0.1:8000/telegram/webhook \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: dev-secret" \
  -d '{"update_id":1,"message":{"message_id":1,"date":1715300000,"chat":{"id":42},"from":{"id":7},"text":"/note 2026-05-09\nWalked the dog\nTried a new book"}}'
# → text: "Saved 2 events for 2026-05-09."

# 2. Verify rows landed in the SQLite file
python -c "import sqlite3; c=sqlite3.connect('./data/diary.db'); \
  print('sources:', c.execute('select count(*) from source_messages').fetchone()[0]); \
  print('entries:', c.execute('select count(*) from diary_entries').fetchone()[0]); \
  print('chunks:',  c.execute('select count(*) from event_chunks').fetchone()[0])"
# → sources: 1 / entries: 1 / chunks: 2

# 3. Stop uvicorn (Ctrl+C), then `make run` again with the same env
#    (a fresh process re-opens the same ./data/diary.db).

# 4. Ask after restart — retrieval is unavailable on SQLite (D-025); reply is NO_EVIDENCE
curl -s -X POST http://127.0.0.1:8000/telegram/webhook \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: dev-secret" \
  -d '{"update_id":2,"message":{"message_id":2,"date":1715300100,"chat":{"id":42},"from":{"id":7},"text":"/ask book"}}'
# → text: "No memories matched 'book'."
# (server log includes "retrieval.unavailable reason=... family_id=...")

# Cleanup
rm -f ./data/diary.db ./data/diary.db-shm ./data/diary.db-wal
```

#### Registering the webhook with Telegram (when using a real bot)

```bash
# 1. Run a tunnel pointing at port 8000
ngrok http 8000   # copy the https URL it prints

# 2. Tell Telegram where to post updates and which secret to send back
curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  --data-urlencode "url=https://YOUR-TUNNEL.ngrok.app/telegram/webhook" \
  --data-urlencode "secret_token=${TELEGRAM_WEBHOOK_SECRET}"
```

## When something is broken

- Workflow & recovery: `docs/RUNBOOK.md`
- What must hold at runtime: `docs/RUNTIME-INVARIANTS.md`
- Data shape rules: `docs/INVARIANTS.md`
- Canonical vocabulary: `docs/GLOSSARY.md`
- Open decisions: `docs/assumptions.md`
- Why things are the way they are: `docs/decision-log.md`
