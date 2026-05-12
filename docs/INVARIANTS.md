# Invariants

These hold at all times. Code that breaks any of them must not be merged. Changing one of them requires a new entry in `docs/decision-log.md`.

Derived from `AGENTS.md` §Non-Negotiable Product Rules and `docs/product/TechSpec.md` §14.

## I-1. Channel boundary
Telegram is a channel, not the system of record. No Telegram-specific type or assumption may appear outside the channel adapter layer.

## I-2. Source of truth
PostgreSQL is the durable system of record. Embeddings, indexes, and provider responses are derived state and must be reproducible from PostgreSQL data.

## I-3. Raw before enrichment
Every inbound diary message is persisted as a `SourceMessage` before any enrichment (parsing, chunking, embedding, indexing). No enrichment step may run if raw persistence has not committed.

## I-4. Lineage preserved
Every `EventChunk` references its `DiaryEntry` and `SourceMessage`. Lineage from chunk → entry → source → channel message is never lost.

## I-5. Event-per-chunk
Each diary event line becomes exactly one `EventChunk`. Multiple events do not share a chunk; one event does not split across chunks.

## I-6. Authorship
`author_user_id` is mandatory at `SourceMessage`, `DiaryEntry`, and `EventChunk`. Shared diary mode never erases authorship.

## I-7. Family scoping
Every persisted record outside `SourceMessage` carries `family_id`. No retrieval may cross families.

## I-8. Hybrid retrieval
The retrieval contract supports both dense and sparse signals. A retrieval backend that cannot deliver hybrid retrieval is not acceptable. Enforced as of D-025: `SearchRepository.dense_candidates` (exact family-scoped scan over `vector(3072)`) and `sparse_candidates` (Postgres FTS `tsvector('simple')`) are independently produced and fused by service-layer Reciprocal Rank Fusion.

## I-9. Grounded answers
Every answer references the chunks used as evidence (`AnswerTrace.context_chunk_ids`). An answer with no retrieved evidence must use an explicit `fallback_mode`, not a fabricated response.

Retrieval-side trace persistence is enforced as of Slice 3.5 (D-032): every `/ask` call writes a `Query` row plus zero-or-more `RetrievalHit` rows carrying `leg ∈ {dense, sparse, merged}` so the chunks each leg saw and the chunks that survived RRF are inspectable via plain SQL. Answer-side `AnswerTrace` persistence remains deferred to Phase 4.

Citation grounding is enforced in code as of Slice 4.2 (D-033): `parse_structured_answer` (in `src/diary_rag/core/diary/answer_schema.py`) requires `StructuredAnswer.cited_chunk_ids` to be a subset of the `chunk_id`s in the `AnswerContext` that built the prompt; fabricated citations raise `FabricatedCitationError`. Empty `cited_chunk_ids` is permitted only when `uncertainty == "no_evidence"`. Live LLM invocation and `AnswerTrace` persistence remain deferred.

## I-10. Optional AI is optional
Query rewriting, semantic expansion, reranking, and answer-style modes are feature-flagged. The base ingestion → retrieval → answer flow must work end-to-end with all enhancements disabled.

## I-11. Provider isolation
External providers (LLM, embeddings, search backend) are accessed through explicit adapters. Domain code does not import provider SDKs directly.

## I-12. Replayability
Parsing and chunking are deterministic for a given `parse_version`. Re-running parse + chunk + embed on the same `SourceMessage` produces the same logical state, not duplicates.

## I-13. Soft delete by default
Deletes default to tombstones. Hard deletion of source data requires an explicit, audited operation. (Specific edit/delete mechanics are open — see `docs/assumptions.md` A-10.)

## I-14. No silent data loss
Absence of an explicit command never causes silent discard or downgrade of raw persistence. Drafts are the safety floor (D-027); CLARIFY (D-020) remains valid only as a response when a heuristic actively conflicts with intent, not as the persistence floor.

## I-15. Raw durability and export
Raw `SourceMessage` is the highest-tier durability surface. Operational policy requires a daily backup window plus a stronger-than-nightly recovery primitive; the user can export their raw data on demand in JSON or TXT, scope-bounded (D-027). Derived state is reproducible from raw under the active parser/embedding versions.
