# Read-Access Enforcement Roadmap — Slice 8.1

## Purpose & status

This document is the refinable-sequence companion to **D-087** (Packet 8.1.0). It
decomposes execution-map **Slice 8.1 — community-scoped read-access enforcement
(cross-community leakage prevention)** into an ordered set of bounded packets and
carries the as-built audit of the read surface against **I-7 / R-3 / R-8**.

**Status: Packet 8.1.0 landed (D-087) — audit + decomposition (docs-only).**
The hot `/ask` read path is already community-scoped and tested; the remaining
packets (8.1.1 / 8.1.2 / 8.1.3) harden the latent by-id/trace read seams so the
no-cross-community-leakage property holds by construction rather than by current
call-graph accident.

This mirrors the D-060 / `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` and D-044 /
`docs/OPERATIONALIZATION-ROADMAP.md` precedent: the decision entry (**D-087**)
carries the stable contract; this doc carries the refinable sequence and the
audit. **D-087 stays authoritative** for the enforcement contract; this doc
mirrors it so it reads alongside the sequence, but does not re-decide it.

---

## 1. Scope

Slice 8.1 = **read-access enforcement**: every read of a community-owned record
either carries a non-null `community_id` and filters by the owning community, or
is documented as a seam closed by a named packet below. The milestone exit
property is the Phase-8 DoD lines "cross-community leakage is prevented" and
"access behavior is explicit" (`docs/product/BuildPlan.md`).

### Explicitly out of scope

- The **visibility model** / per-note scopes — Slice 8.2, blocked on **A-15**.
- **Export / delete / audit / retention** — Slice 8.3.
- **Community-bootstrap reassignment** — the per-chat `external_chat_id →
  community_id` mapping (**A-14**) stays as-is; this milestone scopes *reads*, not
  how a community id is assigned.
- Any **schema / DDL / migration** change, including adding a `community_id`
  column to `answer_traces` (D-087 omits it — community is recoverable via the
  `query_id → queries.community_id` join).
- **D-026–D-042 rename** work.

---

## 2. As-built read-path audit (mirrored from D-087)

Predicates are described by clause, not line number, so the audit stays true as
code moves. "Scoped today?" = takes a mandatory `community_id` and filters by it.

| Read method | Scoped today? | Backend filter (mock / sqlite / postgres) | Call sites | Verdict |
| --- | --- | --- | --- | --- |
| `SearchRepository.dense_candidates` | **Yes** | mock: skip non-matching community / sqlite: `NotImplementedError` / postgres: `WHERE ec.community_id = …` + null-guard | live `/ask` (`QueryService.answer`); eval harness | enforced (R-3) |
| `SearchRepository.sparse_candidates` | **Yes** | mock: skip non-matching community / sqlite: `NotImplementedError` / postgres: `WHERE ec.community_id = …` + null-guard | live `/ask`; eval harness | enforced (R-3) |
| `list_source_messages` | **Yes** | all backends filter `community_id` + null-guard | `/export` (operator) | enforced |
| `list_recent_drafts` | **Yes** | all backends filter `community_id` + null-guard | live `/drafts` | enforced |
| `list_failed_event_chunks` | **Yes** | all backends filter `community_id` + null-guard | reconciliation CLI (operator) | enforced |
| `get_query` | **No** | keyed by `query_id` only, no community filter | **unused** (tests only) | latent gap → **8.1.1** |
| `get_retrieval_hits_for_query` | **No** | keyed by `query_id` only, no community filter | **unused** (tests only) | latent gap → **8.1.1** |
| `get_answer_trace_for_query` | **No** | keyed by `query_id` only, no community filter (row has no `community_id`) | **unused** (tests only) | latent gap → **8.1.1** (scope via `queries` join) |
| `get_event_chunk` | **No** | keyed by `chunk_id` only, no community filter | **unused** (tests only) | latent gap → **8.1.1** |
| `get_source_message` | **No** | keyed by `source_message_id` only, no community filter | **live path**: `/sources` author resolution (`author_display.resolve_chunk_author_display`), over an already-scoped chunk | live-path seam → **8.1.2** |
| `_latest_sources` cache (`services/dispatcher.py`) | safe by construction | keyed by `community_id` | live `/sources` | characterization test → **8.1.2** |
| prompt assembly (`build_answer_prompt`) | **Yes** | asserts single `community_id`, raises `CrossCommunityContextError` | live `/ask` | enforced (R-8) |

Already-present isolation tests: `test_cross_chat_isolation`, the
`test_*_scope_isolates` pair (mock + postgres), `test_missing_community_id_raises`,
`test_raises_on_cross_community_chunks`.

---

## 3. Enforcement contract (D-087)

Cannot change without a new decision packet:

- **Null-`community_id` rejection.** A scoped read rejects a null/empty
  `community_id` with the standard `ValueError` guard used by the enforced reads
  today (fail-closed, no log-and-continue, no admin bypass — R-3).
