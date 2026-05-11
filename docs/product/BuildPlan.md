# Build Plan — Diary RAG Service for TheyGrow

## Status
Draft v1

## Goal

Build a portable memory/journal core, surfaced first as a Diary Memory Service that starts with Telegram and is later integrated into TheyGrow. The same core is intended to support additional hosts (self-hosted OSS, managed cloud, other embedded products) without rewrite (D-026). The family-diary framing is the first use case, not the definition of the system.

Target-state shape (D-027) — bound here so future slices stay consistent, not scheduled as their own phases yet:
- Draft-by-default safety: explicit `/note`, `/draft`, `/ask` commands; absence of command defaults to draft so no inbound message is silently discarded.
- Raw-data durability with a daily backup window (`03:00–05:00` target) and stronger-than-nightly recovery.
- Raw export on demand in JSON or TXT.
- Managed cloud as the default reference deployment shape, with self-hosted OSS and embedded (TheyGrow) as peer shapes.

## Build Strategy

The implementation follows a spec-first, harness-friendly path:
- source of truth docs first,
- repo operating setup first,
- mock-before-real,
- smallest viable end-to-end slice,
- explicit runtime contracts,
- observable fallbacks.

## Phase 0 — Operating Setup

### Goal
Create the repository baseline and canonical product documents before implementation.

### Deliverables
- `README.md`
- `QUICKSTART.md`
- `docs/product/PRD.md`
- `docs/product/BuildPlan.md`
- `docs/product/TechSpec.md`
- `docs/ARCHITECTURE.md`
- `docs/INVARIANTS.md`
- `docs/RUNTIME-INVARIANTS.md`
- `docs/CHECKLIST.md`
- `docs/RUNBOOK.md`
- `docs/decision-log.md`
- `docs/todo.md`
- `docs/execution-map.md`
- `docs/assumptions.md`
- `docs/assumption-audit.md`
- `AGENTS.md`
- `CLAUDE.md`
- `.env.example`
- `.gitignore`
- `Makefile`

### Definition of Done
- canonical product context exists in repo,
- read-before-edit workflow is documented,
- scaffold is committed,
- no implementation begins before source of truth exists.

## Phase 1 — Telegram Shell and Mock Flow

### Goal
Validate the UX and routing model without real providers.

### Build
- Telegram webhook receiver,
- `/start`, `/help`, `/entry`, `/ask`,
- basic date parser,
- line splitter,
- mock persistence,
- mock retrieval,
- mock answer generation,
- end-to-end smoke run.

### Definition of Done
- one entry flow works,
- one query flow works,
- logs show the full lifecycle,
- no real external AI provider required yet.

## Phase 2 — Durable Backend Core

### Goal
Replace mocks with durable persistence and replayable ingestion.

### Build
- PostgreSQL schema,
- repositories for core entities,
- idempotent webhook handling,
- parser versioning,
- edit/delete handling strategy,
- stage status tracking.

### Definition of Done
- raw source message is saved first,
- parse/chunk steps are replayable,
- data model covers source → entry → chunk lineage.

## Phase 3 — Embeddings and Hybrid Retrieval

### Goal
Make diary memory searchable.

### Build
- embedding adapter,
- indexing queue or async job,
- pluggable retrieval backend,
- hybrid search,
- metadata filtering,
- retrieval traces,
- initial ranking policy.

### Definition of Done
- new chunks become searchable,
- hybrid retrieval works on real data,
- filtering by family/author/date scope works,
- retrieval traces are inspectable.

## Phase 4 — Grounded Answer Pipeline

### Goal
Produce stable, evidence-based answers before advanced enrichments.

### Build
- context assembler,
- answer prompt contract,
- answer schema,
- no-result fallback,
- weak-evidence fallback,
- ambiguity fallback,
- evidence rendering for Telegram replies.

### Definition of Done
- questions are answered from retrieved memory,
- answers degrade gracefully when evidence is weak,
- no answer is produced without retrieval output.

## Phase 5 — Optional AI Quality Boosters

### Goal
Add quality improvements behind feature flags.

### Build
- query rewriting,
- semantic expansion,
- reranking,
- answer style modes,
- timeline answer mode,
- analytical synthesis mode.

### Definition of Done
- optional features are independently switchable,
- requested vs effective execution path is logged,
- base RAG flow still works when all boosters are disabled.

## Phase 6 — Provider Hardening

### Goal
Make external provider integrations production-safe enough for MVP use.

### Build
- OpenAI provider hardening,
- timeout policies,
- bounded retries,
- error classification,
- rate-limit handling,
- dead-letter strategy for failed indexing jobs.

### Definition of Done
- provider failures do not corrupt durable state,
- retries are bounded and visible,
- fallback behavior is explicit and logged.

## Phase 7 — Evaluation and Observability

### Goal
Measure whether the system is actually improving.

### Build
- small gold eval set,
- retrieval hit-rate evaluation,
- groundedness checks,
- parse success metrics,
- indexing latency,
- empty retrieval rate,
- answer acceptance signal,
- cost tracking.

### Definition of Done
- quality is measurable,
- regressions are visible,
- rollout decisions can rely on metrics rather than intuition.

## Phase 8 — Privacy, Durability, and Shared-Memory Controls

### Goal
Add product trust baseline: scope safety, raw data durability, and user-visible export.

### Build
- family-scoped access control,
- authorship preservation,
- visibility model,
- raw export on demand in JSON or TXT (D-027),
- audit log for sensitive operations,
- retention policy,
- daily backup window (`03:00–05:00` target) and stronger-than-nightly recovery for raw data (D-027) — mechanism per deployment shape.

### Definition of Done
- cross-family leakage is prevented,
- access behavior is explicit,
- sensitive operations are traceable,
- users can export their raw data on demand in either format,
- raw is recoverable from at least the prior nightly window plus a tighter recovery point than nightly-only.

## Phase 9 — Host Integration Seams

### Goal
Make integration into other hosts cheap. TheyGrow is the named first-class case; self-hosted OSS, managed cloud, and other embedded hosts are peer shapes (D-026, D-027).

### Build
- internal API or SDK,
- stable domain boundaries,
- tenant/scope identity mapping (current: family/child; per-host mapping isolated in the adapter layer),
- downstream integration hooks,
- Telegram-specific logic isolated in adapter layer.

### Definition of Done
- a non-Telegram client can consume the same service,
- migration into TheyGrow is an integration task, not a rewrite,
- self-hosted OSS and managed cloud shapes share the same core configuration.
