# Runtime Invariants

These must hold while the service is running. Violations are alerts, not warnings.

For the canonical `community` / `subject` vocabulary see `docs/GLOSSARY.md` and D-041. This file names the live code identifiers (`community_id`, `detected_route`, …) — its wording matches what code enforces today.

## R-1. Raw-before-enrichment ordering
Within a single inbound-message handler, the `SourceMessage` row is committed before any parse, chunk, embed, or index call is initiated.

## R-2. Idempotent ingest
Replaying the same channel message-state produces no new persisted state. The idempotency key is the triple `(external_chat_id, external_message_id, edit_seq)` (D-023); for Telegram, `edit_seq` is `0` for an original delivery and the `edit_date` epoch seconds for an edited state. Each backend enforces the key via DB-native conflict handling on `source_messages`; `DomainService.ingest` short-circuits parse and chunking on replay and returns the same functional `IngestResult`. Webhook retries are safe and observable: the log line records `effective_path=fresh|replay`.

## R-3. Community scoping on every read
Every retrieval call carries a non-null `community_id`. The retriever rejects calls without it. There is no admin path that bypasses scoping in MVP. The `community_id` a read is scoped to is produced by the adapter-axis chat→community mapping (D-093); this invariant governs the read, not how the id is assigned.

## R-4. Active-state filter on retrieval
Retrieval returns only chunks of the active revision — non-tombstoned **and** non-superseded — by default. Bypass requires an explicit, logged debug path.

The active state is the `lifecycle_state` column on `notes` / `event_chunks` (ED-1 / D-115, enforcing the D-114 edit/delete contract): both retrieval legs return only `lifecycle_state='active'` chunks, so `superseded` and `tombstoned` revisions are excluded **immediately**, regardless of `embedding_status` — a delete is effective before any re-embedding completes, and a superseded/tombstoned chunk is never re-embedded. The `/edit` supersession writer (ED-2) and `/delete` tombstone writer (ED-3) produce the non-active states; ED-1 lands the column and the predicate only.

The dense leg additionally requires `embedding_status='ready'` (D-025): chunks with `pending` or `failed` status do not participate in dense ranking. The sparse leg ranks any active chunk whose text yields tokens regardless of `embedding_status` — sparse is text-only and does not depend on a successful embedding. Every retrieval call logs `dense_n`, `sparse_n`, `merged_n` so an operator can confirm both legs ran.

## R-5. Provenance on every answer
No answer is returned to a user without an `AnswerTrace` row that records `context_chunk_ids` (possibly empty in fallback modes), `prompt_version`, and `fallback_mode`.

The retrieval-side half of this invariant is enforced as of Slice 3.5 (D-032): every `/ask` call writes one `Query` row and zero-or-more `RetrievalHit` rows (`leg ∈ {dense, sparse, merged}`, 1-based `rank`, RRF-contribution `score`).

Answer-side trace persistence is enforced on every `/ask` reply as of Slice 4.3b (D-035): one `AnswerTrace` row is written per call (FK to `queries.query_id`, UNIQUE on `query_id`) recording `prompt_version`, `context_chunk_ids`, `answer_text`, `model_name`, `token_counts`, `latency_ms`, and `fallback_mode`. `Query.fallback` and `AnswerTrace.fallback_mode` are written from one decision per call so they always agree. Slice 4.3a (D-034) landed the seam on the success and no-evidence/empty-query contours; Slice 4.3b extended it to weak-evidence, ambiguous, the LLM-marker `no_evidence` sub-branch, provider-unavailable, and parse-failure. Live provider integration remains deferred to Phase 6.

## R-6. Requested vs effective path
When a fallback is taken (no evidence, weak evidence, ambiguous query, provider unavailable, optional feature disabled), the response and the log distinguish the *requested* path from the *effective* path. No silent degradation.

Surface-level signaling is enforced as of Slice 4.3b (D-035) and tightened in Slice 4.4 (D-036): the dispatcher switches `_format_answer_reply` on `AnswerResult.fallback` and emits a distinct reply per mode. As of Slice 4.4 the reply body for the three answer-producing contours (`none`, `weak_evidence`, `ambiguous`) is `AnswerResult.answer_text` followed by the unchanged contour-specific trailer (`(hybrid retrieval — dense+sparse RRF)`, `(weak evidence — model expressed uncertainty)`, `(ambiguous question — refine and ask again)`). The non-answer contours keep their fixed replies: retry-hint strings on `provider_unavailable` and `parse_failure`; the two `no_evidence` sub-paths (empty retrieval vs LLM-marker over non-empty retrieval) remain disambiguated on `bool(AnswerResult.evidence)` and produce distinct reply strings — the LLM-marker reply deliberately does not surface the model's "no_evidence" prose. The `retrieval.hybrid` log line carries `fallback=…` so the effective path is also visible in logs. The cited chunks no longer appear in the default reply; `/sources` (D-036) exposes them on demand as the selected chunks as-is for the chat's most recent `/ask` turn.

