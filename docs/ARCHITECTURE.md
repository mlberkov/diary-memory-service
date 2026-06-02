# Architecture

Derived from `docs/product/TechSpec.md`. Do not extend with new entities or flows here — promote them to TechSpec first.

## Portability principle

This repository implements a **portable memory/journal core** — a generic shared-memory / note-grounded answer service. The functional core — raw capture, parsing, line-level chunking, embedding, hybrid retrieval, grounded answering, provenance — is the same subsystem regardless of which system embeds it. What varies between hosts is the surface around the core. Telegram is one event-source adapter; TheyGrow is one future host; self-hosted OSS, managed cloud, and embedded-in-TheyGrow are equally first-class deployment shapes. The current parents/family/child framing is the first use case of the core, not its definition. Journal/topic semantics in the core stay generic. The canonical core vocabulary is `community` (the outer scope owning a note corpus) and `subject` (a sub-entity a note is about); the first use case maps `family` → community and `child` → subject. See D-026, D-041, and `docs/GLOSSARY.md`.

### Adapter axes

Hosts and integrations vary along five axes. Each axis has a single explicit seam:

1. **Event source** — Telegram webhook today; HTTP API, embedded SDK call, CLI, web form later. Adapter translates transport-specific input into a `SourceMessage` plus a routing decision.
2. **Control surface** — how users invoke ingest vs. ask. `/note` and `/ask` in Telegram; UI buttons, endpoints, or app screens elsewhere. Routing logic is core-shaped; its binding to a transport is adapter-side.
3. **Storage / infrastructure** — `DomainRepository` and `SearchRepository` Protocols. Mock, SQLite (dev), local Postgres + pgvector, managed Postgres, or a host's existing database when embedded.
4. **Embedding / LLM providers** — `EmbeddingClient`, `ChatClient`. OpenAI today, but also self-hosted models, on-prem inference, host-provided gateways, mocks for tests.
5. **Tenant / auth mapping** — maps the host's identity model (Telegram chat → family scope; TheyGrow account → workspace; OSS deployment → single-tenant default) onto the core's scope. The mapping function is adapter; the scoped query is core. Resolving an author's **display name** from host-supplied identity fields is likewise adapter-side; the core carries only the opaque `author_user_id` (D-081, A-44). Capturing and persisting those host identity fields as an adapter/storage-owned snapshot is likewise adapter-side (D-082); that snapshot lands in a separate adapter-owned side table written through an adapter-owned storage port distinct from the core `DomainRepository` (D-083). The Telegram chat → community mapping is ratified by D-093 (implicit-on-first-message bootstrap; default 1:1 from `external_chat_id`; the core receives an opaque `community_id`; membership inherited from host-chat membership); many communities may coexist on one instance.

### What belongs to the core

- Domain model: `SourceMessage`, `Note`, `EventChunk`, `EmbeddingRecord`, `Query`, `AnswerTrace`, `RetrievalHit` (entity *shape* is core; names follow the canonical vocabulary — see `docs/GLOSSARY.md`).
- Message lifecycle (D-027): draft (raw-only), note (full ingestion), query. Absence of an explicit command defaults to draft so no inbound message is silently discarded.
- Ingestion pipeline: raw-first persistence, versioned parsing, line-level chunking, embedding generation, indexing — gated on the lifecycle state (only notes run the full pipeline; drafts stop at raw persistence).
- Retrieval: hybrid search seam, scope filtering, RRF fusion, retrieval traces.
- Answering: context assembly, grounded answer contract, fallback modes, evidence references.
- Raw export: on-demand export of raw `SourceMessage` data within the requester's scope, in JSON or TXT (D-027).
- Invariants: raw before enrichment, replayability, requested-vs-effective provenance, no silent degradation.
- Service-facing contracts: `IngestionService.ingest_source_message`, `QueryService.answer(query, scope)`.
- Tenancy abstraction: scope is opaque to the core (`community_id`); the core does not encode that a tenant is a "family" or that a subject is a "child".

