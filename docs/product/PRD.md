# PRD — Diary RAG Service for TheyGrow

## Status
Draft v1  
Owner: Founder  
Purpose: canonical product context for the first implementation slice

## 1. Product Intent

This service provides a low-friction diary memory system for parents who write family and child-related observations in Telegram and later ask natural-language questions over these records.

The short-term interface is Telegram.  
The long-term product destination is integration into TheyGrow as a reusable internal memory subsystem.

Core principle:
- Telegram is the initial channel, not the product core.
- The core is a standalone Diary Memory Service.

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

### Job 1 — Capture
As a parent, I want to record important events with minimal friction so that I do not lose them.

### Job 2 — Recall
As a parent, I want to ask natural-language questions over my diary and get grounded answers.

### Job 3 — Shared Memory
As a couple, we want to maintain a shared memory space while preserving authorship and context.

### Job 4 — Portability
As a product team, we want the same memory core to move from Telegram into TheyGrow without re-architecture.

## 5. MVP Input Model

A user writes messages in a Telegram chat.

### Diary message
A message that begins with a date is treated as a diary entry.

Expected structure:
- first line or leading prefix contains date,
- each following line is a separate event.

Example:
2026-05-09
Had a calm morning routine
Tried a new picture book
Fell asleep 20 minutes earlier than usual

### Query message
A message without a date is treated as a question and triggers retrieval + answer generation.

Important note:
- this heuristic is allowed for MVP,
- but explicit commands `/entry` and `/ask` should also exist,
- commands are the preferred routing method,
- heuristic routing is only a convenience layer.

## 6. Functional Scope

### In scope for MVP
- Telegram text input,
- explicit `/entry` and `/ask` commands,
- heuristic auto-routing by date presence,
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
3. Every answer must be grounded in retrieved diary evidence.
4. Retrieval must be future-portable into TheyGrow.
5. Shared-diary mode must preserve authorship.
6. Optional AI enrichments must be feature-flagged, not entangled with the base flow.
7. No silent failure may pretend confidence.

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
- answer generation degrades gracefully when evidence is weak.

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

The service must later support:
- Telegram bot as one client,
- TheyGrow backend/app as another client,
- future web/app surfaces through internal API or SDK.

This must be an integration path, not a rewrite path.
