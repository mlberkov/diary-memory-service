# Checklists

## Pre-implementation (before any new slice)
- [ ] Read `AGENTS.md`, `CLAUDE.md`, and the canonical docs for the slice's phase.
- [ ] Confirm the slice maps to a row in `docs/execution-map.md` and the top of `docs/todo.md`.
- [ ] Re-read `docs/INVARIANTS.md` and `docs/RUNTIME-INVARIANTS.md`; identify which IDs the slice touches.
- [ ] List every assumption the slice depends on. Each must already exist in `docs/assumptions.md` (resolved or open) — add any missing ones first.
- [ ] Write the slice plan: goal, files, contracts, observable behavior, test surface, fallback paths.
- [ ] Confirm the slice respects mock-before-real where applicable.

## Pre-merge (every change)
- [ ] No invariant broken; new invariants added to `docs/INVARIANTS.md` or `docs/RUNTIME-INVARIANTS.md` if introduced.
- [ ] No new assumption left undocumented; resolved assumptions promoted to `docs/decision-log.md` (next D-### id).
- [ ] No Telegram-specific code outside the Telegram adapter (I-1).
- [ ] No retrieval call without `family_id` (R-3).
- [ ] No enrichment path that runs before raw persistence commits (I-3, R-1).
- [ ] No provider call outside the adapter wrapper (I-11, R-7).
- [ ] Optional AI enhancements remain feature-flagged and inspectable (I-10, R-6, R-12).
- [ ] Tests cover happy path and at least one fallback or failure path.
- [ ] Decision log updated for any non-trivial decision.
- [ ] `docs/todo.md` updated; completed items removed, follow-ups added.
- [ ] `docs/execution-map.md` reflects new files if any were introduced.
- [ ] Commit messages are phase-aligned (see `AGENTS.md` §Commit Expectations).

## Pre-deploy (Phase 6+)
- [ ] Provider timeouts, retries, and dead-letter strategy verified under failure injection.
- [ ] Backup/restore drill executed against current schema.
- [ ] Eval harness re-run; no regression beyond agreed threshold (see Phase 7).
- [ ] Runbook reflects current state (commands, observability, recovery).
- [ ] Rollback plan written and reviewed.
