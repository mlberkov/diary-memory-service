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