### What belongs to adapters / integration layers

- Transport types and host identifiers (`telegram.Update`, webhook payloads, HTTP request shapes).
- Storage engine specifics (SQL, pgvector operators, SQLite calls).
- Provider SDKs (`openai`, host-provided model gateways).
- Host identity mapping (Telegram chat → tenant; TheyGrow workspace → tenant; OSS → single default tenant).
- Author display-name resolution (host-supplied identity fields → presentation name; for Telegram, `username → first_name → opaque short-ID`). The core carries only the opaque `author_user_id`; display names are non-authoritative presentation (D-081, A-44).
- Author display-input capture / persistence shape (host-supplied `username` / `first_name` snapshotted at the adapter/storage seam; nullable, non-authoritative; for later display resolution only). The core stores no display field; authorship stays the opaque `author_user_id` (D-082). The snapshot lands in a separate adapter-owned side table written through an adapter-owned storage port distinct from the core `DomainRepository`, keyed by the message idempotency tuple `external_chat_id + external_message_id + edit_seq` as opaque scalars — it never enters a core type or core repository signature (D-083). This keeps host-identity capture an adapter-owned feature while the shared core stays reusable across hosts (D-026 / D-041).
- Transport-bound presentation (Telegram message formatting, marker trailers, UI rendering).

### What must not leak into the core

- Transport types outside the channel adapter (already I-1).
- Provider SDK imports outside provider adapters (already I-11).
- Raw SQL or vendor-specific operators outside the storage layer.
- Use-case vocabulary in newly added code (`family`, `child`, `parent`, "diary" as a type name) where a generic name fits. Core code uses the canonical `community` / `subject` vocabulary (D-041; see `docs/GLOSSARY.md`).
- Assumptions that the runtime is HTTP-shaped, Telegram-shaped, single-tenant, internet-connected, or English-only.
- Authentication model assumptions; the core receives an already-resolved scope.

### Deployment shapes

D-026 names three first-class deployment shapes; D-027 makes managed cloud the default reference shape:

1. **Managed cloud (default).** Service runs in a managed environment with managed Postgres, scheduled backups (see "Durability, backup, and recovery"), and provider gateways. Production usage and any hosted offering instantiate this shape.
2. **Self-hosted OSS.** Same core, deployed on a user's own infrastructure. Postgres and provider seams remain Protocols; the operator chooses concrete backends and is responsible for backup/recovery within the contract below.
3. **Embedded.** The core runs inside another host (TheyGrow as the named first-class case; other embedded products later). Storage, providers, and identity mapping may be supplied by the host. The core does not assume sole ownership of the database or an exclusive network surface.

These are configurations of the same core behind the same adapter seams, not separate codebases. Promoting one shape (managed cloud) to the default is an operational choice, not an architectural one — the other two remain peers, not derivatives.

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
   /note         persist raw         hybrid search       grounded gen    routing trace
   /draft        parse date *        metadata filter     fallbacks       parse status
   /ask          split events *                          evidence ref    retrieval trace
   (none→draft)  embed + index *                                         answer trace
                                                                         export trace

   * note-only steps; drafts stop at raw persistence (D-027).
                                          │
                                          ▼
                                     PostgreSQL
                              (system of record:
                               source, note, chunk,
                               embedding refs, traces)
