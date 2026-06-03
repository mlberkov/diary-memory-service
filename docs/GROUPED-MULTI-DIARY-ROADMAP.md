# Grouped & Multi-Diary Roadmap

## Purpose & status

This document is the refinable-sequence companion to **D-093** (Packet G-0). It
decomposes the **grouped-diary + multi-diary-on-one-instance** milestone into an
ordered set of bounded packets and carries the as-built audit of the
community-bootstrap / chat→community-mapping / membership surface against
**D-026 (adapter axes)**, **D-041 (community / subject vocabulary)**, and
**I-1 / I-6 / I-7 / R-3 / R-8**.

**Status: in progress — Packet G-0 (D-093, docs) + G-1 (D-094, resolver consolidation) + G-2 (D-095, characterization suite) landed; G-3 pending; G-4 deferred.**
Grouped and multi-diary already work *mechanically* (a Telegram group chat
yields one `community_id` with distinct per-sender `author_user_id`; distinct
chats yield isolated communities on one instance; reads are community-scoped and
fail-closed — Slice 8.1 / D-088, D-089, D-090). G-0 ratified the contract
(implicit-on-first-message bootstrap; the 1:1 `external_chat_id → community_id`
adapter-axis mapping; membership inherited from host-chat membership;
multi-diary-on-one-instance is a core capability today). The remaining packets
make the ratified mapping seam physically single (G-1), pin the behavior with a
regression suite (G-2), and document the operator/product model (G-3).

This mirrors the D-087 / `docs/READ-ACCESS-ENFORCEMENT-ROADMAP.md`, D-060 /
`docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md`, and D-044 /
`docs/OPERATIONALIZATION-ROADMAP.md` precedent: the decision entry (**D-093**)
carries the stable contract; this doc carries the refinable sequence and the
audit. **D-093 stays authoritative** for the contract; this doc mirrors it so it
reads alongside the sequence, but does not re-decide it.

---

## 1. Scope

This milestone = **ratify and harden grouped + multi-diary support** on the
existing community-scoped data plane: pin how a community is bootstrapped and how
a host chat maps to a `community_id`, pin that group chats are shared communities
with preserved authorship, pin that one instance serves many communities, and
make the chat→community mapping a single adapter-owned seam — **without** adding a
core participant/ACL model, `/setup`, or a visibility model.

### Explicitly out of scope

- The **visibility model** / per-note scopes — A-15, deferred and sequenced
  **after** the first grouped pilot (G-4); community-level scoping is the access
  model until then.
- A **core participant / membership / ACL table or registry** — membership is
  inherited from host-chat membership (D-093); a registry is deferred until
  access must diverge from chat membership.
- An explicit **`/setup`** onboarding command — deferred-optional (D-093); no
  packet below may depend on it.
- **Subject/child bootstrap** — carved out to **A-45**; `subject_id` is born in
  the D-040 child-filter lineage, not here.
- **DEPLOY-2** managed-cloud multi-tenant deployment shape — its own roadmap
  (`docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md`, A-41).
- Any **schema / DDL / migration** change.

---

## 2. As-built audit (mirrored from D-093)

Predicates are described by clause, not line number, so the audit stays true as
code moves.