Ratified as a named product guardrail in D-099: when `cited_chunk_ids` is empty, `/ask` returns an explicit technical no-evidence response and never surfaces free-form `answer_text` — the no-evidence contours proper return the technical no-evidence reply, while `provider_unavailable` / `parse_failure` are separate technical-failure contours that also carry an empty cited set and also surface no free-form `answer_text`. Cross-reference to existing behavior — no new R-number, no semantic change to R-6.

## R-7. Provider call observability
Every provider call (embedding, chat, search backend) is logged with: provider, model, input hash, latency, token counts (when available), and outcome class.

## R-8. No cross-community data in prompts
Prompt assembly never mixes chunks from more than one `community_id`. This is asserted in code, not just in policy. Multi-diary on one instance relies on this: many communities coexist in one deployment and each answer stays within a single `community_id` (D-093).

## R-9. Bounded provider behavior
Provider calls have explicit timeouts and bounded retries. There is no unbounded wait or unbounded retry loop in any handler.

Enforced for the OpenAI embedding and chat adapters as of Slice 6.1 (D-047): both build the SDK client with an explicit per-attempt timeout and `max_retries=0`, and every API call runs through the shared `adapters/resilience.py` bounded-retry loop. As of Slice 6.3 (D-049) a retryable failure is followed by an inter-attempt wait — exponential backoff with full jitter, or a server `Retry-After` when present — clamped to `provider_backoff_cap_seconds`. Worst-case bounded wall time for one provider call is `provider_timeout_seconds × provider_max_attempts + provider_backoff_cap_seconds × (provider_max_attempts − 1)`. Retry/timeout hardening for non-provider calls (Postgres, internal RPC) is not yet covered.

## R-10. Health gates on boot
Startup verifies the boot-time constraints that are load-bearing for the current phase. Failure aborts boot rather than serving partial functionality.

Phase 3.1+3.2 contour (D-024):
- `settings.embedding_dimension` must equal `3072` (the canonical pgvector column dimension).
- `settings.embedding_backend == "openai"` ⇒ `settings.embedding_model` must equal `text-embedding-3-large`; building `OpenAIEmbeddingClient` requires `OPENAI_API_KEY`.
- The configured `EmbeddingClient`'s reported `dimension` must agree with `settings.embedding_dimension`.
- `storage_backend == "postgres"` ⇒ the connected database must have the `vector` extension installed.

Slice 4.5 contour (D-037):
- The configured `ChatClient`'s reported `model_name` must be non-empty (D-034 clause, unchanged).
- `settings.chat_backend == "openai"` ⇒ `settings.chat_model` must equal `gpt-4.1`; building `OpenAIChatClient` requires `OPENAI_API_KEY`.

Full PostgreSQL connectivity, schema version, and provider reachability checks land with the migration packet.

## R-11. Routing is recorded
Every inbound message records its routing decision (`detected_route`) and whether it came from an explicit command or from heuristic classification. The persistence floor is the draft floor (D-027 / D-028 / R-13): raw is committed regardless of routing confidence, and per D-078 command-less plain text resolves only to the draft floor — heuristics no longer auto-route it to NOTE or ASK (those lifecycles are reached only via explicit `/note` / `/ask`). CLARIFY (D-020) remains valid as a user-facing response when an explicit command actively conflicts with intent, but it is not a plain-text route and never replaces raw persistence. (D-078 records this contract; D-079 enforces it in code — `classify_plain_text` routes command-less plain text only to the draft floor.)

## R-12. Feature flags are inspectable
The effective state of each optional-AI feature flag is loggable on demand and visible in the answer trace when relevant.

## R-13. No silent data loss in dispatch
No dispatch path discards raw text without persisting a `SourceMessage`. When no explicit command is given, the message is persisted as a draft (D-027 / D-028) and is **not** auto-promoted to NOTE or ASK by any heuristic (D-078) — those lifecycles are reached only via the explicit `/note` / `/ask` commands. The draft floor is unconditional and is not overridable by routing confidence. (D-078 records this contract; D-079 enforces it in code — `classify_plain_text` routes command-less plain text only to the draft floor.)

## R-14. Scoped raw export
Raw export honors the same scope as retrieval (R-3): no export call returns rows outside the requester's scope. Each export records its own provenance — export id, scope, time range, format, requester — so the operator can audit which raw was released to whom.
