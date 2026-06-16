# Tech Spec — Shared-Memory Core / Note-Grounded Answer Service

*First implemented use case: a Telegram family/child diary. Later integration host: TheyGrow (D-041).*

## Status
Draft v1

## 1. Architecture Position

The system must be implemented as a standalone **generic shared-memory / note-grounded answer service** — a portable memory/journal core surfaced through host-specific adapters (D-026, D-041), currently surfaced through its first use case as a Diary Memory Service. The first implemented use case is a family/child diary; the core itself is topic-neutral. The canonical core vocabulary is `community` (the outer scope owning a note corpus) and `subject` (a sub-entity a note is about) — see `docs/GLOSSARY.md`.

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
4. parse date if note,
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

### Target command surface (D-027, D-030)
Inbound messages enter one of three lifecycle states — **draft**, **note**, or **query** — set by the user's command (or by the no-command default), not by message content:

- `/note <text>` → canonical note. Triggers the full ingestion pipeline (parse → chunk → embed → index).
- `/ask <text>` → query / retrieval.
- `/drafts [N]` → recall the most recent full raw drafts back into chat (D-030). Action, not a lifecycle state.
- `/export <json|txt>` → raw export (D-029).
- `/chat <text>` → routed conversational question (D-108): classified into one of four routes and answered under per-segment provenance labels. All four routes are dispatchable (RC-2..RC-4 / D-109, D-110, D-111; `docs/ROUTED-CHAT-ROADMAP.md`); a `diary_plus_web` request still falls back to `diary_lookup` when no knowledge source is configured (`KNOWLEDGE_BACKEND`).
- **No command** → defaults to **draft**. The raw text is persisted as a `SourceMessage` with `detected_route='draft'`. No path silently discards an inbound message. Drafts are not note-candidates and have no promotion path (D-030).

### Current command surface
The Telegram adapter exposes `/note`, `/ask`, `/drafts`, and `/export` (D-031). The no-command-→-draft default is in place (D-028). The explicit `/draft` command was removed in D-030; rows previously persisted with `detected_route='draft'` remain valid. The note-lifecycle routing enum value is `RouteKind.NOTE`, persisted as `detected_route='note'` and admitted by the Postgres CHECK constraint (the D-042 roadmap renamed these from `RouteKind.ENTRY` / `detected_route='entry'`).

### Convenience routing
Command-less plain text routes only to the draft floor (`RouteKind.DRAFT`, reason `draft_floor_no_signal`). As of D-078 the classifier no longer auto-routes plain text to NOTE (first-line ISO date) or ASK (question shape); those high-confidence heuristics — retained by D-028 (`first_line_iso_date_with_events`; `question_mark_terminator`, `interrogative_or_imperative_first_token`) — are retired, and NOTE/ASK are reached only via the explicit `/note` / `/ask` commands. CLARIFY remains a valid response kind for explicit-command active-conflict cases but no plain-text path emits or reaches it (dormant since D-028). (D-078 records this contract; D-079 enforces it in code — `classify_plain_text` routes command-less plain text only to the draft floor.)

### Safety rule
The safety floor for ambiguous input is **preserve as draft**, not **clarify and drop** (D-027 / D-028). Absence of an explicit command never causes silent data loss. CLARIFY remains a valid response shape when a heuristic would actively conflict with intent (D-020), but raw persistence is unconditional.

### Lifecycle representation
`SourceMessage.detected_route` carries the lifecycle state (D-028). The `core.routing.lifecycle_for` helper maps routes to the canonical lifecycle vocabulary — `NOTE → "note"`, `ASK → "query"`, `DRAFT → "draft"`, everything else → `"other"` — so the persisted `detected_route` value doubles as the lifecycle marker without a parallel column.

## 5. Data Model

### Core entities
- `User`
- `Family`
- `Child`
- `TelegramChat`
- `SourceMessage`
- `Note`
- `EventChunk`
- `EmbeddingRecord`
- `Query`
- `RetrievalHit`
- `AnswerTrace`
- `IndexingDeadLetter`
- `FeedbackEvent`

