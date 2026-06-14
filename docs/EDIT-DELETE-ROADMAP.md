# Edit/Delete Roadmap

## Purpose & status

This document is the refinable-sequence companion to **D-114** (Packet ED-0). It
decomposes the **edit/delete** milestone — the contract for what happens when a
captured `/note` is edited or deleted — into an ordered set of bounded packets,
and carries the as-built audit of the surfaces the milestone builds on.

**Status: contract ratified (ED-0 / D-114, docs-first); ED-1 landed (D-115);
ED-2 landed (D-116); code packets ED-3..ED-n open.** ED-0 closes assumption
**A-10** at the contract level and resolves TechSpec §12. ED-1 landed the
persisted `lifecycle_state` state model + nullable `supersedes_*` lineage
columns, generalized the active-state retrieval predicate, and landed the R-4
wording. ED-2 wired the `/edit` supersession writer: a parsed note edit
supersedes the prior active revision (lineage recorded, prior flipped to
`superseded`, new revision re-embedded). The `/delete` tombstone writer (ED-3)
is the only remaining non-active transition.

This mirrors the **D-108 / `docs/ROUTED-CHAT-ROADMAP.md`**, **D-097 /
`docs/SUBJECT-SCOPING-ROADMAP.md`**, **D-093 /
`docs/GROUPED-MULTI-DIARY-ROADMAP.md`**, and **D-044 /
`docs/OPERATIONALIZATION-ROADMAP.md`** precedent: the decision entry (**D-114**)
carries the stable contract; this doc carries the refinable sequence and the
audit. **D-114 stays authoritative** for the contract; this doc mirrors it so it
reads alongside the sequence, but does not re-decide it.

---

## 1. Scope

This milestone = **define and implement what happens to a captured `/note` when
its source message is edited or deleted**, end-to-end: source → note/chunk
revision → retrieval visibility → re-embedding. The contract (D-114) is:

- **Supersession (revisions), not in-place mutation** — an edited `/note`
  produces a new note/chunk revision that supersedes the prior one; the prior
  revision is retained (source lineage + I-6 authorship preserved) and marked
  inactive.
- **Tombstones, not hard delete** — a delete tombstones the active revision
  (I-13); hard deletion of source data stays an explicit, audited operation.
- **Re-embed on revision** — a new revision lands `embedding_status='pending'`
  (Slice 2.6) and is re-embedded by the existing pipeline; superseded and
  tombstoned chunks are excluded by the active-state filter immediately,
  regardless of embedding state.
- **State model**: `active | superseded | tombstoned` (column shape / encoding is
  an ED-1 decision).

### Explicitly out of scope

- The exact column shape / state encoding / names and the forward migration
  (ED-1).
- The retrieval predicate change and the R-4 wording generalization in
  `docs/RUNTIME-INVARIANTS.md` (ED-1) — see §2.
- `/edit` ingestion supersession + the re-embed trigger wiring (ED-2).
- `/delete` command + the explicit audited hard-delete operation (ED-3).
- Any new I-/R- number — none opened by the contract; opened only if ED-1
  implementation forces one.
- *(For ED-0 specifically)* any **`src/` / `tests/` / schema / DDL / migration /
  config** change.

---

## 2. As-built audit (surfaces the milestone builds on)

Predicates are described by clause, not line number, so the audit stays true as
code moves.

| Surface | As-built today | Disposition |
| --- | --- | --- |
| Source-layer revisions | edited Telegram messages already land as new `source_messages` rows keyed on `(external_chat_id, external_message_id, edit_seq)`; `edit_seq` is `0` for an original delivery and the `edit_date` epoch for an edited state (R-2 / D-023) | the note/chunk layer extends this with supersession (ED-2); the source layer is unchanged |
| Soft delete | `I-13` — deletes default to tombstones; hard deletion requires an explicit, audited operation | the contract makes I-13 concrete; I-13 reference reconciled to D-114 in ED-0 |
| Active-state retrieval | `R-4` — retrieval returns only chunks of non-tombstoned **and** non-superseded notes by default (ED-1 / D-115); dense leg additionally requires `embedding_status='ready'` | **generalized (ED-1):** both legs filter on the `lifecycle_state='active'` column; the R-4 wording edit landed with ED-1 |
| Authorship | `I-6` — `author_user_id` mandatory at `SourceMessage` / `Note` / `EventChunk`, never erased | preserved across revisions; supersession copies authorship onto each revision, adds no core authorship field |
| Stage status | Slice 2.6 — per-record `parse_status` / `embedding_status` / `index_status` | a new revision lands `embedding_status='pending'`; the existing pipeline re-embeds it (ED-2) |

---

## 3. Ratified contract (D-114)

Cannot change without a new decision packet:

- **Supersession over mutation.** An edited `/note` creates a new note/chunk
  revision (active) that supersedes the prior revision (kept, inactive). Source
  lineage and I-6 authorship are preserved; nothing is mutated in place or
  destroyed.
- **Tombstone over hard delete.** A delete tombstones the active revision (I-13);
  hard deletion of source data stays an explicit, audited operation.
- **Re-embed on revision.** A new revision lands `embedding_status='pending'`
  (Slice 2.6) and is re-embedded by the existing pipeline. Superseded and
  tombstoned chunks are excluded by the active-state filter **immediately**,
  regardless of embedding state — a delete is effective before re-embedding
  completes, and the superseded/tombstoned chunk is never re-embedded.
