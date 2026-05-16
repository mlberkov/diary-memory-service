# Operationalization Roadmap — Stage 2

## Purpose & status

This document is the detailed design artifact for **Stage 2 — Operationalization
/ real infrastructure binding** (D-043). It decomposes Stage 2 into an ordered,
refinable sequence of packet groups, `OP-1`..`OP-5`.

**Status: planned.** No `OP-` packet has been executed. This document records the
*recommended* sequence and the *fixed* ordering constraints; it is a refinable
design surface, not a record of completed work.

- **D-043** adopted the three-stage sequencing model and the operationalization
  gate, and named Stage 2's scope — Phase 6, Phase 7, the raw-data
  durability/backup slice of Phase 8, and resolution of A-34 — but explicitly
  deferred decomposing Stage 2 into concrete packets.
- **D-044** is that decomposition packet. It fixes — at contract level — the
  five packet groups, their execution order and ordering constraints, the
  per-group completion criteria (by reference), and the Stage-2 scope boundary,
  and points here for the detailed sequencing.

The D-044 decision packet that introduced this roadmap implemented nothing; the
operationalization work is carried out by the separate `OP-1`..`OP-5` packets.

This mirrors the D-042 / `docs/RENAMING-ROADMAP.md` precedent: the decision entry
carries the stable contract, the roadmap doc carries the refinable sequence.

---

## 1. Scope

Stage 2 = the five work items D-043 placed before the operationalization gate:

- **A-34** — schema-migration tooling (no migration tool wired; local schema
  upgrades are destructive).
- **Phase 6** — provider hardening (timeouts, bounded retries, error
  classification, rate-limit handling, dead-letter for failed indexing jobs).
- **A-35** — failed-embedding reconciliation (sticky `embedding_status='failed'`
  chunks; no auto-retry today).
- **Phase 8 raw-data durability/backup slice** — the daily backup window and
  stronger-than-nightly recovery primitive for raw `SourceMessage` data (D-027,
  A-40). **Stage 2 only.**
- **Phase 7** — evaluation and observability (gold eval set, retrieval &
  groundedness metrics, cost & latency).

### Explicitly out of scope

- **Stage-3 Phase 8 slices.** Phase 8 deliberately spans two stages (D-043).
  Only the raw-data durability/backup slice is Stage 2 and decomposed here as
  OP-4. The Stage-3 Phase 8 slices — community-scoped access control (8.1),
  the visibility model (8.2), export/delete (8.3), the audit log, and the
  retention policy — are **not** decomposed by D-044 and remain Stage 3, gated
  behind the operationalization gate.
- All other Stage-3 work — Phase 5 (optional AI quality boosters) and Phase 9
  (host integration seams).
- Implementation of any `OP-` packet. This roadmap sequences the work; it does
  not perform it.

---

## 2. Packet-group inventory

| Group | Source | Surfaces it touches |
| --- | --- | --- |
| **OP-1 — Schema-migration tooling** | A-34; D-043 Stage-2 exit clause "schema upgrades are non-destructive" | Introduce a migration tool (Alembic or equivalent); capture the current bootstrap DDL (`src/memory_rag/storage/postgres/schema.sql`) as the baseline migration; replace the destructive `docker compose down -v` upgrade contour with non-destructive, versioned upgrades. |
| **OP-2 — Provider hardening** | Phase 6 (BuildPlan slices 6.1 timeouts & retries, 6.2 dead-letter, 6.3 rate-limit handling) | Bounded retry policy and explicit timeouts on provider calls (R-9); error classification; a dead-letter surface for failed indexing jobs; rate-limit backoff and the matching observability. |
| **OP-3 — Failed-embedding reconciliation** | A-35 | A reconciliation job that retries `embedding_status='failed'` chunks with bounded backoff, routes exhausted retries to OP-2's dead-letter surface, and emits retry-outcome logs/metrics. |
| **OP-4 — Raw-data durability & backup** | Phase 8 raw-data durability/backup slice (Stage 2 only); D-027; A-40 | Daily backup window (target `03:00–05:00` local) covering at minimum `source_messages` plus enough relational scaffolding to restore `SourceMessage → Note → EventChunk` lineage; a stronger-than-nightly recovery primitive; the A-40 mechanism + RPO/RTO selection. |
| **OP-5 — Evaluation & observability** | Phase 7 (BuildPlan slices 7.1 gold eval set, 7.2 retrieval & groundedness metrics, 7.3 cost & latency) | A curated gold eval set (extending the D-038 retrieval harness); retrieval hit-rate / empty-rate / groundedness metrics; parse-success metrics; indexing latency; cost & token aggregation; regression visibility. |

---

## 3. Recommended implementation roadmap

Execution order: **OP-1 → OP-2 → OP-3 → (OP-4 ‖) → OP-5.** OP-4 may run
concurrently with OP-2/OP-3 once OP-1 is merged.

