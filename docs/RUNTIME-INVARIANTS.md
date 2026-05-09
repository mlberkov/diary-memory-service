# Runtime Invariants

These must hold while the service is running. Violations are alerts, not warnings.

## R-1. Raw-before-enrichment ordering
Within a single inbound-message handler, the `SourceMessage` row is committed before any parse, chunk, embed, or index call is initiated.

## R-2. Idempotent ingest
Replaying the same channel update (same channel id, message id, and edit sequence) produces no new state. Webhook retries are safe.

## R-3. Family scoping on every read
Every retrieval call carries a non-null `family_id`. The retriever rejects calls without it. There is no admin path that bypasses scoping in MVP.

## R-4. Active-state filter on retrieval
Retrieval returns only chunks of non-tombstoned entries by default. Bypass requires an explicit, logged debug path.

## R-5. Provenance on every answer
No answer is returned to a user without an `AnswerTrace` row that records `context_chunk_ids` (possibly empty in fallback modes), `prompt_version`, and `fallback_mode`.

## R-6. Requested vs effective path
When a fallback is taken (no evidence, weak evidence, ambiguous query, provider unavailable, optional feature disabled), the response and the log distinguish the *requested* path from the *effective* path. No silent degradation.

## R-7. Provider call observability
Every provider call (embedding, chat, search backend) is logged with: provider, model, input hash, latency, token counts (when available), and outcome class.

## R-8. No cross-family data in prompts
Prompt assembly never mixes chunks from more than one `family_id`. This is asserted in code, not just in policy.

## R-9. Bounded provider behavior
Provider calls have explicit timeouts and bounded retries. There is no unbounded wait or unbounded retry loop in any handler.

## R-10. Health gates on boot
Startup verifies PostgreSQL connectivity, schema version, and the configured embedding model dimension. Failure aborts boot rather than serving partial functionality.

## R-11. Routing is recorded
Every inbound message records its routing decision (`detected_route`) and whether it came from an explicit command or from heuristic routing. Low-confidence routing asks for clarification rather than guessing.

## R-12. Feature flags are inspectable
The effective state of each optional-AI feature flag is loggable on demand and visible in the answer trace when relevant.
