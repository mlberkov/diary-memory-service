# Backlog

Top of list = pick next. Each item maps to a row in `docs/execution-map.md`. When a slice is done, remove it and add the next downstream slice.

## Slice 0.2 — Supporting docs baseline (in review)
- Owner: agent → human reviewer
- Map: execution-map 0.2
- Outcome: `README.md`, `QUICKSTART.md`, all `docs/*.md` populated; assumptions surfaced; mismatches reported.
- Done when: human reviewer signs off; high-priority assumptions (A-1, A-4, A-10, A-11, A-14) have an owner and a target phase confirmed.

## Slice 0.3 — Resolve Phase-0 blockers
- Owner: human
- Map: execution-map 0.3 (and assumption audit)
- Outcome: pre-Phase-1 assumptions promoted to decision log:
  - A-1 implementation language
  - A-2 dependency manager
  - A-3 test/format/type toolchain
  - A-4 Telegram transport for dev vs prod
- Done when: each item has a D-### entry, or is explicitly deferred with a target phase.

## Slice 1.1 — Language & toolchain
- Owner: agent
- Map: execution-map 1.1
- Outcome: project skeleton in chosen language; real `make init`, `make check`, `make test`, `make format` targets; empty test suite passes.
- Done when: `make check` is green on a fresh clone; CI plan documented in `docs/RUNBOOK.md`.

---

When 0.2 ships, the next three become 0.3 → 1.1 → 1.2 (Telegram adapter shell). Slices beyond 1.2 are visible in `docs/execution-map.md`; do not promote them here until the upstream slice is in flight.
