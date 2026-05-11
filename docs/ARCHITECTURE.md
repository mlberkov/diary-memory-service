# Architecture

Derived from `docs/product/TechSpec.md`. Do not extend with new entities or flows here — promote them to TechSpec first.

## Portability principle

This repository implements a **portable memory/journal core**. The functional core — raw capture, parsing, line-level chunking, embedding, hybrid retrieval, grounded answering, provenance — is the same subsystem regardless of which system embeds it. What varies between hosts is the surface around the core. Telegram is one event-source adapter; TheyGrow is one future host; self-hosted OSS, managed cloud, and embedded-in-TheyGrow are equally first-class deployment shapes. The current parents/family/child framing is the first use case of the core, not its definition. Journal/topic semantics in the core stay generic. See D-026.

### Adapter axes

Hosts and integrations vary along five axes. Each axis has a single explicit seam:

1. **Event source** — Telegram webhook today; HTTP API, embedded SDK call, CLI, web form later. Adapter translates transport-specific input into a `SourceMessage` plus a routing decision.
2. **Control surface** — how users invoke ingest vs. ask. `/entry` and `/ask` in Telegram; UI buttons, endpoints, or app screens elsewhere. Routing logic is core-shaped; its binding to a transport is adapter-side.
3. **Storage / infrastructure** — `DiaryRepository` and `SearchRepository` Protocols. Mock, SQLite (dev), local Postgres + pgvector, managed Postgres, or a host's existing database when embedded.
4. **Embedding / LLM providers** — `EmbeddingClient`, `ChatClient`. OpenAI today, but also self-hosted models, on-prem inference, host-provided gateways, mocks for tests.
5. **Tenant / auth mapping** — maps the host's identity model (Telegram chat → family scope; TheyGrow account → workspace; OSS deployment → single-tenant default) onto the core's scope. The mapping function is adapter; the scoped query is core.

### What belongs to the core

- Domain model: `SourceMessage`, `DiaryEntry`, `EventChunk`, `EmbeddingRecord`, `Query`, `AnswerTrace`, `RetrievalHit` (entity *shape* is core; entity *names* may be reframed in a later renaming packet to read topic-neutrally).
- Ingestion pipeline: raw-first persistence, versioned parsing, line-level chunking, embedding generation, indexing.
- Retrieval: hybrid search seam, scope filtering, RRF fusion, retrieval traces.
- Answering: context assembly, grounded answer contract, fallback modes, evidence references.
- Invariants: raw before enrichment, replayability, requested-vs-effective provenance, no silent degradation.
- Service-facing contracts: `IngestionService.ingest_source_message`, `QueryService.answer(query, scope)`.
- Tenancy abstraction: scope is opaque to the core (today `family_id`); the core does not encode that a tenant is a "family" or that a subject is a "child".

### What belongs to adapters / integration layers

- Transport types and host identifiers (`telegram.Update`, webhook payloads, HTTP request shapes).
- Storage engine specifics (SQL, pgvector operators, SQLite calls).
- Provider SDKs (`openai`, host-provided model gateways).
- Host identity mapping (Telegram chat → tenant; TheyGrow workspace → tenant; OSS → single default tenant).
- Transport-bound presentation (Telegram message formatting, marker trailers, UI rendering).

### What must not leak into the core

- Transport types outside the channel adapter (already I-1).
- Provider SDK imports outside provider adapters (already I-11).
- Raw SQL or vendor-specific operators outside the storage layer.
- Use-case vocabulary in newly added code (`family`, `child`, `parent`, "diary" as a type name) where a generic name fits. Existing names persist; new code adopts the neutral form.
- Assumptions that the runtime is HTTP-shaped, Telegram-shaped, single-tenant, internet-connected, or English-only.
- Authentication model assumptions; the core receives an already-resolved scope.

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

- **Channel adapters** — Telegram today, TheyGrow tomorrow, plus future HTTP/SDK/CLI surfaces. Translate transport-specific input into core service calls. No domain logic.
- **Diary Memory Service** — the product core. Owns ingestion, retrieval, answering, traces. Has no transport or host knowledge.
- **Core domain** — the entities listed in TechSpec §5. Pure data + pure logic, no IO. Topic-neutral in shape; use-case-specific scope (family, child) is carried as opaque identifiers, not encoded in the model.
- **Infrastructure** — PostgreSQL repositories, embedding client, chat client, hybrid search backend. Each behind an explicit interface (e.g. `SearchRepository`, `EmbeddingClient`, `ChatClient`).

## Boundary rules

- Telegram-specific types do not appear outside the Telegram adapter (I-1).
- Core domain does not import provider SDKs directly (I-11).
- Provider access goes through one wrapper per provider; every call is logged with model, input hash, latency, outcome class (R-7).
- Repository interfaces hide PostgreSQL specifics; no SQL outside the repository layer.
- Use-case vocabulary (`family`, `child`, `parent`, "diary" as a type name) does not appear in newly added core code where a generic name fits (D-026). Existing names persist until an explicit renaming packet.

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
- Makes the integration into TheyGrow an adapter swap, not a rewrite — and the same shape extends to OSS self-host, managed cloud, and other embedded hosts.
- Allows the indexing/retrieval backend to evolve without touching domain code.
- Allows replay of any past `SourceMessage` under a new parser or embedding version.

## Out of scope here

- Concrete table DDL — lives with the migration in Phase 2.
- Concrete prompt templates — live with the answer pipeline in Phase 4.
- Provider-specific configuration — lives in `.env` and the provider adapter.