| Packet | Group | Preconditions | Exit criterion (by reference) | Validation |
| --- | --- | --- | --- | --- |
| **OP-1** | Schema-migration tooling | D-044 merged. None on Phase 6/7 behavior — OP-1 leads Stage 2. | A-34 resolved: schema upgrades are non-destructive (D-043 Stage-2→3 exit clause; A-34 in `docs/assumptions.md`). | A fresh-environment bootstrap and an upgrade from the prior schema both succeed without a destructive volume reset. |
| **OP-2** | Provider hardening | OP-1 merged (the dead-letter surface adds persistent state and rides OP-1's non-destructive upgrades). | Phase 6 Definition of Done (`docs/product/BuildPlan.md` "Phase 6 — Provider Hardening"): provider failures do not corrupt durable state; retries are bounded and visible; fallback behavior is explicit and logged. | `make check`; provider-failure paths exercised with bounded retries and an inspectable dead-letter surface. |
| **OP-3** | Failed-embedding reconciliation | OP-1 and OP-2 merged — OP-3 consumes OP-2's bounded-backoff retry (6.1) and dead-letter (6.2) primitives, per A-35's own specification. | A-35 resolved (`docs/assumptions.md`), governed by the same Phase 6 Definition of Done. | `make check`; a `failed` chunk is retried, succeeds or lands in the dead-letter surface, and the outcome is observable. |
| **OP-4** | Raw-data durability & backup | OP-1 merged (recovery restores into a schema-versioned database). Independent of OP-2/OP-3 — may run in parallel. | Phase 8 raw-data durability Definition of Done (`docs/product/BuildPlan.md` "Phase 8"): raw is recoverable from at least the prior nightly window plus a tighter recovery point than nightly-only (D-027); A-40 mechanism + RPO/RTO selected. | A restore drill recovers raw `SourceMessage` data from the backup window and from the stronger-than-nightly primitive. |
| **OP-5** | Evaluation & observability | OP-2 merged so quality is measured against hardened infrastructure. The gold-eval-set work (7.1) extends the D-038 harness and may begin in parallel with OP-2; the group as a whole closes Stage 2. | Phase 7 Definition of Done (`docs/product/BuildPlan.md` "Phase 7 — Evaluation and Observability"): quality is measurable; regressions are visible; rollout decisions can rely on metrics. | `make check`; the eval harness produces retrieval/groundedness/cost metrics and surfaces a regression against a recorded baseline. |

**Refinability rule.** Implementation-time planning may split or merge these
packet groups — for example, splitting OP-2 along its 6.1/6.2/6.3 slices — as
long as every resulting packet preserves **both**:

1. the D-044 OP-group ordering constraints in §4 (OP-1 ≺ {OP-2, OP-3, OP-4};
   OP-2 ≺ OP-3; OP-5 closes Stage 2), and
2. the D-043 Stage-2 → Stage-3 operationalization gate — no Stage-3 packet
   starts until all of OP-1..OP-5 are complete.

A change that cannot preserve both must instead amend D-044 with a new decision.

---

## 4. Dependency graph & ordering rationale

```
OP-1 ──▶ OP-2 ──▶ OP-3 ──▶ OP-5
  │                         ▲
  └────────▶ OP-4 ──────────┘   (OP-4 ‖ OP-2/OP-3)
```

- **OP-1 first.** OP-2's dead-letter surface and OP-3's reconciliation both add
  persistent schema. Under A-34 every such change is a destructive volume reset,
  which is unacceptable as the first non-local deployment approaches. OP-1 has
  no dependency on Phase 6/7 behavior, so it leads. This is the one hard
  ordering constraint that touches every other group.
- **OP-2 ≺ OP-3.** A-35 specifies reconciliation uses "bounded backoff and a
  dead-letter strategy". Bounded backoff is OP-2's 6.1 retry primitive; the
  dead-letter surface is OP-2's 6.2 deliverable. OP-3 must consume them, not
  re-invent them.
- **OP-1 ≺ OP-4; OP-4 independent of OP-2/OP-3.** Backup and recovery are
  orthogonal to provider behavior; OP-4's only hard dependency is restoring into
  a schema-versioned database. It therefore follows OP-1 but may run
  concurrently with OP-2/OP-3.
- **OP-5 closes Stage 2.** Measuring retry/fallback cost (7.3) and groundedness
  before provider hardening exists measures a moving target. The gold-eval-set
  work (7.1) extends the already-shipped D-038 retrieval harness and may begin
  in parallel with OP-2, but the group as a whole closes last so the "quality is
  measurable" exit criterion is judged against hardened infrastructure.
- **OP-2 ↔ OP-5 cross-cut.** OP-2's "retries bounded and visible / fallback
  explicit and logged" emits the structured signals OP-5's 7.3 cost & latency
  aggregation consumes. Recording this here avoids an instrument-before-observe
  trap.

---

## 5. Exit criteria → Stage-2 gate mapping

D-043's operationalization gate — "no Stage-3 packet may start until the Stage-2
exit criteria are met" — decomposes precisely into:

| D-043 Stage-2 → 3 exit clause | Satisfied by |
| --- | --- |
| Provider failures do not corrupt durable state; retries/fallbacks bounded and observable (Phase 6 DoD) | OP-2 |
| Schema upgrades are non-destructive (A-34 resolved with migration tooling) | OP-1 |
| Raw `SourceMessage` data has a backup window + stronger-than-nightly recovery primitive (Phase 8 durability DoD, D-027) | OP-4 |
| Retrieval and answer quality are measurable, regressions visible (Phase 7 DoD) | OP-5 |
| (A-35 sticky failed embeddings — implied by "provider failures do not corrupt durable state") | OP-3 |

Stage 2 is complete — and the operationalization gate opens — when **all of
OP-1..OP-5** are done. No Stage-3 Phase 8 slice, Phase 5 slice, or Phase 9 slice
may start before then.

---

## See also

- D-027, D-043, D-044 in `docs/decision-log.md`.
- `docs/product/BuildPlan.md` — "Development Sequencing" and the Phase 6 / 7 / 8
  Definitions of Done referenced above.
- `docs/execution-map.md` — Phase 6 / 7 / 8 slice rows tagged with `OP-` IDs.
- `docs/RENAMING-ROADMAP.md` — the structurally analogous D-042 roadmap doc.
- A-34, A-35, A-40 in `docs/assumptions.md` / `docs/assumption-audit.md`.