```

## Layering

- **Channel adapters** — Telegram today, TheyGrow tomorrow, plus future HTTP/SDK/CLI surfaces. Translate transport-specific input into core service calls. No domain logic.
- **Diary Memory Service** — the product core. Owns ingestion, retrieval, answering, traces. Has no transport or host knowledge.
- **Core domain** — the entities listed in TechSpec §5. Pure data + pure logic, no IO. Topic-neutral in shape; use-case-specific scope (family, child) is carried as opaque identifiers, not encoded in the model. The canonical core terms for that scope are `community` and `subject` (D-041; see `docs/GLOSSARY.md`).
- **Infrastructure** — PostgreSQL repositories, embedding client, chat client, hybrid search backend. Each behind an explicit interface (e.g. `SearchRepository`, `EmbeddingClient`, `ChatClient`).

## Boundary rules

- Telegram-specific types do not appear outside the Telegram adapter (I-1).
- Core domain does not import provider SDKs directly (I-11).
- Provider access goes through one wrapper per provider; every call is logged with model, input hash, latency, outcome class (R-7).
- Repository interfaces hide PostgreSQL specifics; no SQL outside the repository layer.
- Use-case vocabulary (`family`, `child`, `parent`, "diary" as a type name) does not appear in core code where a generic name fits (D-026); core code uses the canonical `community` / `subject` vocabulary (D-041).

## Message lifecycle: draft vs note

Inbound messages enter one of three lifecycle states. The state is set by the control surface (D-026 axis 2), not by message content:

- **Draft** — a message the user has not yet committed as a canonical note. The core persists it as raw `SourceMessage` and stops there: no parse, no chunk, no embed, no index. Drafts exist so absence of an explicit command never causes silent data loss; they are recoverable, exportable, and promotable to a note later.
- **Note** — a message the user has explicitly committed for capture. The full ingestion pipeline runs (parse → chunk → embed → index), governed by I-3, I-4, I-5.
- **Query** — a retrieval/answer request. No durable note is created; the `Query` row and any `AnswerTrace` are the persisted record.

Target control surface (D-027):

- `/note <text>` — explicit note. Triggers the full ingestion pipeline.
- `/draft <text>` — explicit draft. Raw persistence only.
- `/ask <text>` — query.
- **No command** — routes to **draft** only (D-078). Absence of an explicit command never silently discards, downgrades, or upgrades raw persistence; heuristics do not auto-route plain text to note or ask — those lifecycles are reached only via the explicit `/note` / `/ask` commands. (D-078 records this contract; D-079 enforces it in code — `classify_plain_text` routes command-less plain text only to the draft floor.)

The Telegram implementation exposes `/note`, `/ask`, `/drafts`, and `/export` (D-031); the explicit `/draft` command was removed in D-030, and the no-command-→-draft default is enforced in code (D-028). The lifecycle state is carried by `SourceMessage.detected_route` (extended with `RouteKind.DRAFT`), with `core.routing.lifecycle_for` as the canonical mapping helper — no separate lifecycle column. The routing enum value `RouteKind.NOTE` is persisted as `detected_route='note'` (D-042 renamed these from `RouteKind.ENTRY` / `detected_route='entry'`).

Lifecycle rules:

- Draft and note share the same raw `SourceMessage` shape; what differs is the lifecycle state and which downstream steps run.
- A draft may later be promoted to a note via an explicit user action. Promotion is replayable from the persisted raw text under the active parser/embedding versions (I-12).
- Drafts participate in raw export (see "Raw export"). They do not participate in retrieval.
- Command-less plain text persists as a draft regardless of routing confidence (R-11, R-13, D-078); no heuristic auto-routes it to note or ask. CLARIFY (D-020) survives only as a reply when an explicit command actively conflicts with intent — it is not a plain-text route. The safety floor is "raw always persists", regardless of routing confidence.

Specific draft retention, expiry, and promotion mechanics are bracketed as open assumptions.

## Data flow — ingestion (`/note`)

1. Channel adapter receives an inbound update.
2. Adapter calls `IngestionService.ingest_source_message(...)`.
3. Service persists `SourceMessage` (raw text, route hint, metadata) — **commit before any enrichment** (I-3, R-1).
4. Service parses date and splits event lines (`parse_version` recorded).
5. Service creates `Note` and one `EventChunk` per event line (I-5).
6. Service requests embeddings (sync or async — see assumption A-7).
7. Service indexes chunks into the hybrid search backend.
8. Service returns confirmation + parse trace; adapter formats the user-facing reply.

If any step after raw persistence fails, raw data is intact and the failed step is replayable (I-12).

## Data flow — query (`/ask`)

1. Channel adapter receives an inbound update.
2. Adapter calls `QueryService.answer(query, scope)`.
3. Service persists `Query`.
4. Service runs hybrid retrieval; applies community/subject/visibility filters (I-7, I-8).
5. Service assembles top-k context with provenance.
6. Service calls the grounded answer pipeline; records `AnswerTrace` with `context_chunk_ids` and `fallback_mode` (R-5).
7. Adapter renders the answer + evidence references for the user.

If retrieval is empty, weak, or ambiguous, the service emits an explicit fallback (I-9, R-6). No silent degradation.

## Durability, backup, and recovery

Raw data is the system's highest-tier durability surface. Embeddings, indexes, retrieval traces, and answer traces are all reproducible from raw `SourceMessage` rows; raw is not reproducible from anything else (I-2, I-3). The architecture treats raw with proportionate care (D-027).

Target contour:

- **Daily backup window.** A scheduled backup runs in a fixed nightly window (target: `03:00–05:00` local time). Backups cover at minimum `source_messages` (raw text + lifecycle metadata) plus enough relational scaffolding to restore the `SourceMessage → Note → EventChunk` lineage.
- **Stronger recovery than periodic backup.** The system must support recovery to a point closer to failure than the last nightly snapshot. The mechanism (continuous WAL archiving, point-in-time recovery, streaming replicas, or a managed-cloud equivalent) is selected per deployment shape; the requirement is that nightly-only is not the design floor.
- **Raw is especially durable.** Derived state (embeddings, indexes, traces) may be reconstructed by replay from raw under active parser/embedding versions; raw loss is unrecoverable. Operational policies (retention windows, restore drills) treat raw retention as the highest tier.
- **Replayability remains the recovery primitive.** Once raw is restored, parsing/chunking/embedding/indexing rerun (I-12). Replay produces logical state, not duplicates.

Specific backup tooling, retention windows, and RPO/RTO targets are resolved by D-053 (OP-4.1): for the reference Postgres shape, a nightly base backup + continuous WAL archiving → point-in-time recovery, RPO ≤ 5 min / RTO ≤ 1 h, and 30-day base-backup retention; managed-cloud and self-hosted shapes use the provider- or operator-owned equivalent.

## Raw export

The user MUST be able to export their raw data on demand (D-027).

Target contour:

- **Scope.** The export covers raw `SourceMessage` rows (both draft and note) within the requester's scope. Derived state (notes, chunks, embeddings, traces) is not in the minimum export contract — raw is enough to reconstruct everything else.
- **Formats.** Both **JSON** (machine-friendly: stable field names, ISO timestamps) and **TXT** (human-readable: one record per block) are supported. The requester chooses the format per request.
- **Authorization.** The export is scope-bounded the same way retrieval is (R-3); a request never returns data outside the requester's scope.
- **Provenance.** The export records its own generation metadata (export id, scope, time range, format, requester) so the operator can audit which raw was released to whom.

Export is a core capability invoked through the control-surface axis. Transport-specific delivery (Telegram file reply, HTTP download, host-app screen) is adapter-side. Specific delivery channels and request shapes are bracketed as open assumptions.

## Why this shape

- Keeps the write path safe from LLM/availability problems.
- Makes the integration into TheyGrow an adapter swap, not a rewrite — and the same shape extends to OSS self-host, managed cloud, and other embedded hosts.
- Allows the indexing/retrieval backend to evolve without touching domain code.
- Allows replay of any past `SourceMessage` under a new parser or embedding version.
- Treats absence of an explicit command as a draft, not as loss — valuable personal information survives even when the user's intent is unclear (D-027).
- Treats raw as the highest-tier durability surface, with a daily backup window and stronger-than-nightly recovery — derived state is always reproducible, raw is not (D-027).

## Out of scope here

- Concrete table DDL — lives with the migration in Phase 2.
- Concrete prompt templates — live with the answer pipeline in Phase 4.
- Provider-specific configuration — lives in `.env` and the provider adapter.
