# Runtime Invariants

These must hold while the service is running. Violations are alerts, not warnings.

## R-1. Raw-before-enrichment ordering
Within a single inbound-message handler, the `SourceMessage` row is committed before any parse, chunk, embed, or index call is initiated.

## R-2. Idempotent ingest
Replaying the same channel message-state produces no new persisted state. The idempotency key is the triple `(external_chat_id, external_message_id, edit_seq)` (D-023); for Telegram, `edit_seq` is `0` for an original delivery and the `edit_date` epoch seconds for an edited state. Each backend enforces the key via DB-native conflict handling on `source_messages`; `DiaryService.ingest` short-circuits parse and chunking on replay and returns the same functional `IngestResult`. Webhook retries are safe and observable: the log line records `effective_path=fresh|replay`.

## R-3. Family scoping on every read
Every retrieval call carries a non-null `family_id`. The retriever rejects calls without it. There is no admin path that bypasses scoping in MVP.

## R-4. Active-state filter on retrieval
Retrieval returns only chunks of non-tombstoned entries by default. Bypass requires an explicit, logged debug path.

The dense leg additionally requires `embedding_status='ready'` (D-025): chunks with `pending` or `failed` status do not participate in dense ranking. The sparse leg ranks any chunk whose text yields tokens regardless of `embedding_status` — sparse is text-only and does not depend on a successful embedding. Every retrieval call logs `dense_n`, `sparse_n`, `merged_n` so an operator can confirm both legs ran.

## R-5. Provenance on every answer
No answer is returned to a user without an `AnswerTrace` row that records `context_chunk_ids` (possibly empty in fallback modes), `prompt_version`, and `fallback_mode`.

The retrieval-side half of this invariant is enforced as of Slice 3.5 (D-032): every `/ask` call writes one `Query` row and zero-or-more `RetrievalHit` rows (`leg ∈ {dense, sparse, merged}`, 1-based `rank`, RRF-contribution `score`). Answer-side `AnswerTrace` persistence (prompt version, model name, generated text) remains deferred to Phase 4 and lands with its own table.

## R-6. Requested vs effective path
When a fallback is taken (no evidence, weak evidence, ambiguous query, provider unavailable, optional feature disabled), the response and the log distinguish the *requested* path from the *effective* path. No silent degradation.

## R-7. Provider call observability
Every provider call (embedding, chat, search backend) is logged with: provider, model, input hash, latency, token counts (when available), and outcome class.

## R-8. No cross-family data in prompts
Prompt assembly never mixes chunks from more than one `family_id`. This is asserted in code, not just in policy.

## R-9. Bounded provider behavior
Provider calls have explicit timeouts and bounded retries. There is no unbounded wait or unbounded retry loop in any handler.

## R-10. Health gates on boot
Startup verifies the boot-time constraints that are load-bearing for the current phase. Failure aborts boot rather than serving partial functionality.

Phase 3.1+3.2 contour (D-024):
- `settings.embedding_dimension` must equal `3072` (the canonical pgvector column dimension).
- `settings.embedding_backend == "openai"` ⇒ `settings.embedding_model` must equal `text-embedding-3-large`; building `OpenAIEmbeddingClient` requires `OPENAI_API_KEY`.
- The configured `EmbeddingClient`'s reported `dimension` must agree with `settings.embedding_dimension`.
- `storage_backend == "postgres"` ⇒ the connected database must have the `vector` extension installed.

Full PostgreSQL connectivity, schema version, and provider reachability checks land with the migration packet.

## R-11. Routing is recorded
Every inbound message records its routing decision (`detected_route`) and whether it came from an explicit command or from heuristic routing. The persistence floor is the draft floor (D-027 / R-13): raw is committed regardless of routing confidence. CLARIFY (D-020) remains valid as a user-facing response when a heuristic actively conflicts with intent, but it never replaces raw persistence.

## R-12. Feature flags are inspectable
The effective state of each optional-AI feature flag is loggable on demand and visible in the answer trace when relevant.

## R-13. No silent data loss in dispatch
No dispatch path discards raw text without persisting a `SourceMessage`. When no explicit command is given, the message is persisted as a draft (D-027). Implementations may layer heuristics on top to suggest a stronger route, but the draft floor is unconditional and is not overridable by routing confidence.

## R-14. Scoped raw export
Raw export honors the same scope as retrieval (R-3): no export call returns rows outside the requester's scope. Each export records its own provenance — export id, scope, time range, format, requester — so the operator can audit which raw was released to whom.