> `Family` and `Child` are the first-use-case entity names for the canonical core concepts `community` and `subject` (D-041; see `docs/GLOSSARY.md`). The realized scope identifiers in code and schema are `community_id` and the nullable `subject_id` (Milestone H; see the subject-scoping note below). Community bootstrap is **implicit-on-first-message** and the chat→community mapping is the tenant/auth adapter axis (default Telegram: 1:1 from `external_chat_id`), ratified by D-093 and realized by the single adapter-owned `resolve_community_id` resolver (D-094, see `docs/GROUPED-MULTI-DIARY-ROADMAP.md`); membership is inherited from host-chat membership. **Grouped diaries (a shared chat is one community with preserved per-sender authorship) and multiple diaries on one instance (many communities coexist without leakage) are supported** (G-1/G-2; D-094/D-095; operator how-to in `docs/RUNBOOK.md`, D-096). Per-note visibility remains deferred (A-15 / Slice 8.2). Subject scoping is the second scoping dimension and is **supported** (Milestone H, D-097/D-107): its contract is ratified by D-097 (A-45 **closed → D-097**) — `subject_id` is an opaque, community-scoped, **nullable** identifier on `Note` / `EventChunk`, assigned by an adapter-axis function with a default single-subject mapping, `null` = community-wide, with **no** core subject registry/entity and an **optional** strict-match retrieval filter mirroring the D-040 `date_range` seam; it is separate from A-15 visibility. The code realization landed as Milestone H / H-1..H-4 (`docs/SUBJECT-SCOPING-ROADMAP.md`): the nullable `subject_id` field on `Note` / `EventChunk` (`core/domain/models.py`) plus the durable schema (the `0005.subject-id-columns` migration) (H-1); adapter-axis assignment via the single adapter-owned `resolve_subject_id` resolver (H-2); the optional keyword-only `subject_scope` retrieval filter, recorded on the persisted `Query` row (H-3, D-107; the `0006.query-subject-scope` migration); and the cross-seam regression suite `tests/test_subject_scoping.py` plus docs reconciliation (H-4) — the §5 field lists below carry the canonical `subject_id` / `subject_scope` names. There is no inbound `/ask` subject syntax and no subject-selection UX (deferred; operator how-to in `docs/RUNBOOK.md`). No `Family` / `Child` / `Community` / `Participant` / `Subject` table exists yet.

### SourceMessage
Fields:
- source_message_id
- external_chat_id
- external_user_id
- external_message_id
- edit_seq
- community_id
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

`author_user_id` is the **opaque core author identifier** (mandatory per I-6).
The core stores and scopes by it but never decodes or renders it; a
human-readable **author display name** is resolved only at the host adapter
seam (Telegram today) from host-supplied identity fields
(`username → first_name → opaque short-ID`) and is non-authoritative
presentation, not a core field. The sole sanctioned display surface this
milestone is `/sources`; answer-reply attribution is deferred (D-081, A-44). The adapter/storage-owned snapshot capture shape for those host identity fields (`username` / `first_name`; nullable, non-authoritative; for later adapter-side display resolution only) is pinned by D-082; the core adds no display field. D-083 pins the landing seam (Option A): that snapshot lands in a separate adapter-owned side table written through an adapter-owned storage port distinct from the core `DomainRepository`, keyed by the message idempotency tuple `external_chat_id + external_message_id + edit_seq` as opaque scalars; the core repository signature is unchanged.

### Note
Fields:
- note_id
- community_id
- subject_id
- note_date
- source_message_id
- author_user_id
- note_text
- visibility_scope
- created_at

### EventChunk
Fields:
- chunk_id
- note_id
- source_message_id
- community_id
- subject_id
- author_user_id
- note_date
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
- community_id
- author_user_id
- subject_scope
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

### IndexingDeadLetter
Fields:
- dead_letter_id
- source_message_id
- community_id
- chunk_ids
- model_name
- error_class
- created_at

One row recording a failed indexing job: when an embedding call raises during
ingest, the affected chunks are marked `embedding_status='failed'` (A-35) and
the service additionally attempts to persist this record (OP-2.2 / D-048).
`chunk_ids` lists every chunk the failed call covered; `error_class` is the
exception class name only. The record is append-only — it carries no status
field; OP-3 reconciliation consumes this surface without mutating it. The
write is best-effort: `event_chunks.embedding_status` stays the authoritative
failure signal.

## 6. Chunking Contract

Input:
- one Telegram diary message,
- date at the beginning,
- the remaining lines are the note body (which may be a multi-line dialogue or transcript).

Chunking rule:
- each explicit `/note` becomes exactly one chunk; newlines in the body are content structure, not event separators (I-5, D-106).

Additional storage recommendation:
- preserve raw source message,
- preserve the logical note,
- preserve event-level chunks.

This creates replayability and provenance.

## 7. Metadata Contract

Minimum metadata per chunk:
- community_id
- subject_id
- author_user_id
- source_message_id
- note_id
- event_index
- note_date
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
- a daily backup window (target: `03:00–05:00` local time) covering at minimum `source_messages` plus enough relational scaffolding to restore the `SourceMessage → Note → EventChunk` lineage,
- a stronger-than-nightly recovery primitive (continuous WAL archiving, point-in-time recovery, streaming replicas, or a managed-cloud equivalent — selected per deployment shape; mechanism selected by D-053 — nightly base backup + continuous WAL archiving → PITR, with RPO ≤ 5 min / RTO ≤ 1 h targets),
- retention windows and restore drills that treat raw as the highest tier.

