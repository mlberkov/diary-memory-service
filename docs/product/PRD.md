# PRD — Diary RAG Service for TheyGrow

## Status
Draft v1  
Owner: Founder  
Purpose: canonical product context for the first implementation slice

## 1. Product Intent

The system is a **portable memory/journal core** surfaced through host-specific adapters. It exists to capture and recall valuable personal information — observations, events, reflections — without forcing the user to commit to a single host or topic. The topic model is generic; child- and family-related capture is **one possible use case**, not the system's definition.

The **first use case** — and the scope of this PRD — is parents who write family and child-related observations in Telegram and later ask natural-language questions over these records. The same core is intended to support additional hosts (TheyGrow, self-hosted OSS, managed cloud, other embedded products) without rewrite.

The short-term interface is Telegram. The long-term product destination spans:
- **managed cloud** as the default reference deployment (D-027),
- **self-hosted OSS** as a peer deployment shape,
- **embedded** in TheyGrow and other host products as a reusable internal memory subsystem.

Core principles (D-026, D-027):
- Telegram is one event-source adapter, not the product core.
- The core is a standalone, portable memory/journal core — currently surfaced as a Diary Memory Service.
- The parents / family-diary framing below is the first use case, not the definition of the system.
- Absence of an explicit command must never cause silent data loss: any message the user sends is, at minimum, preserved as a draft.
- Raw data is durable by design (daily backup window, stronger-than-nightly recovery) and exportable on demand (JSON or TXT).

## 2. Problem

Parents can write observations quickly in chat, but later cannot reliably:
- find relevant events,
- reconstruct timelines,
- ask semantic questions over diary history,
- distinguish meaningful memories from noisy chat history,
- reuse this memory layer inside a dedicated product.

Telegram history is not a memory system:
- weak semantic retrieval,
- poor metadata filtering,
- no grounded answer generation,
- no product-grade provenance.

## 3. Users

Primary users:
- one parent maintaining a private diary,
- two parents maintaining a shared family diary.

Future users:
- TheyGrow families using the same memory layer inside `theygrow.app`.

## 4. Core User Jobs

### Job 1 — Capture without loss
As a user, I want to record important observations with minimal friction so that I do not lose them — even when I am unsure whether what I just wrote is "ready" to be a canonical note.

### Job 2 — Recall
As a user, I want to ask natural-language questions over my own captured memory and get grounded answers.

### Job 3 — Shared Memory
As co-authors, we want to maintain a shared memory space while preserving authorship and context.

### Job 4 — Portability
As a product team, we want the same memory core to move from Telegram into TheyGrow (and other hosts) without re-architecture.

### Job 5 — Own my data
As a user, I want to export my raw captured data on demand and trust that it is durably backed up — including a recovery story stronger than "wait for the next nightly backup".

## 5. Input Model

A user writes messages in a chat (Telegram today; other hosts later). Routing is set by the user's command, not by message content (D-027, D-030):

- `/note <text>` — explicit **note**. Eligible for the full ingestion pipeline (parse → chunk → embed → index).
- `/ask <text>` — **query**. Treated as a retrieval request over previously captured notes.
- `/drafts [N]` — **recall** the most recent full raw drafts back into the chat (D-030).
- **No command** — treated as a **draft**. The raw text is persisted as a `SourceMessage` with `detected_route='draft'`. No path silently discards an inbound message. Drafts are not note-candidates and have no promotion path (D-030); recall (`/drafts`) and export (`/export`) are the operations available on captured drafts.

### Note capture shape

A `/note` whose text follows the canonical shape:

```
2026-05-09
Had a calm morning routine
Tried a new picture book
Fell asleep 20 minutes earlier than usual
```

- the first line contains the date,
- each following line is a separate event and becomes its own chunk.

### Heuristics on top of the draft floor

Heuristics MAY suggest a stronger route (note or ask) for plain text, but MUST NOT override the draft floor. A heuristic that cannot suggest with confidence falls back to draft — never to silent discard.