- **State model**: `active | superseded | tombstoned`. The column shape /
  encoding (single state column vs tombstone flag + supersession link), exact
  names, and the lineage reference are an ED-1 decision.
- **R-4 generalization**: the active-state filter generalizes from
  "non-tombstoned" to "non-tombstoned **and** non-superseded"; the wording edit
  lands with ED-1, not ED-0.
- **Untouched by the contract**: raw-before-enrichment (I-3 / R-1), Postgres as
  the sole durable source of truth (I-2), the source-layer idempotency key (R-2),
  and the existing command surface (ED-0 adds no command).

---

## 4. Packet sequence (refinable)

Names, granularity, and ordering between independent packets are refinable when
each packet is planned, as long as every resulting packet preserves the §3
contract. C = core, A = adapter, Cfg = config (D-026 classification).

| Packet | Surfaces it touches | Class | Status |
| --- | --- | --- | --- |
| **ED-0 — docs-first contract + decomposition** | `docs/decision-log.md` (D-114); this roadmap doc (new); `docs/product/TechSpec.md` §12 (rewritten to the contract); `docs/assumptions.md` + `docs/assumption-audit.md` (A-10 closed → D-114); `docs/INVARIANTS.md` (I-13 cross-reference reconciliation only); `docs/execution-map.md`; `docs/todo.md`. Docs-only — no `src/` / `tests/` / schema / migration / config change; no new I-/R- number. | docs-only | **Landed (D-114).** |
| **ED-1 — state model + schema + retrieval predicate** | single `lifecycle_state` column (`active | superseded | tombstoned`, CHECK + DEFAULT `'active'`) + nullable `supersedes_*` lineage columns on `notes` / `event_chunks` (additive migration 0010); the active-state filter generalized to exclude `superseded` as well as `tombstoned` on both legs; the **R-4 wording** generalization in `docs/RUNTIME-INVARIANTS.md`; backend parity across Postgres / SQLite (round-trip only) / mock. | C + schema | **Landed (D-115).** |
| **ED-2 — `/edit` ingestion supersession + re-embed** | edited source message → new note/chunk revision (supersession) through `DomainService.ingest`; prior revision marked superseded; new revision lands `embedding_status='pending'` and re-embeds via the existing pipeline. | C | **Landed (D-116).** Four repo seams (`get_active_note_for_external_message`, `get_active_chunk_for_note`, `mark_note_superseded`, `mark_chunk_superseded`) across mock / sqlite / postgres; `ingest()` lookup→lineage→save→flip(chunk-then-note)→re-embed. NOTE→NOTE only; malformed/draft edits supersede nothing; replay-safe. |
| **ED-3 — `/delete` control surface** | explicit delete → tombstone the active revision; the explicit, audited hard-delete operation; control-surface wiring. | C + A | planned |
| **ED-n — drill evidence + milestone close** | operator-run real-backend drill (REAL-1 precedent: a committed, dated, redaction-checked evidence artifact); closure flips in this doc, `docs/execution-map.md`, `docs/todo.md`; closure decision entry. | docs-only | planned |

---

## 5. Dependencies & ordering rationale

```
ED-0 (D-114, docs) ──▶ ED-1 (state model + schema + predicate) ──▶ ED-2 (/edit supersession + re-embed) ──▶ ED-3 (/delete) ──▶ ED-n (drill + close)
```

- **ED-0 first** — the contract must be recorded before any `src/` edit (the
  docs-first convention behind D-093 / D-097 / D-106 / D-108).
- **ED-1 before ED-2/ED-3** — the state column, the active-state predicate, and
  the R-4 wording must exist before edit and delete can write or read those
  states.
- **ED-2 / ED-3 order is refinable** — both depend on ED-1 and not on each other;
  edit (supersession + re-embed) and delete (tombstone) are independent surfaces.
- **ED-n last** — milestone close needs real-backend evidence per the REAL-1
  precedent.

---

## 6. Exit criterion

The milestone exits when an edited `/note` is demonstrably superseded by a new
re-embedded revision and a deleted `/note` is demonstrably tombstoned, both with
the prior revision retained (lineage + I-6 authorship preserved) and both
excluded from retrieval by the generalized active-state filter (R-4); hard delete
remains an explicit, audited operation (I-13); there is real-backend round-trip
evidence per the REAL-1 precedent (a committed, dated, redaction-checked
artifact); the decision log / execution map / todo / this roadmap are flipped to
milestone-closed; the full repo gate is green; and one PR bundles the coherent
milestone, not individual packets.

---

## See also

- **D-114** in `docs/decision-log.md` — the authoritative decision entry for the
  edit/delete contract and the A-10 closure.
- **D-108 / D-097 / D-093 / D-044** and their roadmap docs — the "decision entry
  carries the contract, roadmap doc carries the refinable sequence" precedent.
- **I-6 / I-13** in `docs/INVARIANTS.md` — authorship preservation; soft delete
  by default (reference reconciled to D-114 in ED-0).
- **R-2 / R-4** in `docs/RUNTIME-INVARIANTS.md` — source-layer `edit_seq`
  revisions; the active-state retrieval filter generalized by this milestone
  (wording edit lands with ED-1).
- **A-10** (closed → D-114) in `docs/assumptions.md` / `docs/assumption-audit.md`.
- `docs/execution-map.md` — the Phase 2 row 2.5 + the ED-0..ED-n decomposition
  block pointing here.
