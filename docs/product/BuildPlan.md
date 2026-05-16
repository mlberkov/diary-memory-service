# Build Plan — Shared-Memory Core / Note-Grounded Answer Service

*First implemented use case: a Telegram family/child diary. Later integration host: TheyGrow (D-041).*

## Status
Draft v1

## Goal

Build a **generic shared-memory / note-grounded answer service** — a portable memory/journal core that captures notes into a durable corpus and answers natural-language questions grounded in retrieved evidence, serving both individual-memory (solo) and shared/group corpora under one core model. It is surfaced first as a Diary Memory Service that starts with Telegram and is later integrated into TheyGrow. The same core is intended to support additional hosts (self-hosted OSS, managed cloud, other embedded products) without rewrite (D-026, D-041). The family/child diary is the first **implemented** use case, not the definition of the system; `community` (the outer scope owning a corpus, one or more participants) and `subject` (a sub-entity within a community) are the canonical core vocabulary (D-041).

Target-state shape (D-027) — bound here so future slices stay consistent, not scheduled as their own phases yet:
- Draft-by-default safety: explicit `/note`, `/ask`, `/drafts` commands; absence of command defaults to draft so no inbound message is silently discarded. The explicit `/draft` command was removed in D-030 — drafts are created only by the no-command default and recalled via `/drafts`.
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

## Development Sequencing

Development runs in three stages (D-043). The stage is the unit of execution
order; the Phase numbers below are documentation identifiers, **not** the order
of work. Where a Phase number and the stage map disagree — Phase 5 is numbered
before Phases 6–8 but executes after them — the stage map is the order of record.

- **Stage 1 — Product baseline.** The end-to-end note → retrieve →
  grounded-answer product works. Phases 0–4.
- **Stage 2 — Operationalization / real infrastructure binding.** Provider
  integrations are production-safe, schema evolution is non-destructive, raw
  data is durable and recoverable, and quality is measurable. Phase 6, Phase 7,
  the raw-data durability/backup slices of Phase 8, and resolution of A-34
  (schema-migration tooling).
- **Stage 3 — Quality improvement / expansion.** Phase 5, the
  access-control / visibility / audit / retention slices of Phase 8, and Phase 9.

**Operationalization gate:** no Stage-3 packet may start until the Stage-2 exit
criteria are met. Phase 8 deliberately spans Stage 2 and Stage 3; the slice-level
split is recorded in `docs/execution-map.md`. The Stage-2 work is decomposed into
ordered packet groups `OP-1`..`OP-5` in `docs/OPERATIONALIZATION-ROADMAP.md`
(D-044).

**Exit criteria.**
- *Stage 1 → 2:* the Phase 4 Definition of Done holds.
- *Stage 2 → 3:* provider failures do not corrupt durable state and
  retries/fallbacks are bounded and observable (Phase 6 DoD); schema upgrades
  are non-destructive (A-34 resolved); raw `SourceMessage` data has a backup
  window and a stronger-than-nightly recovery primitive (Phase 8 durability DoD,
  D-027); retrieval and answer quality are measurable (Phase 7 DoD).

This three-stage model is a coarse outer layer. It does not replace the
fine-grained baseline-vs-quality discipline (D-038 / D-039), which still governs
packet-level work within a stage — including retrieval-tuning packets inside
Phase 3, which remain Stage 1.

## Phase 0 — Operating Setup *(Stage 1 — Product baseline)*

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

## Phase 1 — Telegram Shell and Mock Flow *(Stage 1 — Product baseline)*

### Goal
Validate the UX and routing model without real providers.

### Build
- Telegram webhook receiver,
- `/start`, `/help`, `/note`, `/ask`,
- basic date parser,
- line splitter,
- mock persistence,
- mock retrieval,
- mock answer generation,
- end-to-end smoke run.

### Definition of Done
- one note flow works,
- one query flow works,
- logs show the full lifecycle,
- no real external AI provider required yet.

## Phase 2 — Durable Backend Core *(Stage 1 — Product baseline)*

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
- data model covers source → note → chunk lineage.

## Phase 3 — Embeddings and Hybrid Retrieval *(Stage 1 — Product baseline)*

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
- filtering by community/author/date scope works,
- retrieval traces are inspectable.

## Phase 4 — Grounded Answer Pipeline *(Stage 1 — Product baseline)*

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

## Phase 5 — Optional AI Quality Boosters *(Stage 3 — Quality / Expansion; gated on Stage-2 exit)*

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

## Phase 6 — Provider Hardening *(Stage 2 — Operationalization)*

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

## Phase 7 — Evaluation and Observability *(Stage 2 — Operationalization)*

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

## Phase 8 — Privacy, Durability, and Shared-Memory Controls *(spans stages: raw-data durability/backup is Stage 2; access control, visibility, audit, retention are Stage 3)*

### Goal
Add product trust baseline: scope safety, raw data durability, and user-visible export.

### Build
- community-scoped access control,
- authorship preservation,
- visibility model,
- raw export on demand in JSON or TXT (D-027),
- audit log for sensitive operations,
- retention policy,
- daily backup window (`03:00–05:00` target) and stronger-than-nightly recovery for raw data (D-027) — mechanism per deployment shape.

### Definition of Done
- cross-community leakage is prevented,
- access behavior is explicit,
- sensitive operations are traceable,
- users can export their raw data on demand in either format,
- raw is recoverable from at least the prior nightly window plus a tighter recovery point than nightly-only.

## Phase 9 — Host Integration Seams *(Stage 3 — Quality / Expansion; gated on Stage-2 exit)*

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
