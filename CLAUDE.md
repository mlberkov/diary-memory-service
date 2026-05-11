# CLAUDE.md

## Role

You are working inside a spec-first repository for a portable memory/journal core. The first use case is a Diary RAG Service that starts in Telegram and is designed for later integration into TheyGrow; the same core is intended to support additional hosts (self-hosted OSS, managed cloud, other embedded products) without rewrite (D-026).

Your job is not to improvise the product.
Your job is to implement and refine the repository in a way that stays consistent with canonical docs.

## Mandatory Read Order

Before making any significant change, read files in this order:

1. `AGENTS.md`
2. `docs/product/PRD.md`
3. `docs/product/BuildPlan.md`
4. `docs/product/TechSpec.md`
5. `docs/decision-log.md`

Then, if relevant to the task, read:

6. `docs/ARCHITECTURE.md`
7. `docs/INVARIANTS.md`
8. `docs/RUNTIME-INVARIANTS.md`
9. `docs/RUNBOOK.md`
10. `docs/execution-map.md`
11. `docs/assumptions.md`
12. `docs/assumption-audit.md`
13. `README.md`
14. `QUICKSTART.md`

Do not skip this read order for non-trivial work.

## Current Repository Stage

The repository is currently in:
- source-of-truth establishment mode,
- early implementation planning mode,
- thin-slice-first mode.

That means:
- prefer documents before code,
- prefer mock-before-real,
- prefer minimal end-to-end slices,
- prefer explicit interfaces over framework magic.

## What Must Be Preserved

You must preserve these architectural rules:

1. Telegram is one event-source adapter, not the system core (D-026).
2. The system core is a standalone, portable memory/journal core — currently surfaced as a Diary Memory Service.
3. PostgreSQL is the durable source of truth.
4. Raw source messages are persisted before enrichment.
5. Each diary event line becomes its own chunk.
6. Hybrid retrieval is a required capability.
7. Every answer must be grounded in retrieved evidence.
8. Shared diary mode must preserve authorship.
9. Optional AI enrichments are feature-flagged.
10. Host-specific types, provider SDKs, raw SQL, and use-case vocabulary (`family`, `child`, `parent`, "diary" as a type name) must not appear in newly added core code. Existing names persist until an explicit renaming packet (D-026).

## Implementation Style

### Prefer
- small, phase-appropriate changes,
- explicit contracts,
- inspectable data flow,
- simple code over framework-heavy abstractions,
- deterministic behavior,
- clear logging and observable failures.

### Avoid
- speculative abstraction,
- premature optimization,
- hidden orchestration,
- agentic complexity,
- undocumented assumptions,
- architecture drift from canonical docs.

## Framework Guidance

Default:
- implement core logic directly.

Allowed only as secondary tooling:
- helper libraries for HTTP, validation, testing, logging,
- optional utilities for evaluation or experiments.

Do not introduce as the foundation without explicit approval:
- LangGraph,
- complex chain frameworks,
- workflow engines,
- multi-agent orchestration.

## Task Execution Pattern

For any meaningful task, follow this order:

1. Restate the phase and goal internally.
2. Read canonical docs.
3. Identify the smallest viable change.
4. Classify the change along D-026 adapter axes: **core**, **adapter**, or **config**. If it crosses axes, name the seams touched.
5. Check whether the change requires doc updates.
6. Implement or edit.
7. Run the minimum relevant validation.
8. Summarize:
   - what changed,
   - what remains,
   - what assumptions were made,
   - what risks or open questions remain.

## Portability Rule

The functional core (ingestion, retrieval, answering, traces, domain model, invariants) is one consistent subsystem across all hosts (Telegram today, TheyGrow later, OSS / managed / embedded all first-class — D-026).

Do not add to core code:
- transport types or host identifiers,
- provider SDK imports,
- raw SQL or storage-engine specifics,
- use-case vocabulary (`family`, `child`, `parent`, "diary" as a type name) in newly added types or function names,
- assumptions that the runtime is HTTP-shaped, Telegram-shaped, single-tenant, internet-connected, or English-only.

Each of these belongs behind its adapter seam (event source, control surface, storage, provider, tenant mapping). Use-case-specific scope is carried as opaque identifiers, not encoded in core types. Existing names (`family_id`, `DiaryRepository`, `DiaryEntry`, the `diary_rag` package) persist until an explicit renaming packet.

## Documentation Rule

If code changes imply new behavior, and that behavior is not already reflected in canonical docs:
- update docs in the same task,
- or stop and surface the mismatch.

Do not let implementation silently outrun the docs.

## Assumption Rule

If an important decision is unclear:
- add it to `docs/assumptions.md`,
- mention it explicitly in the task summary,
- do not silently hard-code it as settled truth.

## Fallback Rule

When a fallback path exists:
- make requested path and effective path distinguishable,
- do not hide degraded behavior,
- preserve provenance in logs or result metadata.

## Current Expected Next Steps

Near-term expected tasks are:

1. stabilize repository docs,
2. align supporting docs with canonical product context,
3. create a thin Telegram shell,
4. implement mock ingestion and query flow,
5. then move to durable persistence,
6. then retrieval and grounded answering.

Do not jump directly to advanced AI or TheyGrow-wide integration.

## Output Preference

When finishing a task:
- be concrete,
- list touched files,
- mention validations run,
- mention assumptions,
- mention whether the result is mock, real, or mixed.

## Safety Against Drift

If a task request conflicts with:
- `AGENTS.md`,
- `docs/product/PRD.md`,
- `docs/product/BuildPlan.md`,
- `docs/product/TechSpec.md`,
- `docs/decision-log.md`,

then:
- do not silently comply,
- point out the mismatch,
- propose the smallest consistent resolution.

A request that would introduce host-specific behavior, transport types, provider SDKs, or use-case vocabulary into core code conflicts with D-026 even if no other doc names the specific case. Surface the conflict and propose the adapter/config seam that should carry the change instead.
