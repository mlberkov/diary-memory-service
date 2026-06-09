# Subject-Scoping Roadmap

## Purpose & status

This document is the refinable-sequence companion to **D-097** (Packet H-0). It
decomposes the **subject-scoping** milestone — adding an opaque, community-scoped
`subject_id` dimension to the existing community-scoped data plane — into an
ordered set of bounded packets and carries the as-built audit of the subject
surface against **D-026 (adapter axes)**, **D-041 (community / subject
vocabulary)**, and **I-7 / R-3 / R-8** (community scoping stays the outer
boundary).

**Status: in progress — Packets H-0 (D-097, docs), H-1 (data model), and H-2
(adapter-axis assignment) landed; H-3..H-4 pending.** `subject_id` now exists as a
nullable, opaque field on `Note` / `EventChunk` and in the durable schema (H-1), and
host→subject assignment is a single adapter-owned seam (H-2). Under the default
single-subject mapping the seam assigns `null` (community-wide), so every record is
still community-wide today; the retrieval path (H-3) does not exist yet. H-0 ratifies the
contract (an opaque / community-scoped / **nullable** `subject_id` on `Note` /
`EventChunk`; assignment is an adapter-axis function with a default single-subject
mapping; `null` = community-wide; **no** core subject registry/entity; an
optional retrieval filter mirroring the D-040 `date_range` seam; orthogonal to
A-15 visibility). The remaining packets put `subject_id` in the data model (H-1),
make assignment a single adapter-owned seam (H-2), add the optional retrieval
filter (H-3), and pin + document the behavior and close the milestone (H-4).

This mirrors the **D-093 / `docs/GROUPED-MULTI-DIARY-ROADMAP.md`**, **D-087 /
`docs/READ-ACCESS-ENFORCEMENT-ROADMAP.md`**, and **D-044 /
`docs/OPERATIONALIZATION-ROADMAP.md`** precedent: the decision entry (**D-097**)
carries the stable contract; this doc carries the refinable sequence and the
audit. **D-097 stays authoritative** for the contract; this doc mirrors it so it
reads alongside the sequence, but does not re-decide it.

---

## 1. Scope

This milestone = **add a subject-scoping dimension** to the existing
community-scoped data plane: pin that subject scope is carried as an opaque,
community-subordinate, nullable `subject_id`; put it on the subject-bearing core
records; make host→subject assignment a single adapter-owned seam with a default
single-subject mapping; and offer subject-scoped retrieval as an **optional**
filter — **without** adding a core subject registry/entity, an explicit
subject-selection command, or any visibility model, and **without** reopening
Milestone G.

### Explicitly out of scope

- The **visibility model** / per-note scopes — **A-15**, separate and orthogonal
  (subject = *what a note is about*; visibility = *who may see it*). A-15 stays
  open and sequenced (Slice 8.2 / G-4); no packet below advances, enumerates, or
  depends on it.
- A **core `Subject` / subject-registry / membership / per-subject-ACL entity** —
  `subject_id` is an opaque scalar exactly as `community_id` is; a registry is
  deferred until assignment must diverge from the default single-subject mapping
  (e.g. multiple named subjects per community).