### Naming note

The target command names are `/note`, `/ask`, `/drafts`. The current Telegram implementation exposes `/entry` (the historical name for `/note`), `/ask`, `/drafts`, and `/export`; the no-command-→-draft default is in place (D-028) and the explicit `/draft` command was removed (D-030). The `/entry` → `/note` rename is a separate naming-alignment packet.

## 6. Functional Scope

### In scope for MVP
- Telegram text input,
- explicit `/entry`, `/ask`, and `/drafts` commands (the current command surface; `/entry` is the historical name for `/note`; the explicit `/draft` command was removed in D-030 — the no-command default carries the draft floor),
- heuristic auto-routing by date presence on top of the draft floor: high-confidence ENTRY/ASK signals route as before; everything else persists as a draft (D-028),
- date parsing,
- line-by-line event splitting,
- one event per chunk,
- raw message persistence,
- event chunk persistence,
- embeddings generation,
- hybrid retrieval,
- metadata filtering,
- grounded answer generation,
- retrieval provenance,
- observability for ingestion and retrieval.

### In scope for target state (beyond current MVP)
- raw export on demand in JSON or TXT (D-027),
- daily backup window and stronger-than-nightly recovery surfaced operationally (D-027),
- managed-cloud reference deployment as the default operational shape (D-027).

### Out of scope for MVP
- voice/photo/video ingestion,
- automatic developmental coaching,
- medical recommendations,
- graph updates into full TheyGrow knowledge graphs,
- multi-agent orchestration,
- rich web UI,
- proactive recommendations.

## 7. Product Principles

1. Telegram is a transport and UX layer only.
2. The source of truth must live outside Telegram.
3. Absence of an explicit command never causes silent data loss; the safety floor for ambiguous input is a draft, not a discard.
4. Every answer must be grounded in retrieved evidence.
5. Retrieval must be future-portable into TheyGrow and other hosts.
6. Shared-memory mode must preserve authorship.
7. Optional AI enrichments must be feature-flagged, not entangled with the base flow.
8. No silent failure may pretend confidence.
9. Raw data is durable by design: daily backup window, stronger-than-nightly recovery, on-demand raw export.
10. The topic model is generic; child- and family-oriented capture is one use case, not the system's definition.

## 8. Success Criteria

### User outcomes
- diary capture feels lightweight and fast,
- questions over diary history return useful answers,
- users can inspect the basis of answers,
- solo and shared usage are both supported.

### System outcomes
- raw messages are never lost,
- parsing and chunking are replayable,
- indexing failures do not destroy source data,
- retrieval behavior is inspectable,
- answer generation degrades gracefully when evidence is weak,
- raw data is recoverable from a daily backup window with a tighter recovery point than nightly-only,
- users can export their raw data on demand in JSON or TXT.

## 9. Risks

1. Routing ambiguity between diary entries and questions.
2. Weak retrieval on temporally important memories.
3. Shared-journal access complexity.
4. Telegram-specific assumptions leaking into core architecture.
5. Low user trust if answer provenance is weak.

## 10. MVP Recommendation

Build the first production slice as:
1. Telegram `/entry`
2. raw message persistence
3. parse date
4. split event lines
5. create chunks
6. embed and index
7. Telegram `/ask`
8. retrieve top evidence
9. generate grounded answer
10. return answer with evidence references

## 11. Integration Direction

The service must support multiple hosts as first-class integration shapes (D-026, D-027):
- Telegram bot as one event-source adapter (current),
- TheyGrow backend/app as a named first-class embedded host,
- self-hosted OSS as a peer deployment shape,
- **managed cloud** as the **default reference deployment**,
- other embedded products and future web/app surfaces through internal API or SDK.

Each must be an integration path, not a rewrite path. Hosts vary along the five adapter axes (event source, control surface, storage/infrastructure, embedding/LLM providers, tenant/auth mapping); the functional core stays the same.
