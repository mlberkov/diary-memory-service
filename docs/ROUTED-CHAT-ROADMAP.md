# Routed-Chat Roadmap

## Purpose & status

This document is the refinable-sequence companion to **D-108** (Packet RC-1). It
decomposes the **routed chat core** milestone — a routed conversational entry
point in the functional core that classifies an incoming natural-language
question into one of four routes and answers it under explicit per-source
provenance labeling — into an ordered set of bounded packets, and carries the
as-built audit of the surfaces the milestone builds on.

**Status: in progress — Packet RC-1 (D-108, docs-first contract +
owner-override recording) landed; RC-2..RC-4 are planned.** No `src/` surface
of this milestone exists yet: there is no `/chat` command, route enum,
classifier, dispatcher extension, web adapter, or trace field until the code
packets make each true (D-108, mirroring D-097's "no `src/` claim until H-1").

The milestone is an **explicit owner override of the default pick-next
sequencing**: the edit/delete milestone (**A-10**, TechSpec §12, Slice 2.5) is
**re-queued as the milestone immediately after this one** (recorded in D-108;
visible in `docs/todo.md` and on the execution-map 2.5 row). Routed chat has no
dependency on A-10, and routing reuses the existing retrieval seam unchanged —
so when A-10 lands later, tombstoned/superseded exclusion (R-4) applies to
routed answers automatically.

This mirrors the **D-097 / `docs/SUBJECT-SCOPING-ROADMAP.md`**, **D-093 /
`docs/GROUPED-MULTI-DIARY-ROADMAP.md`**, and **D-044 /
`docs/OPERATIONALIZATION-ROADMAP.md`** precedent: the decision entry (**D-108**)
carries the stable contract; this doc carries the refinable sequence and the
audit. **D-108 stays authoritative** for the contract; this doc mirrors it so it
reads alongside the sequence, but does not re-decide it.

---

## 1. Scope

This milestone = **add a routed conversational entry point to the functional
core**: classify an incoming natural-language question into one of four routes
(`diary_lookup` / `diary_plus_llm` / `diary_plus_web` / `general_llm` —
product-register labels; core identifiers `notes_lookup` / `notes_plus_model` /
`notes_plus_knowledge` / `model_only`, D-108 dual-register mapping), and answer
it by combining the existing note-grounded answering with model-knowledge
answering and web-grounded answering, every answer segment carrying an explicit
provenance class (notes / web / model). First — and for this milestone, only —
surfaced through the existing Telegram control surface via a new `/chat`
command. This is step A of the host roadmap in which theygrow.app later
consumes the same seam; Phase 9 / A-21 remain untouched and undecided.

### Explicitly out of scope

- **A-21 / Phase 9** host-integration seam work (HTTP API vs SDK), web UI,
  theygrow.app embedding — the seam is designed so Phase 9 can expose it
  without reshaping, but nothing is opened or pre-decided.
- **Edit/delete mechanics (A-10)** — explicitly the next milestone after this
  one (owner re-queue, D-108); re-queued, not advanced.
- **Thematic-tag enrichment at ingestion**; TheyGrow knowledge-graph / ontology
  integration; memory synthesis / proactive summaries; voice/photo ingestion;
  multi-agent orchestration.
- The **explicit `/ask` filter-syntax** item (`docs/todo.md`, Slice 3.4
  (cont.)) — only its natural-language side is partially delivered by RC-3; the
  explicit-syntax half stays a separate, open item.
- The **curated domain-knowledge provider** — expected later behind the same
  knowledge-source seam; not implemented or decided beyond the seam shape.
- *(For RC-1 specifically)* any **`src/` / `tests/` / schema / DDL / migration /
  config** change.

---

## 2. As-built audit (surfaces the milestone builds on)

Predicates are described by clause, not line number, so the audit stays true as
code moves.

| Surface | As-built today | Disposition |
| --- | --- | --- |
| Grounded ask flow | one `/ask` pipeline: hybrid retrieval (I-8) → structured answer with citation grounding (D-033) → fallback grading (`FallbackMode`, D-035) → cited-only evidence surface (D-098 / D-099 / D-100) | `diary_lookup` delegates to it **unchanged** |
| Provider contour | OpenAI only — embeddings (D-024) + chat `gpt-4.1` boot-gated (D-037), hardened via `adapters/resilience.py` (timeouts, bounded retries, backoff — D-047 / D-049; R-7 / R-9) | classifier (`gpt-4.1-mini`) + knowledge-source adapter follow the same pattern (RC-2 / RC-4) |
| Retrieval kwargs | keyword-only `date_range` (D-040) + `subject_scope` (D-107) on both search legs at the service seam | RC-3 rewriting maps natural language onto them; seam unchanged |
| Trace plane | `Query` / `RetrievalHit` / `AnswerTrace` rows per `/ask` (D-032 / D-035; R-5 / R-6 / R-11) | routing decisions, classifier outputs, rewritten queries, web traces join this plane (additive, RC-2..RC-4) |
| Web search / knowledge source | **absent** — no provider, adapter, or config anywhere | new narrow knowledge-source port + hardened Tavily adapter (RC-4); R-7 already names "search backend" |
| Command surface | `/note` `/ask` `/drafts` `/export` `/sources` + unconditional draft floor (I-14 / R-13) | unchanged; `/chat` is a new command (RC-2) |

---

## 3. Ratified contract (D-108)

Cannot change without a new decision packet:

- **Four routes, owner-fixed verbatim** (product register): `diary_lookup`
  (diary retrieval only — the existing grounded ask, unchanged),
  `diary_plus_llm` (LLM generation with diary context / enrichment retrieval),
  `diary_plus_web` (web search + diary context, both cited), `general_llm` (LLM
  directly, no retrieval). Pipeline: classify → (rewrite query → scoped
  retrieval) → (web search where applicable) → generate with provenance labels.
  Enrichment pattern: retrieve personal context first, rewrite the outward
  query using it, answer combining both planes.
- **Dual-register naming**: core identifiers are `notes_lookup` /
  `notes_plus_model` / `notes_plus_knowledge` / `model_only` (D-026 / D-041;
  `docs/GLOSSARY.md` carries the mapping); `diary_*` labels stay in
  use-case-facing prose.
- **Placement**: router in the functional core at the service seam, not the
  Telegram adapter (I-1); hand-rolled single-LLM classification + dispatch (no
  LangGraph, not multi-agent); in-process call from the adapter; A-21 / Phase 9
  untouched.
- **Control surface**: new **`/chat`** command; existing commands and the
  unconditional draft floor byte-/behavior-unchanged.
- **Providers**: classifier = OpenAI function-calling, canonical pin
  **`gpt-4.1-mini`** (separate pin alongside the D-037 `gpt-4.1` gate);
  knowledge source = narrow core port + hardened **Tavily** adapter (not
  welded to "web").
- **Provenance / generalized I-9**: every answer segment carries a provenance
  class — notes (cited via the cited-only evidence surface), web (cited URLs),
  model (explicitly labeled); no segment may present model or web content as if
  it came from the diary; I-9 preserved verbatim for the notes-grounded class.
- **Scoping**: R-3 / R-8 (+ optional `subject_scope`) on every retrieval and
  every prompt in every route, including enrichment retrievals; test-asserted.
- **Medical amendment + escalation prompt invariant**: general developmental
  information and activity suggestions allowed in reactive answers; never a
  diagnosis or symptom interpretation; potential developmental/medical red
  flags (in the question or the retrieved diary context) ⇒ the answer must
  recommend consulting a specialist — a system-prompt invariant of
  `diary_plus_llm` / `diary_plus_web`, tested on red-flag-style prompts (mock
  providers).
- **Failure / fallback policy**: no numeric confidence thresholds;
  classification failure/ambiguity defaults to `diary_lookup` + honest
  degradation (empty/weak diary evidence stated explicitly **before** any
  general/web content); requested vs effective route per R-6; routing accuracy
  observed via traces, not gated.
- **Trace contract**: routing decisions, classifier outputs, rewritten queries,
  retrieval + web traces captured in the existing trace plane; schema
  extensions additive and non-destructive, landing with the code packets.
- **Untouched**: raw-before-enrichment (I-3 / R-1), Postgres as sole durable
  source of truth (I-2), no destructive schema changes.

---

## 4. Packet sequence (refinable)

Names, granularity, and ordering between independent packets are refinable when
each packet is planned, as long as every resulting packet preserves the §3
contract. C = core, A = adapter, Cfg = config (D-026 classification).

| Packet | Surfaces it touches | Class | Status |
| --- | --- | --- | --- |
| **RC-1 — docs-first contract + owner-override recording** | `docs/decision-log.md` (D-108); this roadmap doc (new); `docs/INVARIANTS.md` (I-9 appended provenance-class clause); `docs/product/PRD.md` (§6 medical bullet amended); `docs/product/TechSpec.md` §4 (`/chat` target line); `docs/GLOSSARY.md` (route mapping); `docs/assumptions.md` + `docs/assumption-audit.md` (A-10 re-queue annotations); `docs/execution-map.md`; `docs/todo.md`. Docs-only — no `src/` / `tests/` / schema change. | docs-only | **Landed (D-108).** |
| **RC-2 — classifier + dispatcher + two routes** | Routed entry at the service seam: classifier provider adapter (`gpt-4.1-mini` pin + `Settings` knob + boot-gate clause, D-047/D-049 hardening), hand-rolled dispatch over the core route enum (`notes_lookup` / `notes_plus_model` / `notes_plus_knowledge` / `model_only`); `notes_lookup` (`diary_lookup`) delegates to the existing grounded ask unchanged; `model_only` (`general_llm`) adds direct LLM with explicit model labeling; Telegram `/chat` wiring; routing + classifier output captured in traces (additive migration); classification-failure → `diary_lookup` fallback. | C + A (+ Cfg, schema) | Planned. |
| **RC-3 — enrichment + rewriting + `diary_plus_llm`** | Enrichment retrieval (personal context first), rewrite-to-kwargs onto the landed `date_range` / `subject_scope` seam, `notes_plus_model` (`diary_plus_llm`) generation with mixed notes+model provenance labeling; honest-degradation wording on empty/weak diary evidence; regression coverage asserting R-3 / R-8 scoping inside enrichment retrievals. | C | Planned. |
| **RC-4 — `diary_plus_web` + closure** | Narrow knowledge-source port + hardened Tavily adapter (R-7 / R-9); `notes_plus_knowledge` (`diary_plus_web`) full pipeline (enrich → rewrite → search → synthesize, citing both planes — notes citations + web URLs); escalation invariant verified on red-flag-style prompts (mock provider); consolidated regression suite (mock + PG-gated); `docs/RUNBOOK.md` operator section; doc reconciliation + milestone-closed flips (this doc, execution-map, todo). | C + A (+ Cfg) | Planned. |

---

## 5. Dependencies & ordering rationale

```
RC-1 (D-108, docs) ──▶ RC-2 (classifier + dispatcher + diary_lookup + general_llm) ──▶ RC-3 (enrichment + rewriting + diary_plus_llm) ──▶ RC-4 (diary_plus_web + closure)   [A-10 edit/delete: the next milestone after RC-4]
```

- **RC-1 first** — the contract, taxonomy, provider decisions, and the owner
  override must be recorded before any `src/` edit (D-093 / D-097 / D-106
  docs-first convention).
- **RC-2 before RC-3** — the classifier/dispatcher seam and the two
  no-enrichment routes establish the routed entry the enrichment routes plug
  into.
- **RC-3 before RC-4** — `diary_plus_web` reuses RC-3's enrichment + rewriting
  and adds only the knowledge-source plane on top.
- **A-10 after RC-4** — owner re-queue (D-108); no RC packet depends on
  edit/delete mechanics, and the unchanged retrieval seam means later
  tombstone exclusion (R-4) applies to routed answers automatically.

---

## 6. Exit criterion

The milestone exits when all four routes are demonstrable end-to-end through
Telegram, with real-backend round-trip evidence per the REAL-1 precedent
(D-073 / D-074: a committed, dated, redaction-checked evidence artifact); every
answer segment is provenance-labeled; no diary-uncited claim is attributed to
the diary; community/subject scoping is enforced on every retrieval and every
prompt (R-3 / R-8); the existing command surface and invariants are untouched;
the decision log / execution map / todo / this roadmap are flipped to
milestone-closed; **A-10 is visibly re-queued as next**; the full `make check`
gate is green; and one PR bundles the coherent milestone, not individual
packets.

---

## See also

- **D-108** in `docs/decision-log.md` — the authoritative decision entry for
  the routed-chat contract, the provider/control-surface decisions, and the
  owner-ordered A-10 re-queue.
- **D-097 / D-093 / D-044** and their roadmap docs — the "decision entry
  carries the contract, roadmap doc carries the refinable sequence" precedent.
- **I-9** in `docs/INVARIANTS.md` — grounded answers, generalized by D-108 to
  per-segment provenance classes.
- **R-3 / R-4 / R-6 / R-7 / R-8 / R-9 / R-11** in
  `docs/RUNTIME-INVARIANTS.md` — scoping, tombstone filtering, requested-vs-
  effective path, provider observability and bounds, routing recording.
- **D-040 / D-107** in `docs/decision-log.md` — the `date_range` /
  `subject_scope` retrieval-kwarg seam RC-3 rewriting maps onto.
- **D-047 / D-049** in `docs/decision-log.md` — the provider-hardening pattern
  the classifier and knowledge-source adapters follow.
- **A-10** (re-queued next) and **A-21** (untouched, Phase 9) in
  `docs/assumptions.md` / `docs/assumption-audit.md`.
- `docs/execution-map.md` — the "Routed chat core (D-108)" block pointing here.
