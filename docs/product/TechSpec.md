# Tech Spec — Diary RAG Service for TheyGrow

## Status
Draft v1

## 1. Architecture Position

The system must be implemented as a standalone Diary Memory Service — a **portable memory/journal core** surfaced through host-specific adapters (D-026). The first use case is a family/child diary; the core itself is topic-neutral.

### Current channel
- Telegram bot

### Future channels and deployment shapes
- TheyGrow app/backend (embedded host, named first-class case),
- self-hosted OSS (peer shape),
- **managed cloud as the default reference deployment** (D-027),
- other embedded products and future web/app surfaces.

### Rule
Telegram-specific logic must remain in the adapter layer and must not define the core domain model. The same boundary applies to other event sources, control surfaces, storage backends, provider SDKs, and tenant/auth mappings — each is one of the five adapter axes named in `docs/ARCHITECTURE.md` (D-026).

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

### Target command surface (D-027)
Inbound messages enter one of three lifecycle states — **draft**, **note**, or **query** — set by the user's command, not by message content:

- `/note <text>` → canonical note. Triggers the full ingestion pipeline (parse → chunk → embed → index).
- `/draft <text>` → explicit draft. Persisted as raw `SourceMessage` only; no parse, chunk, embed, or index.
- `/ask <text>` → query / retrieval.
- **No command** → defaults to **draft**. The raw text is persisted; the user may later promote it to a note. No path silently discards an inbound message.

### Current command surface
The Telegram adapter exposes `/entry` (the historical name for `/note`), `/draft`, and `/ask`. The no-command-→-draft default is also in place (D-028). Renaming `/entry` to `/note` is part of the broader naming-alignment packet (D-026).

### Convenience routing
Heuristics MAY suggest a stronger route (note or ask) for plain text, but MUST NOT override the draft floor. As of D-028, the classifier keeps the high-confidence ENTRY (`first_line_iso_date_with_events`) and ASK (`question_mark_terminator`, `interrogative_or_imperative_first_token`) rules and routes everything else to `RouteKind.DRAFT` (reason `draft_floor_no_signal`). CLARIFY remains a valid response kind but no plain-text path emits it; it survives in the dispatcher for explicit-command active-conflict cases.

### Safety rule
The safety floor for ambiguous input is **preserve as draft**, not **clarify and drop** (D-027 / D-028). Absence of an explicit command never causes silent data loss. CLARIFY remains a valid response shape when a heuristic would actively conflict with intent (D-020), but raw persistence is unconditional.

### Lifecycle representation
`SourceMessage.detected_route` carries the lifecycle state (D-028). The `core.routing.lifecycle_for` helper maps routes to the canonical lifecycle vocabulary — `ENTRY → "note"`, `ASK → "query"`, `DRAFT → "draft"`, everything else → `"other"` — so the persisted `detected_route` value doubles as the lifecycle marker without a parallel column. Renaming `ENTRY` → `NOTE` is its own naming-alignment packet (D-026).

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

### Raw durability (D-027)
Raw `SourceMessage` is the highest-tier durability surface. Derived state (embeddings, indexes, retrieval traces, answer traces) is reproducible from raw under the active parser/embedding versions; raw is not reproducible from anything else.

Operational policy requires:
- a daily backup window (target: `03:00–05:00` local time) covering at minimum `source_messages` plus enough relational scaffolding to restore the `SourceMessage → DiaryEntry → EventChunk` lineage,
- a stronger-than-nightly recovery primitive (continuous WAL archiving, point-in-time recovery, streaming replicas, or a managed-cloud equivalent — selected per deployment shape; mechanism bracketed as A-40),
- retention windows and restore drills that treat raw as the highest tier.

### Raw export (D-027)
The user must be able to export their raw `SourceMessage` data on demand in either JSON (stable field names, ISO timestamps) or TXT (one record per block). The export is scope-bounded the same way retrieval is, and records its own provenance (export id, scope, time range, format, requester). Derived state is not in the minimum export contract. Per-host delivery channels and request shape are bracketed as A-39.

## 9. Retrieval Contract

### Retrieval style
Hybrid retrieval is required. Enforced as of D-025 as a **baseline** contour; quality optimizations (BM25, rerankers, external search systems) are explicit follow-ups, not part of the base contract.

### Retrieval abstraction
The retrieval backend is the `SearchRepository` Protocol (`src/diary_rag/storage/search_repository.py`), with two independent legs:

- `dense_candidates(family_id, query_embedding, model_name, limit) -> list[EventChunk]`
- `sparse_candidates(family_id, query_text, limit) -> list[EventChunk]`

The three concrete stores (mock, sqlite, postgres) each satisfy both `DiaryRepository` (ingest) and `SearchRepository` (retrieval); the union is named `HybridDiaryStore`. SQLite raises `NotImplementedError` from the retrieval methods because it is opt-in for ingest only; Postgres is the canonical retrieval backend.

### Retrieval v1 flow
1. normalize query (strip whitespace + trailing punctuation),
2. compute the query embedding once via the configured `EmbeddingClient`,
3. run dense + sparse legs against `SearchRepository`,
4. fuse the two ranked lists with **service-layer Reciprocal Rank Fusion** (`k=60`),
5. truncate to `retrieval_top_k` (Settings; default 5),
6. wrap each chunk as `Evidence(chunk_id, entry_date, chunk_text)`,
7. log `retrieval.hybrid family_id=… model=… dense_n=… sparse_n=… merged_n=…`.

Date constraints, family/visibility/child filters, dedup, and retrieval-trace persistence belong to Phase 3.4 / 3.5; they are not in the D-025 baseline.

### Dense leg (Postgres)
- Exact family-scoped sequential scan over the canonical `vector(3072)` column.
- `ORDER BY embedding <=> %s::vector` (cosine distance), joined to `event_chunks` on `chunk_id`, filtered to `embedding_status='ready'` and the active `model_name`.
- No HNSW / IVFFlat — pgvector caps those at 2000 dim, so the canonical column cannot use them. Halfvec / HNSW is **A-36b**, deferred to the next quality-decision packet.

### Sparse leg (Postgres)
- Generated stored column `event_chunks.chunk_text_tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', chunk_text)) STORED`, with a GIN index `idx_event_chunks_chunk_text_tsv`.
- Queries use `websearch_to_tsquery('simple', $q)` and order by `ts_rank_cd`. The `'simple'` dictionary avoids stemming so mixed Russian/English content is treated symmetrically (**A-37**).
- **BM25 is not in this packet.** The next quality-decision packet revisits sparse quality.

### Fusion
- Reciprocal Rank Fusion at the service layer (`services/retrieval.py`), pure function over ranked lists, `k=60`.
- No score calibration between cosine distance and `ts_rank` — RRF uses rank position only.
- No reranker / cross-encoder in this packet; both are deferred.

### Context policy
- retrieve `retrieval_top_k` chunks (default 5) from a candidate pool of `retrieval_candidate_k` per leg (default 20),
- prefer diversity across dates — deferred to Phase 3.4,
- deduplicate near-identical lines — deferred,
- optionally apply recency boost — deferred,
- group by date in final answer prompt when useful — deferred to Phase 4.

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
8. Absence of an explicit command never causes silent data loss; the safety floor for ambiguous input is a draft, not a discard (D-027).
9. Raw is the highest-tier durability surface; on-demand raw export in JSON or TXT is a required capability (D-027).
