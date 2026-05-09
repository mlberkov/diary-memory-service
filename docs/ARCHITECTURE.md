# Architecture

Derived from `docs/product/TechSpec.md`. Do not extend with new entities or flows here — promote them to TechSpec first.

## One-page view

```
Telegram bot   ──┐                                              ┌── TheyGrow client (later)
                 ▼                                              ▼
            Channel adapter (Telegram)              Channel adapter (TheyGrow)
                 │                                              │
                 └──────────────► Diary Memory Service ◄────────┘
                                          │
       ┌──────────────┬───────────────────┼───────────────────┬────────────────┐
       ▼              ▼                   ▼                   ▼                ▼
   Routing       Ingestion           Retrieval           Answering       Observability
   /entry        persist raw         hybrid search       grounded gen    routing trace
   /ask          parse date          metadata filter     fallbacks       parse status
   heuristic     split events                            evidence ref    retrieval trace
                 chunk + embed                                           answer trace
                                          │
                                          ▼
                                     PostgreSQL
                              (system of record:
                               source, entry, chunk,
                               embedding refs, traces)
```

## Layering

- **Channel adapters** — Telegram today, TheyGrow tomorrow. Translate transport-specific input into core service calls. No domain logic.
- **Diary Memory Service** — the product. Owns ingestion, retrieval, answering, traces. Has no Telegram knowledge.
- **Core domain** — the entities listed in TechSpec §5. Pure data + pure logic, no IO.
- **Infrastructure** — PostgreSQL repositories, embedding client, chat client, hybrid search backend. Each behind an explicit interface (e.g. `SearchRepository`, `EmbeddingClient`, `ChatClient`).

## Boundary rules

- Telegram-specific types do not appear outside the Telegram adapter (I-1).
- Core domain does not import provider SDKs directly (I-11).
- Provider access goes through one wrapper per provider; every call is logged with model, input hash, latency, outcome class (R-7).
- Repository interfaces hide PostgreSQL specifics; no SQL outside the repository layer.

## Data flow — ingestion (`/entry`)

1. Channel adapter receives an inbound update.
2. Adapter calls `IngestionService.ingest_source_message(...)`.
3. Service persists `SourceMessage` (raw text, route hint, metadata) — **commit before any enrichment** (I-3, R-1).
4. Service parses date and splits event lines (`parse_version` recorded).
5. Service creates `DiaryEntry` and one `EventChunk` per event line (I-5).
6. Service requests embeddings (sync or async — see assumption A-7).
7. Service indexes chunks into the hybrid search backend.
8. Service returns confirmation + parse trace; adapter formats the user-facing reply.

If any step after raw persistence fails, raw data is intact and the failed step is replayable (I-12).

## Data flow — query (`/ask`)

1. Channel adapter receives an inbound update.
2. Adapter calls `QueryService.answer(query, scope)`.
3. Service persists `Query`.
4. Service runs hybrid retrieval; applies family/child/visibility filters (I-7, I-8).
5. Service assembles top-k context with provenance.
6. Service calls the grounded answer pipeline; records `AnswerTrace` with `context_chunk_ids` and `fallback_mode` (R-5).
7. Adapter renders the answer + evidence references for the user.

If retrieval is empty, weak, or ambiguous, the service emits an explicit fallback (I-9, R-6). No silent degradation.

## Why this shape

- Keeps the write path safe from LLM/availability problems.
- Makes the integration into TheyGrow an adapter swap, not a rewrite.
- Allows the indexing/retrieval backend to evolve without touching domain code.
- Allows replay of any past `SourceMessage` under a new parser or embedding version.

## Out of scope here

- Concrete table DDL — lives with the migration in Phase 2.
- Concrete prompt templates — live with the answer pipeline in Phase 4.
- Provider-specific configuration — lives in `.env` and the provider adapter.
