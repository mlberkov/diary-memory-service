# Invariants

These hold at all times. Code that breaks any of them must not be merged. Changing one of them requires a new entry in `docs/decision-log.md`.

Derived from `AGENTS.md` §Non-Negotiable Product Rules and `docs/product/TechSpec.md` §14.

For the canonical `community` / `subject` vocabulary see `docs/GLOSSARY.md` and D-041. This file names the live code identifiers (`community_id`, `Note`, …) — its wording matches what code enforces today.

## I-1. Channel boundary
Telegram is a channel, not the system of record. No Telegram-specific type or assumption may appear outside the channel adapter layer.

## I-2. Source of truth
PostgreSQL is the durable system of record. Embeddings, indexes, and provider responses are derived state and must be reproducible from PostgreSQL data.

## I-3. Raw before enrichment
Every inbound diary message is persisted as a `SourceMessage` before any enrichment (parsing, chunking, embedding, indexing). No enrichment step may run if raw persistence has not committed.

## I-4. Lineage preserved
Every `EventChunk` references its `Note` and `SourceMessage`. Lineage from chunk → note → source → channel message is never lost.

## I-5. One explicit `/note` is one chunk
Each explicit `/note` payload becomes exactly one `EventChunk`, even when the payload contains newline characters. Newlines inside a `/note` are content structure (a multi-line dialogue or transcript), not event separators, and never split the note across chunks. Per-line splitting is retired for explicit `/note` (D-106, which supersedes the per-line half of D-005). Any future batch or multi-event capture is a separate explicit command or separator contract, not a reinstatement of per-line splitting inside `/note`.

## I-6. Authorship
`author_user_id` is mandatory at `SourceMessage`, `Note`, and `EventChunk`. Shared diary mode never erases authorship. `author_user_id` is an opaque core identifier; human-readable author display names are resolved only at the host adapter seam and are non-authoritative presentation, never a substitute for it (D-081; `docs/assumptions.md` A-44). Capturing and persisting those display inputs is likewise adapter/storage-owned and adds no core authorship field (D-082); they land in a separate adapter-owned side table via an adapter-owned storage port distinct from the core repository, never entering a core type or core function signature (D-083). Resolved display names are surfaced only on `/sources` (D-086); the `/ask`-reply `Contributors:` footer that once also surfaced them (D-091 / D-092) was removed in D-101, with no change to this invariant — the core still carries authorship only as the opaque `author_user_id`. Grouped-diary membership inherited from host-chat membership (D-093) preserves each sender's distinct opaque `author_user_id` and adds no core authorship field.

## I-7. Community scoping
Every persisted record outside `SourceMessage` carries `community_id`. No retrieval may cross communities. The `community_id` itself is assigned by the adapter-axis chat→community mapping — implicit-on-first-message bootstrap, default Telegram 1:1 from `external_chat_id` — and many communities may coexist on one instance; how a community is bootstrapped and mapped is recorded in D-093 (and `docs/GROUPED-MULTI-DIARY-ROADMAP.md`), not changed by this invariant.

## I-8. Hybrid retrieval
The retrieval contract supports both dense and sparse signals. A retrieval backend that cannot deliver hybrid retrieval is not acceptable. Enforced as of D-025: `SearchRepository.dense_candidates` (exact community-scoped scan over `vector(3072)`) and `sparse_candidates` (Postgres FTS `tsvector('simple')`) are independently produced and fused by service-layer Reciprocal Rank Fusion.

## I-9. Grounded answers
Every answer references the chunks used as evidence (`AnswerTrace.context_chunk_ids`). An answer with no retrieved evidence must use an explicit `fallback_mode`, not a fabricated response.

Retrieval-side trace persistence is enforced as of Slice 3.5 (D-032): every `/ask` call writes a `Query` row plus zero-or-more `RetrievalHit` rows carrying `leg ∈ {dense, sparse, merged}` so the chunks each leg saw and the chunks that survived RRF are inspectable via plain SQL.

