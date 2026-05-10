# Tech Spec — Diary RAG Service for TheyGrow

## Status
Draft v1

## 1. Architecture Position

The system must be implemented as a standalone Diary Memory Service.

### Current channel
- Telegram bot

### Future channel
- TheyGrow app/backend

### Rule
Telegram-specific logic must remain in the adapter layer and must not define the core domain model.

## 2. Core Technical Direction

### Recommendation
Build the core flow from scratch.

Do not use LangChain or LangGraph as the architectural foundation.

### Why
The system needs:
- explicit runtime contracts,
- deterministic ingestion,
- inspectable provenance,
- clear fallback behavior,
- migration-friendly boundaries.

### Allowed usage of frameworks
Optional frameworks may be used only for:
- retriever experiments,
- evaluation harnesses,
- isolated utilities.

LangGraph is not recommended at MVP stage because the problem is still a relatively direct single-service RAG flow rather than a multi-agent workflow graph.

## 3. System Model

### Main flow
1. receive Telegram message,
2. classify route,
3. persist raw source message,
4. parse date if entry,
5. split into event chunks,
6. persist normalized records,
7. generate embeddings,
8. index chunks,
9. accept query,
10. retrieve evidence,
11. assemble context,
12. generate grounded answer,
13. log trace.

### Ordering rule
Route classification (step 2) operates on the incoming in-memory message and does not require any persisted state.
The `SourceMessage` row (step 3) must be committed before any enrichment step — parsing, chunking, embedding, or indexing — runs. No enrichment step may begin if raw persistence has not succeeded.

## 4. Routing

### Preferred routing
- `/entry` → diary ingestion path
- `/ask` → question path

### Convenience routing
- date present at message start → diary path
- no date present → question path

### Safety rule
If routing confidence is low, the system should ask for clarification rather than silently misclassify.

## 5. Data Model

### Core entities
- `User`
- `Family`
- `Child`
- `TelegramChat`
- `SourceMessage`
- `DiaryEntry`
- `EventChunk`
- `EmbeddingRecord`
- `Query`
- `RetrievalHit`
- `AnswerTrace`
- `FeedbackEvent`

### SourceMessage
Fields:
- source_message_id
- external_chat_id
- external_user_id
- external_message_id
- edit_seq
- family_id
- author_user_id
- raw_text
- detected_route
- raw_date_detected
- timezone
- created_at
- edited_at
- deleted_at
- parse_status
- parse_version

`external_chat_id` and `external_user_id` replace the channel-specific
`telegram_chat_id` / `telegram_user_id` so the channel-of-origin stays in the
adapter layer (Invariant I-1). The triple `(external_chat_id,
external_message_id, edit_seq)` is the idempotency key enforced by Runtime
invariant R-2 (D-023): for Telegram, `edit_seq` is `0` for an original
delivery and the `edit_date` epoch seconds for an edited state.

### DiaryEntry
Fields:
- diary_entry_id
- family_id
- child_id
- entry_date
- source_message_id
- author_user_id
- entry_text
- visibility_scope
- created_at

### EventChunk
Fields:
- chunk_id
- diary_entry_id
- source_message_id
- family_id
- child_id
- author_user_id
- entry_date
- event_index
- chunk_text
- normalized_text
- tags_json
- embedding_status
- index_status
- created_at

### Query
Fields:
- query_id
- source_message_id
- family_id
- author_user_id
- child_scope
- query_text
- normalized_query_text
- rewrite_text
- created_at

### RetrievalHit
Fields:
- retrieval_hit_id
- query_id
- chunk_id
- score_dense
- score_sparse
- score_hybrid
- rerank_score
- selected_for_context
- rank_position
- retrieval_reason

### AnswerTrace
Fields:
- answer_trace_id
- query_id
- prompt_version
- context_chunk_ids
- answer_text
- confidence_band
- fallback_mode
- model_name
- token_counts
- latency_ms
- created_at

## 6. Chunking Contract

Input:
- one Telegram diary message,
- date at the beginning,
- each following line is a diary event.

Chunking rule:
- each event line becomes one chunk.

Additional storage recommendation:
- preserve raw source message,
- preserve logical diary entry,
- preserve event-level chunks.

This creates replayability and provenance.

## 7. Metadata Contract

Minimum metadata per chunk:
- family_id
- child_id
- author_user_id
- source_message_id
- diary_entry_id
- event_index
- entry_date
- created_at
- visibility_scope
- parse_version

## 8. Persistence Contract

### Source of truth
PostgreSQL should be the primary durable system of record.

### Requirement
Raw source message must be persisted before embeddings or indexing.

### Rationale
No provider failure may destroy original user input.

## 9. Retrieval Contract

### Retrieval style
Hybrid retrieval is required.

### Retrieval abstraction
The retrieval backend must be swappable behind an interface such as `SearchRepository`.

### Retrieval v1 flow
1. normalize query,
2. detect optional date constraints,
3. run hybrid retrieval,
4. apply family/visibility/child filters,
5. merge and deduplicate hits,
6. select top-k context,
7. return retrieval trace.

### Context policy
- retrieve top 5 to 12 chunks,
- prefer diversity across dates,
- deduplicate near-identical lines,
- optionally apply recency boost,
- group by date in final answer prompt when useful.

## 10. Answer Contract

Every answer must:
- be based on retrieved evidence,
- expose supporting snippets or references,
- explicitly state uncertainty when evidence is weak,
- refuse to pretend certainty when evidence is missing.

Fallback modes:
- no evidence found,
- weak evidence found,
- ambiguous query,
- out-of-scope request,
- provider unavailable.

## 11. Optional AI Enhancements

These must be feature-flagged:
- query rewriting,
- semantic expansion,
- reranking,
- answer style control,
- timeline mode,
- analytical synthesis mode.

Important rule:
- base retrieval and answer flow must still work with all enhancements disabled.

## 12. Edit and Delete Strategy

This is not fully fixed yet and must be decided explicitly.

Open questions:
- whether edited Telegram messages create revisions or mutate the latest record,
- whether deleted messages tombstone chunks or hard-delete them,
- how re-indexing is triggered after edits.

Current recommendation:
- use revision-friendly design,
- never lose source lineage,
- prefer tombstones over silent destructive deletion.

## 13. Observability

The system must log:
- message routing decision,
- parse result,
- chunk creation result,
- embedding/index status (D-024: `embedding.ok` carries provider model + chunk count + dimension; `embedding.failed` carries provider model + chunk count + exception class),
- retrieval trace,
- answer generation trace,
- fallback requested vs effective path,
- latency and error class.

## 14. Invariants

1. Telegram is a channel, not the system of record.
2. Raw source data is persisted before enrichment.
3. Every answer links to evidence.
4. Empty retrieval produces explicit fallback.
5. Fallbacks are logged and discoverable.
6. Optional AI enrichments are not mandatory for the base flow.
7. Domain logic must not depend on framework internals.