### Raw export (D-027)
The user must be able to export their raw `SourceMessage` data on demand in either JSON (stable field names, ISO timestamps) or TXT (one record per block). The export is scope-bounded the same way retrieval is, and records its own provenance (export id, scope, time range, format, requester). Derived state is not in the minimum export contract. Per-host delivery channels and request shape are bracketed as A-39.

## 9. Retrieval Contract

### Retrieval style
Hybrid retrieval is required. Enforced as of D-025 as a **baseline** contour; quality optimizations (BM25, rerankers, external search systems) are explicit follow-ups, not part of the base contract.

### Retrieval abstraction
The retrieval backend is the `SearchRepository` Protocol (`src/memory_rag/storage/search_repository.py`), with two independent legs:

- `dense_candidates(community_id, query_embedding, model_name, limit, *, date_range=None) -> list[EventChunk]`
- `sparse_candidates(community_id, query_text, limit, *, date_range=None) -> list[EventChunk]`

The three concrete stores (mock, sqlite, postgres) each satisfy both `DomainRepository` (ingest) and `SearchRepository` (retrieval); the union is named `HybridDomainStore`. SQLite raises `NotImplementedError` from the retrieval methods because it is opt-in for ingest only; Postgres is the canonical retrieval backend.

### Retrieval v1 flow
1. normalize query (strip whitespace + trailing punctuation),
2. compute the query embedding once via the configured `EmbeddingClient`,
3. run dense + sparse legs against `SearchRepository`,
4. fuse the two ranked lists with **service-layer Reciprocal Rank Fusion** (`k=60`),
5. truncate to `retrieval_top_k` (Settings; default 5),
6. wrap each chunk as `Evidence(chunk_id, note_date, chunk_text)`,
7. log `retrieval.hybrid community_id=… model=… dense_n=… sparse_n=… merged_n=…`.

The optional **date-range filter** has landed (D-040, Slice 3.4): both legs accept a keyword-only `date_range` carrying an inclusive `note_date` lower/upper bound (either side optional). It defaults to `None` — no constraint — so the D-025 retrieval shape and the RRF inputs are unchanged when unused. The remaining visibility/subject metadata filters, dedup, and retrieval-trace persistence belong to Phase 3.4 / 3.5; they are not in the D-025 baseline. Visibility filtering waits on A-15.

### Metadata filtering
- `DateRange(start, end)` is a channel-neutral frozen value object (`core/domain/models.py`); both bounds are `date | None` and inclusive. A both-`None` range is treated as no constraint; `start > end` is rejected at construction.
- Postgres adds a conditional `note_date >= / <=` predicate to both leg SQL queries; the mock backend applies the identical deterministic comparison, so mock and Postgres stay at parity. SQLite still raises `NotImplementedError`.
- `QueryService.answer` accepts a per-call `date_range` and threads it to both legs. There is no inbound `/ask` date syntax yet — that is a separate packet.

### Dense leg (Postgres)
- Exact community-scoped sequential scan over the canonical `vector(3072)` column.
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
- prefer diversity across dates — deferred (a retrieval-quality lever, not the D-040 date filter),
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

Ratified by **D-114** (Packet ED-0); decomposed in
`docs/EDIT-DELETE-ROADMAP.md`. The three previously-open axes are decided:

- **Edits create revisions, not in-place mutation.** An edited `/note` produces a
  new note/chunk revision that supersedes the prior one; the prior revision is
  retained (source lineage and I-6 authorship preserved) and marked inactive.
  This continues the source-layer revision model already in force (edited
  messages land as new `source_messages` rows keyed on `edit_seq`, R-2 / D-023).
- **Deletes tombstone, not hard-delete.** A delete tombstones the active revision
  (I-13 soft delete by default); hard deletion of source data stays an explicit,
  audited operation.
- **Re-embedding is triggered by the revision.** A new revision lands
  `embedding_status='pending'` (stage tracking, §ingestion) and is re-embedded by
  the existing pipeline; superseded and tombstoned chunks are excluded by the
  active-state filter (R-4) immediately, regardless of embedding state.

State model: `active | superseded | tombstoned`. **ED-1 (D-115) landed** the
encoding (a single `lifecycle_state` column on `notes` / `event_chunks`, CHECK +
DEFAULT `'active'`, with nullable `supersedes_*` lineage columns), the
retrieval-predicate change (both legs filter `lifecycle_state='active'`), and the
R-4 wording generalization. The `/edit` (supersession + re-embed) and `/delete`
(tombstone) mechanics land in the ED-2 / ED-3 code packets
(`docs/EDIT-DELETE-ROADMAP.md`); assumption A-10 is closed by D-114.

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