- **Filter by the owning community.** A scoped read filters by the owning
  community **via the appropriate predicate or join for that record's storage
  shape**: a record carrying `community_id` directly filters on its own column; a
  trace record whose community lives on the parent `queries` row filters via a
  `query_id → queries.community_id` join. The exact per-method predicate-vs-join
  choice is left to the implementing packet — this contract does not over-specify
  storage.
- **No `answer_traces` schema change.** Community stays recoverable through the
  existing `query_id → queries.community_id` join; the milestone is read-only and
  adds no column / DDL / migration.
- **`get_source_message` is a live-path seam.** It is sequenced into 8.1.2, not
  8.1.1 — completing 8.1.1 does **not** close all latent/read seams.

---

## 4. Packet sequence (refinable)

Names, granularity, and ordering between independent packets are refinable when
each packet is planned, as long as every resulting packet preserves the §3
contract.

| Packet | Surfaces it touches | Status |
| --- | --- | --- |
| **8.1.0 — audit + decomposition** | `docs/decision-log.md` (D-087); this roadmap doc (new); `docs/execution-map.md`; `docs/todo.md`. Docs-only — no `src/` / `tests/` / schema change. | **Landed (D-087).** |
| **8.1.1 — defensive scoping of unused by-id/trace reads** | Add a mandatory `community_id` + null-guard + owning-community filter to `get_query`, `get_retrieval_hits_for_query`, `get_answer_trace_for_query`, `get_event_chunk` across the `DomainRepository` Protocol + mock / sqlite / postgres backends (`get_answer_trace_for_query` / `get_retrieval_hits_for_query` scope via the `queries` join; `get_event_chunk` filters its own `community_id`); update the test-only call sites; add guard + cross-community isolation tests. No live `/ask` behavior change, no schema change. **Does not close `get_source_message` / `/sources` — see 8.1.2.** | **Pending.** |
| **8.1.2 — `get_source_message` scoping + `/sources` isolation** | Thread `community_id` through `get_source_message` (Protocol + all backends) and through the live `/sources` author-resolution path (`adapters/telegram/author_display.py`); add cross-community characterization tests for `/sources` block rendering and the `community_id`-keyed `_latest_sources` cache. No schema change. | **Pending.** |
| **8.1.3 — milestone closure / verification** | Consolidated cross-community isolation test sweep across every scoped read; a `docs/RUNBOOK.md` operator note on read-access scoping; execution-map + todo closure; DoD evidence that "cross-community leakage is prevented" / "access behavior is explicit". | **Pending.** |

---

## 5. Dependencies & ordering rationale

```
8.1.0 (D-087, docs) ──▶ 8.1.1 (unused reads) ──▶ 8.1.2 (get_source_message + /sources) ──▶ 8.1.3 (closure / verification)
```

- **8.1.0 first** — the contract + audit must be recorded before any `src/`
  edit, per the docs-first convention (D-060 / D-044 precedent).
- **8.1.1 before 8.1.2** — the unused by-id/trace reads are pure defense-in-depth
  (no live caller), so they carry zero behavior risk and establish the
  mandatory-`community_id` + join pattern that 8.1.2 reuses on the live
  `get_source_message` seam.
- **8.1.2 is the only packet touching a live read path** — it is isolated so the
  `/sources` author-resolution change ships with its own characterization tests.
- **8.1.3 last** — closure depends on every prior scoped read existing.

---

## 6. Exit criterion

Slice 8.1 exits when every read of a community-owned record either carries a
non-null `community_id` and filters by the owning community, or is a documented
safe-by-construction seam with a characterization test; the consolidated
isolation sweep is green; the RUNBOOK records the read-access scoping contract;
and the Phase-8 DoD lines "cross-community leakage is prevented" and "access
behavior is explicit" are satisfied for the read surface. (Visibility — Slice 8.2
— and export/delete/audit/retention — Slice 8.3 — are separate slices and not
part of this exit criterion.)

---

## See also

- **D-087** in `docs/decision-log.md` — the authoritative decision entry for the
  Slice 8.1 enforcement contract, audit, and packet ladder.
- **I-7** in `docs/INVARIANTS.md` — community scoping (every record outside
  `SourceMessage` carries `community_id`; no retrieval crosses communities).
- **R-3** and **R-8** in `docs/RUNTIME-INVARIANTS.md` — community scoping on every
  read; no cross-community data in prompts.
- **A-14** (per-chat community assignment) and **A-15** (visibility, deferred to
  Slice 8.2), both open, in `docs/assumptions.md` / `docs/assumption-audit.md`.
- `docs/OPERATIONALIZATION-ROADMAP.md` and
  `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` — the structurally analogous roadmap
  docs and the "decision entry carries the contract, roadmap doc carries the
  refinable sequence" precedent.
- `docs/execution-map.md` — the Phase-8 Slice 8.1 row pointing here.
- `docs/todo.md` — the Slice 8.1 backlog section.