Citation grounding is enforced in code as of Slice 4.2 (D-033): `parse_structured_answer` (in `src/memory_rag/core/domain/answer_schema.py`) requires `StructuredAnswer.cited_chunk_ids` to be a subset of the `chunk_id`s in the `AnswerContext` that built the prompt; fabricated citations raise `FabricatedCitationError`. Empty `cited_chunk_ids` is permitted only when `uncertainty == "no_evidence"`; `"uncertain"` and `"ambiguous"` therefore require non-empty citations (Slice 4.3b, D-035).

Answer-side trace persistence is enforced on every `/ask` reply as of Slice 4.3b (D-035): one `AnswerTrace` row is written per call (FK to `queries.query_id`, UNIQUE on `query_id`) recording `prompt_version`, `context_chunk_ids`, `answer_text`, `model_name`, `token_counts`, `latency_ms`, and `fallback_mode`. `Query.fallback` and `AnswerTrace.fallback_mode` are written from one decision per call so they always agree. Slice 4.3a (D-034) landed the seam on the success and no-evidence/empty-query contours; Slice 4.3b extended it to weak-evidence, ambiguous, the LLM-marker `no_evidence` sub-branch, provider-unavailable, and parse-failure. Live provider integration remains deferred to Phase 6.

Ratified as a named product guardrail in D-099: when `cited_chunk_ids` is empty, `/ask` returns an explicit technical no-evidence response and never surfaces free-form `answer_text` (cited-empty reading only; semantic-groundedness of present citations is a separate Phase 7 concern). This is a cross-reference to existing behavior — no new invariant, no semantic change to I-9.

Generalized for routed answers in D-108 (routed-chat milestone): every answer segment carries an explicit provenance class — **notes** (cited through the existing cited-only evidence surface; this clause changes nothing for the notes-grounded class, whose contract above stands verbatim), **web** (cited URLs), or **model** (explicitly labeled as model knowledge). No segment may present model- or web-sourced content as if it came from the diary. Ratified docs-first; enforced in code by the routed-chat packets RC-2..RC-4 (`docs/ROUTED-CHAT-ROADMAP.md`) — until then the only live answer surface is the notes-grounded `/ask` flow above.

## I-10. Optional AI is optional
Query rewriting, semantic expansion, reranking, and answer-style modes are feature-flagged. The base ingestion → retrieval → answer flow must work end-to-end with all enhancements disabled.

## I-11. Provider isolation
External providers (LLM, embeddings, search backend) are accessed through explicit adapters. Domain code does not import provider SDKs directly.

## I-12. Replayability
Parsing and chunking are deterministic for a given `parse_version`. Re-running parse + chunk + embed on the same `SourceMessage` produces the same logical state, not duplicates.

## I-13. Soft delete by default
Deletes default to tombstones. Hard deletion of source data requires an explicit, audited operation. (Specific edit/delete mechanics are open — see `docs/assumptions.md` A-10.)

## I-14. No silent data loss
Absence of an explicit command never causes silent discard, downgrade, or upgrade of raw persistence. Drafts are the safety floor (D-027 / D-028) and, per D-078, the only route for command-less plain text: heuristics do not auto-route plain text to NOTE or ASK — those lifecycles are reached only via the explicit `/note` / `/ask` commands. CLARIFY (D-020) remains valid only as a response when an explicit command actively conflicts with intent, not as a plain-text route and not as the persistence floor. (D-078 records this contract; D-079 enforces it in code — `classify_plain_text` routes command-less plain text only to the draft floor.)

## I-15. Raw durability and export
Raw `SourceMessage` is the highest-tier durability surface. Operational policy requires a daily backup window plus a stronger-than-nightly recovery primitive; the user can export their raw data on demand in JSON or TXT, scope-bounded (D-027). Derived state is reproducible from raw under the active parser/embedding versions.
