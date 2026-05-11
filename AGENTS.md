# AGENTS.md

## Purpose

This repository follows a spec-first, harness-friendly workflow.

Agents must treat repository documents as the primary source of truth.
Do not infer core product behavior from partial prompts when the relevant repository documents already exist.

## Repository Mode

This repository is currently in:
- Phase 0 / early Phase 1 setup,
- documentation-first mode,
- source-of-truth establishment mode.

That means:
- docs come before implementation,
- read-before-edit is mandatory,
- assumptions must be surfaced explicitly,
- no silent architectural invention is allowed.

## Canonical Source of Truth

The primary canonical files are:

1. `docs/product/PRD.md`
2. `docs/product/BuildPlan.md`
3. `docs/product/TechSpec.md`
4. `docs/decision-log.md`

Supporting operational context:
5. `docs/ARCHITECTURE.md`
6. `docs/INVARIANTS.md`
7. `docs/RUNTIME-INVARIANTS.md`
8. `docs/RUNBOOK.md`
9. `docs/execution-map.md`
10. `docs/assumptions.md`
11. `docs/assumption-audit.md`

If any prompt conflicts with these files:
- prefer the canonical repository documents,
- do not silently resolve the conflict in code,
- record the conflict and ask for clarification if the change is material.

## Product Context

This project is a portable memory/journal core. The first use case is a Diary RAG Service that:
- starts as a Telegram-based diary and Q&A interface,
- later integrates into TheyGrow as a reusable memory subsystem,
- is intended to support additional hosts (self-hosted OSS, managed cloud, other embedded products) without rewrite.

Core architectural rule (D-026):
- The functional core is the same subsystem across hosts.
- Telegram is one event-source adapter; TheyGrow is one future host. Neither is the product core.
- The parents / family-diary framing is the first use case of the core, not its definition.

Core service rule:
- the main system is a standalone Diary Memory Service exposed through host-specific adapters.

## Non-Negotiable Product Rules

1. Raw source messages must be preserved before enrichment.
2. PostgreSQL is the primary durable system of record.
3. Each diary event line becomes a separate chunk.
4. Answers must be grounded in retrieved evidence.
5. Hybrid retrieval is required.
6. Explicit `/note` and `/ask` commands are preferred over heuristic-only routing.
7. Telegram-specific logic must not leak into the core domain model.
8. Optional AI enrichments must be feature-flagged.
9. No silent fallback may pretend that retrieval succeeded.
10. Shared diary mode must preserve authorship.
11. Host-specific types, provider SDKs, raw SQL, and use-case vocabulary (`family`, `child`, `parent`, "diary" as a type name) must not appear in newly added core code. Existing names persist until an explicit renaming packet (D-026).

## Working Rules for Agents

### Read-before-edit
Before making any non-trivial change, read at minimum:
- `CLAUDE.md`
- `AGENTS.md`
- `docs/product/PRD.md`
- `docs/product/BuildPlan.md`
- `docs/product/TechSpec.md`
- `docs/decision-log.md`

### Do not invent architecture
Do not introduce:
- extra subsystems,
- framework-heavy abstractions,
- agentic workflows,
- background jobs,
- data models,
- external dependencies,
unless they are justified by the canonical docs or explicitly approved.

### Smallest viable slice
Prefer the smallest end-to-end slice that proves the current phase goal.

Do not jump ahead from:
- docs setup -> production-grade infra,
- Telegram shell -> full TheyGrow integration,
- base RAG -> advanced agent orchestration.

### Classify every packet
Every packet description must classify its changes along the adapter axes (D-026). State for each touched area whether it is:
- **core** (functional core: ingestion, retrieval, answering, traces, domain model, invariants),
- **adapter** (event source, control surface, storage, providers, tenant/auth mapping),
- **config** (settings, env, feature flags, deployment wiring).

Changes that cross axes name the seams they touch. A "core" change that imports a provider SDK, references a transport type, or hard-codes use-case vocabulary in a new type is a leak, not a core change.

### Explicit assumptions
If something important is underspecified:
- write it into `docs/assumptions.md`,
- do not bury the assumption inside code,
- do not pretend the choice is already approved.

### Fallback provenance
When designing or implementing fallbacks:
- distinguish requested path from effective path,
- make fallback behavior inspectable,
- avoid hidden degradation.

### Framework policy
Default approach:
- implement core flows from scratch.

Allowed:
- optional and isolated use of helper libraries.

Not allowed as architectural foundation without explicit approval:
- LangGraph,
- framework-owned domain orchestration,
- opaque hidden chains.

## Change Policy

Use a two-step mindset:
1. align docs and decisions,
2. then change implementation.

If a requested code change implies a spec change:
- update the relevant docs first or alongside the code,
- do not leave the repo in a state where code contradicts canonical docs.

## Documentation Expectations

When touching docs:
- keep them concise and operational,
- avoid placeholder fluff,
- prefer explicit rules over vague aspirations,
- keep naming consistent with existing canonical files.

## Commit Expectations

Commits should be:
- small,
- phase-aligned,
- readable,
- easy to review.

Prefer commit messages such as:
- `docs: add canonical product context for diary rag service`
- `docs: add agent operating rules and claude read order`
- `feat: add telegram entry routing shell`
- `feat: persist raw source messages before chunking`

## Current Priority

Current priority is:
- establish stable repository source of truth,
- complete repo operating rules,
- only then proceed to controlled implementation of the first thin slice.
