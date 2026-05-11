# telegram-dairy

Diary RAG Service for **TheyGrow** — a low-friction memory system for parents who write family and child observations in Telegram and later ask natural-language questions over them.

> **Status:** Milestone 1 complete (Phase 1 + Phase 2 + Phase 3.1/3.2). Slice 3.3 baseline hybrid retrieval is now in (D-025). Telegram webhook adapter, channel-neutral `DiaryService` / `QueryService`, durable PostgreSQL backend behind `DiaryRepository` (D-022), idempotent webhook + ingest keyed on `(external_chat_id, external_message_id, edit_seq)` (D-023), sync per-chunk embedding indexing on pgvector with `text-embedding-3-large` @ 3072 dim (D-024), and baseline hybrid retrieval with `SearchRepository` (dense exact family-scoped scan + Postgres FTS `tsvector('simple')`) fused by service-layer RRF (D-025). The grounded-answer pipeline, provider hardening, and search-quality optimizations (BM25, reranker, Qdrant, halfvec/HNSW) land in later milestones.

## What this is

The product is a **standalone Diary Memory Service**. Telegram is the first client channel. The same service is later integrated into TheyGrow as a reusable internal memory subsystem.

Core rules (from `AGENTS.md` and the canonical docs):

- Telegram is a channel, not the system core.
- PostgreSQL is the durable source of truth.
- Raw source messages are persisted before enrichment.
- Each diary event line becomes its own chunk.
- Hybrid retrieval is required.
- Every answer is grounded in retrieved evidence.
- Optional AI enrichments are feature-flagged.
- Shared diary mode preserves authorship.

## What's in this repo

### Canonical (treat as source of truth)
- `docs/product/PRD.md` — product intent, users, scope, success criteria.
- `docs/product/BuildPlan.md` — phased build plan (Phase 0 → 9).
- `docs/product/TechSpec.md` — entities, contracts, retrieval architecture.
- `docs/decision-log.md` — accepted decisions (D-001 …).

### Operating contract
- `AGENTS.md` — operating rules for any AI agent in this repo.
- `CLAUDE.md` — Claude Code read order and working mode.

### Supporting
- `docs/ARCHITECTURE.md` — one-page system shape and layer boundaries.
- `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` — non-negotiables.
- `docs/RUNBOOK.md` — canonical workflow inside this repo.
- `docs/CHECKLIST.md` — pre-implementation and pre-merge gates.
- `docs/execution-map.md` — phase → files map.
- `docs/assumptions.md` / `docs/assumption-audit.md` — open questions and their risk/owner.
- `docs/todo.md` — ordered backlog of the next slices.

### Scaffold
- `pyproject.toml`, `.python-version`, `uv.lock` — Python 3.11 + uv project (D-016, D-017).
- `Makefile` — `format`, `lint`, `typecheck`, `test`, `check`, `run` (D-018).
- `src/diary_rag/` — package skeleton (`config`, `logging`, `app`, `__main__`) plus placeholder packages for `adapters/telegram`, `core/routing`, `services`, `storage/mock`.
- `tests/` — Slice 1.1 smoke tests.
- `.env.example` — config keys we expect to need.
- `.gitignore` — local artifacts and secrets.

## Current status

- Canonical docs (PRD, BuildPlan, TechSpec, decision log) populated.
- Operating contract (AGENTS, CLAUDE) populated.
- Supporting docs populated; open items surfaced in `docs/assumptions.md`.
- Phase-1 platform decisions locked: **Python 3.11** (D-016), **`uv`** (D-017), **Ruff + Mypy + Pytest** (D-018), **Telegram webhook transport** (D-019).
- **Slice 1.1 done:** toolchain wired, package skeleton in place, `make check` green, FastAPI `/health` smokeable via `make run`.
- **Slice 1.2 done:** `POST /telegram/webhook` accepts a Telegram update, fails closed without the secret header (A-26), parses `/start` `/help` `/entry` `/ask`, and returns a `sendMessage`-shaped payload.
- **Mock diary/query contour done:** `core/diary` dataclasses + ISO date parser, `MockDiaryStore`, `DiaryService` and `QueryService`, `Dispatcher` wires `ENTRY` / `ASK` to those services. `/entry` records the raw `SourceMessage` before parsing (I-3, R-1); `/ask` returns explicit `NO_EVIDENCE` when nothing matches (I-9, R-5/R-6). New open assumptions: A-28 (ISO-only mock dates), A-29 (substring-match retrieval), A-30 (process-local mock state).
- **Phase 3.1+3.2 done (D-024):** `EmbeddingClient` seam, `OpenAIEmbeddingClient` (`text-embedding-3-large` @ 3072 dim, passes `dimensions=3072` explicitly), `MockEmbeddingClient` (honest `model_name="mock"`). Sync indexing on ingest writes one `embedding_records` row per chunk; `event_chunks.embedding_status ∈ {pending, ready, failed}`. Postgres backend uses `pgvector(3072)` (compose image swapped to `pgvector/pgvector:pg16`). Boot gate refuses to start with the wrong dimension, the wrong OpenAI model, or pgvector missing. Replay (R-2) does not re-embed; failed embeddings stay failed (A-35).
- **Slice 3.3 done (D-025) — baseline hybrid retrieval:** new `SearchRepository` seam with `dense_candidates` (exact family-scoped scan over `vector(3072)`, `embedding <=> %s::vector`, `embedding_status='ready'` only) and `sparse_candidates` (generated stored `chunk_text_tsv tsvector` from `to_tsvector('simple', chunk_text)` + GIN index, ranked by `ts_rank_cd`). Service-layer Reciprocal Rank Fusion (`k=60`) merges the two legs. Postgres is the only canonical retrieval backend; SQLite hybrid raises `NotImplementedError` and the dispatcher returns `NO_EVIDENCE`. Closes A-6 / A-29; replaces A-36 with A-36b (halfvec/HNSW deferred) and opens A-37 (sparse dictionary `simple`). **BM25 / reranker / Qdrant / halfvec are explicitly deferred to the next quality-decision packet** — this slice ships the smallest canonical baseline so retrieval becomes evaluable.
- Next gate: the search-quality fork — pick one of BM25-grade sparse, a reranker, or external vector/search system to measure against the D-025 baseline (`docs/todo.md`).

## How to start

1. Read `AGENTS.md`, then `CLAUDE.md`.
2. Read canonical docs in the order listed in `CLAUDE.md`.
3. `uv sync --all-extras && make check` (see `QUICKSTART.md`).
4. Pick the top item from `docs/todo.md` and follow `docs/RUNBOOK.md`.