- An explicit **subject-selection command** / multi-subject UX — not built; no
  packet below may depend on it (parallel to D-093's `/setup`-deferred clause).
- **Reopening or re-deciding the D-093 / Milestone G** community-bootstrap
  contract — community scoping (I-7 / R-3 / R-8) is the unchanged outer boundary.
- The **date-range filter** (D-040) — already landed; the H-3 subject filter
  composes with it but does not modify it.
- *(For H-0 specifically)* any **schema / DDL / migration / `src/`** change.

---

## 2. As-built audit (mirrored from D-097)

Predicates are described by clause, not line number, so the audit stays true as
code moves.

| Surface | As-built today | Verdict |
| --- | --- | --- |
| Subject scope on records | **present** — nullable, opaque `subject_id` on `Note` / `EventChunk` + durable schema (H-1); `null` = community-wide, so unpopulated until H-2 | landed — H-1 |
| Subject assignment | **present** — single adapter-owned `resolve_subject_id` seam carried on `InboundMessage` → `Note` / `EventChunk` (H-2); default single-subject mapping assigns `null` (community-wide) | landed — H-2 |
| Subject retrieval filter | **absent** — only the D-040 `date_range` keyword-only filter exists on the search legs | gap — added by H-3 (optional, mirrors D-040) |
| Subject registry / entity | **absent** (and intentionally so) | intentional — no entity this milestone |
| Community scoping | every record `community_id`-keyed; every read scoped + fail-closed (I-7 / R-3 / R-8; Slice 8.1; D-094) | unchanged outer boundary |
| A-15 visibility | community-level scoping is the access model; per-note visibility deferred | unchanged — separate from this milestone |

---

## 3. Ratified contract (D-097)

Cannot change without a new decision packet:

- **`subject_id` is opaque, community-scoped, and nullable.** It is carried on
  the subject-bearing core records (`Note`, `EventChunk`), born directly as
  `subject_id` (canonical vocabulary, D-041); `child` / `child_id` stay
  use-case-facing labels, never a core field name. It is **subordinate to
  `community_id`** and never widens or crosses community scope.
- **`null` = community-wide.** A `null` `subject_id` is the access model that
  exists today; subject scoping is additive and optional and does not retro-scope
  existing records.
- **Assignment is an adapter-axis function** (D-026 axis 5), parallel to the
  chat→community resolver. The default first-use-case mapping is **single-subject
  per community** (behavior-preserving). The core receives an opaque `subject_id`
  (or `null`) and never derives subject from a host identity field (I-1). No
  packet depends on an explicit subject-selection command existing first.
- **No core subject registry/entity.** `subject_id` is an opaque scalar; a
  registry is deferred until assignment must diverge from the default mapping.
- **Retrieval is an optional keyword-only filter** (`Query.subject_scope`,
  default `None` = no constraint), mirroring the D-040 `date_range` seam and
  composing with it.
- **Separate from A-15 visibility** — orthogonal; not advanced by this milestone.
- **No `src/` claim of a `subject_id` field/column/filter until H-1 makes it
  true.** D-097 ratifies the contract over an absent surface; the code is
  sequenced, not assumed.

---

## 4. Packet sequence (refinable)

Names, granularity, and ordering between independent packets are refinable when
each packet is planned, as long as every resulting packet preserves the §3
contract. C = core, A = adapter, Cfg = config (D-026 classification).

| Packet | Surfaces it touches | Class | Status |
| --- | --- | --- | --- |
| **H-0 — subject-scoping contract + A-45 resolution + roadmap** | `docs/decision-log.md` (D-097); this roadmap doc (new); `docs/assumptions.md` + `docs/assumption-audit.md` (close A-45 → D-097; A-15 clarified, stays open); `docs/execution-map.md` (Milestone H block); cross-ref-only touches to `docs/product/TechSpec.md` §5, `docs/GLOSSARY.md`, `docs/RUNBOOK.md`. Docs-only — no `src/` / `tests/` / schema change. | docs-only | **Landed (D-097).** |
| **H-1 — `subject_id` in the data model** | Add a nullable, opaque `subject_id` to `Note` / `EventChunk` (`core/domain/models.py`) + a non-destructive migration (nullable column, default `null`; community scoping unchanged). No assignment, no retrieval change yet. | **C** (+ schema) | Landed (H-1; `0005.subject-id-columns` migration). |
| **H-2 — adapter-axis subject assignment** | One adapter-owned host→subject mapping (default single-subject per community, parallel to `adapters/telegram/community.py` `resolve_community_id`); the resolved opaque `subject_id` crosses the boundary on `InboundMessage`; the domain service carries it through to `Note` / `EventChunk`. Behavior-preserving under the default mapping. | **A** (+ core call sites) | Landed (H-2; `adapters/telegram/subject.py` `resolve_subject_id`, default `None`). |
| **H-3 — optional subject retrieval filter** | `Query.subject_scope` + a keyword-only optional subject filter on `storage/search_repository.py` both legs (and the postgres/mock stores), mirroring the D-040 `date_range` seam; `None` = no constraint (preserves the current shape + RRF inputs); composes with `date_range`. | **C** | Pending. |
| **H-4 — regression suite + operator/product docs + closure** | Subject-scoping characterization suite (mock + PG-gated parity); reconcile `docs/RUNBOOK.md` / `docs/product/TechSpec.md` §5 / `docs/ARCHITECTURE.md`; flip this roadmap `Status:` / §6 / the execution-map rows to milestone-closed (conditional on this packet landing). | tests + docs | Pending. |

*(A-15 visibility is **not** an H packet — it stays Slice 8.2 / G-4, separate.)*

---

## 5. Dependencies & ordering rationale

```
H-0 (D-097, docs) ──▶ H-1 (subject_id in the model) ──▶ H-2 (adapter-axis assignment) ──▶ H-3 (optional retrieval filter) ──▶ H-4 (tests + docs + closure)   [A-15 visibility: separate, Slice 8.2 / G-4]
```

- **H-0 first** — the contract + audit must be recorded before any `src/` edit
  (D-093 / D-060 / D-044 / D-087 docs-first convention).
- **H-1 before H-2** — the field must exist before assignment can populate it.
- **H-2 before H-3** — a filter is only meaningful once notes/chunks can carry a
  non-`null` `subject_id`; until then the optional filter is a no-op seam.
- **H-3 before H-4** — the operator/product docs and the regression suite describe
  behavior the retrieval filter has just made real.
- **A-15 separate** — per-note/per-participant visibility is orthogonal to subject
  scoping; it is sequenced after the first grouped pilot (Slice 8.2 / G-4) and
  does not block H-1..H-4.

---

## 6. Exit criterion

The milestone exits when `subject_id` is in the `Note` / `EventChunk` data model
(H-1), host→subject assignment is a single adapter-owned seam with a default
single-subject mapping (H-2), subject-scoped retrieval is an optional keyword-only
filter that composes with the D-040 date filter (H-3), and a regression suite +
operator/product docs pin and record the behavior (H-4) — all while preserving the
§3 contract and the existing community-scoping invariants (I-7 / R-3 / R-8). **H-1
and H-2 have landed** (`subject_id` in the `Note` / `EventChunk` data model + durable
schema; host→subject assignment a single adapter-owned seam with a default
single-subject mapping); H-3..H-4 remain, so the milestone is still in progress. The
visibility model (A-15 / Slice 8.2 / G-4) and any core subject registry/entity are
separate and **not** part of this exit criterion — they remain outside the
milestone.

---

## See also

- **D-097** in `docs/decision-log.md` — the authoritative decision entry for the
  subject-scoping contract, the A-45 resolution, and this packet ladder.
- **D-093** in `docs/decision-log.md` and `docs/GROUPED-MULTI-DIARY-ROADMAP.md` —
  the community-bootstrap contract that carved out A-45 (the origin of this
  milestone) and the structurally analogous roadmap.
- **D-040** in `docs/decision-log.md` — the date-range retrieval-filter seam the
  H-3 subject filter mirrors and composes with.
- **D-026** in `docs/decision-log.md` and `docs/ARCHITECTURE.md` — the five
  adapter axes; axis 5 (tenant/auth mapping): "the mapping function is adapter;
  the scoped query is core".
- **D-041** in `docs/decision-log.md` and `docs/GLOSSARY.md` — the canonical
  `community` / `subject` / `participant` vocabulary (`child → subject`).
- **I-1 / I-6 / I-7** in `docs/INVARIANTS.md` and **R-3 / R-8** in
  `docs/RUNTIME-INVARIANTS.md` — channel boundary, authorship, community scoping
  (the unchanged outer boundary).
- **A-45** (closed → D-097, subject bootstrap/assignment contract) and **A-15**
  (visibility, separate, open → Slice 8.2 / G-4) in `docs/assumptions.md` /
  `docs/assumption-audit.md`.
- `docs/READ-ACCESS-ENFORCEMENT-ROADMAP.md`, `docs/OPERATIONALIZATION-ROADMAP.md`,
  `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` — the structurally analogous roadmap
  docs and the "decision entry carries the contract, roadmap doc carries the
  refinable sequence" precedent.
- `docs/execution-map.md` — the Milestone H block pointing here.