| Surface | As-built today | Verdict |
| --- | --- | --- |
| Chat→community mapping | **G-1 (D-094): consolidated** into one adapter-owned resolver `adapters/telegram/community.py` `resolve_community_id`; the resolved opaque `community_id` is carried on `InboundMessage.community_id` and the core never re-derives scope from `external_chat_id`. *(As-built before G-1 was broader than the original audit's "three sites": 6 core/services derivations + 2 adapter copies — see D-094.)* | ratified rule (D-093); **consolidated (D-094)** |
| Group chat | one shared `community_id`, distinct `author_user_id` per sender; authorship preserved (I-6) | works; **pinned (G-2 / D-095)** |
| Multi-diary on one instance | distinct chats → isolated communities; every record `community_id`-keyed, every read scoped (I-7 / R-3 / R-8; Slice 8.1) | works; **pinned (G-2 / D-095)** |
| Membership | inherited from host-chat membership; community-level read scoping (Slice 8.1); **no core ACL** | ratified (D-093) |
| Bootstrap | implicit-on-first-message (first message persists a `SourceMessage` + derives `community_id`); no `/setup` | ratified (D-093) |
| Community / Participant / Subject entity | **absent** (community is an opaque `community_id` scalar) | intentional — no entity this milestone |

---

## 3. Ratified contract (D-093)

Cannot change without a new decision packet:

- **Bootstrap is implicit-on-first-message.** A new chat initializes its
  community scope on first inbound message. `/setup` is deferred-optional, never
  a dependency of a later packet.
- **The chat→community mapping is an adapter-axis function** (D-026 axis 5: the
  mapping function is adapter, the scoped query is core). Default Telegram mapping
  is 1:1 from `external_chat_id`. The core receives an **opaque** `community_id`;
  past the edge it is never "the Telegram chat id" (D-089 framing).
- **Membership is inherited from host-chat membership.** Every chat member has
  community-level read/query access to the whole community corpus; authorship is
  preserved per opaque `author_user_id` (I-6). No core participant/ACL table this
  milestone.
- **Multi-diary on one instance is a core capability.** N communities coexist on
  one instance without leakage (I-7 / R-3 / R-8). DEPLOY-1 single-tenant is a
  deployment default, non-binding on the core.
- **No `src/` claim of a single resolver seam until G-1 makes it true.** D-093
  ratifies the mapping *rule* over the as-built three sites; the single
  adapter-owned resolver is a sequenced code packet, not an assumed fact.

---

## 4. Packet sequence (refinable)

Names, granularity, and ordering between independent packets are refinable when
each packet is planned, as long as every resulting packet preserves the §3
contract. C = core, A = adapter, Cfg = config (D-026 classification).

| Packet | Surfaces it touches | Class | Status |
| --- | --- | --- | --- |
| **G-0 — contract + assumption split + roadmap** | `docs/decision-log.md` (D-093); this roadmap doc (new); `docs/assumptions.md` + `docs/assumption-audit.md` (close A-14 → D-093, open A-45); `docs/execution-map.md`; `docs/todo.md`; cross-ref-only touches to INVARIANTS / RUNTIME-INVARIANTS / RUNBOOK / TechSpec §5 / ARCHITECTURE. Docs-only — no `src/` / `tests/` / schema change. | docs-only | **Landed (D-093).** |
| **G-1 — consolidate the chat→community resolver** | Replaced the open-coded `external_chat_id → community_id` derivations (6 core/services sites + 2 `webhook.py` copies — broader than the audit's "three") with **one adapter-owned resolver** `resolve_community_id`; the resolved opaque `community_id` crosses the boundary on `InboundMessage.community_id`, and the core never re-derives scope from `external_chat_id`. Behavior-preserving (default mapping stays 1:1). The resolver yields an opaque scope id and never leaks a Telegram type into the core (I-1). The named seam is where a future host plugs a different mapping. | **A** (+ core call sites) | **Landed (D-094).** |
| **G-2 — grouped + multi-diary regression suite** | New consolidated `tests/test_grouped_multi_diary.py` (6 tests, mock-mode) pinning already-true behavior through the G-1 `resolve_community_id` seam: one group chat → one `community_id` + distinct `author_user_id` per sender; grouped `/ask` preserves ≥2 contributors into the answer context (I-6) + the ASK `grounding_chunks` seam (D-091); N distinct chats → N isolated communities; cross-community `/sources`-cache isolation re-asserted at grouped granularity (composing with Slice 8.1's `tests/test_read_access_isolation.py` and `tests/test_dispatcher_sources.py`). Mock-mode only; PG/sqlite storage-read parity stays with the existing PG-gated suites. No `src/` behavior change. | tests | **Landed (D-095).** |
| **G-3 — operator + product docs** | `docs/RUNBOOK.md` how-to for the bootstrap/mapping/membership model and running multi-diary on one instance; reconcile `docs/ARCHITECTURE.md` axis-5 prose and `docs/product/TechSpec.md` §5 with the ratified mapping; mark grouped/multi-diary as supported. | docs-only | Pending. |
| **G-4 — visibility model (A-15 / Slice 8.2)** *(deferred, not built)* | Enumerate `visibility_scope` values and per-note / per-participant read control **after** the first grouped pilot. Explicitly out of scope of this milestone. | future | Deferred (A-15). |

---

## 5. Dependencies & ordering rationale

```
G-0 (D-093, docs) ──▶ G-1 (resolver consolidation) ──▶ G-2 (regression suite) ──▶ G-3 (operator/product docs) ──▶ [G-4 deferred: A-15 / Slice 8.2]
```

- **G-0 first** — the contract + audit must be recorded before any `src/` edit
  (D-060 / D-044 / D-087 docs-first convention).
- **G-1 before G-2** — consolidating the mapping into one seam gives the
  regression suite a single, named target to characterize rather than three
  duplicated sites.
- **G-2 before G-3** — the operator/product docs describe behavior the regression
  suite has just pinned.
- **G-4 deferred** — per-note/per-participant visibility (A-15 / Slice 8.2) is a
  finer access granularity that layers on top of community-level scoping; it is
  sequenced after the first grouped pilot and does not block G-1..G-3.

---

## 6. Exit criterion

The milestone exits when the chat→community mapping is a single adapter-owned
seam (G-1), grouped + multi-diary behavior is pinned by a regression suite that
is green across mock / sqlite / PG-gated postgres (G-2), and the
operator/product docs record the bootstrap/mapping/membership model and how to
run multi-diary on one instance (G-3) — all while preserving the §3 contract and
the existing community-scoping invariants (I-7 / R-3 / R-8). The visibility model
(A-15 / Slice 8.2) and subject/child bootstrap (A-45) are separate and **not**
part of this exit criterion.

---

## See also

- **D-093** in `docs/decision-log.md` — the authoritative decision entry for the
  community-bootstrap / mapping / membership contract and this packet ladder.
- **D-026** in `docs/decision-log.md` and `docs/ARCHITECTURE.md` — the five
  adapter axes; axis 5 (tenant/auth mapping): "the mapping function is adapter;
  the scoped query is core".
- **D-041** in `docs/decision-log.md` and `docs/GLOSSARY.md` — the canonical
  `community` (one-or-more participants) / `subject` / `participant` vocabulary.
- **I-1 / I-6 / I-7** in `docs/INVARIANTS.md` and **R-3 / R-8 / R-14** in
  `docs/RUNTIME-INVARIANTS.md` — channel boundary, authorship, community scoping.
- **A-14** (closed → D-093, community half), **A-45** (subject/child bootstrap,
  open → D-040 lineage), and **A-15** (visibility, deferred to Slice 8.2 / G-4)
  in `docs/assumptions.md` / `docs/assumption-audit.md`.
- `docs/READ-ACCESS-ENFORCEMENT-ROADMAP.md`, `docs/OPERATIONALIZATION-ROADMAP.md`,
  `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` — the structurally analogous roadmap
  docs and the "decision entry carries the contract, roadmap doc carries the
  refinable sequence" precedent.
- `docs/execution-map.md` — the milestone row + note block pointing here.
- `docs/todo.md` — the grouped/multi-diary backlog section.
