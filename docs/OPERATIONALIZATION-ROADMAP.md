# Operationalization Roadmap — Stage 2

## Purpose & status

This document is the detailed design artifact for **Stage 2 — Operationalization
/ real infrastructure binding** (D-043). It decomposes Stage 2 into an ordered,
refinable sequence of packet groups, `OP-1`..`OP-5`.

**Status: Stage 2 complete.** OP-1 is complete — OP-1.1 (D-045) landed the migration
tool, the baseline migration, and the rewired bootstrap; OP-1.2 (D-046) landed
the first non-destructive schema-changing upgrade and resolved A-34. OP-2 is
complete — Slice 6.1 (D-047) landed the provider timeout / bounded-retry
primitive, Slice 6.2 (D-048) landed the persistent dead-letter surface for
failed indexing jobs, and Slice 6.3 (D-049) landed rate-limit backoff
(exponential delay, jitter, clamped `Retry-After`). OP-3 is complete —
OP-3.1 (D-050) landed the failed-embedding discovery seam and the read-only
reconciliation entrypoint, OP-3.2a (D-051) landed the retry execution that
transitions succeeded chunks `failed → ready`, and OP-3.2b (D-052) landed
exhausted-retry dead-letter routing, which resolves A-35. OP-4 is
complete — OP-4.1 (D-053) resolved A-40, selecting a nightly physical base
backup + continuous WAL archiving → PITR as the recovery primitive, RPO ≤ 5 min
/ RTO ≤ 1 h for raw `SourceMessage` data, and a restore-drill cadence of once
before the first non-local deployment, then quarterly thereafter, and decomposed
OP-4 into OP-4.1/4.2/4.3; OP-4.2 (D-054) landed the backup automation —
always-on WAL archiving plus an opt-in nightly `pg_basebackup` sidecar with
`pg_archivecleanup`-based retention for the reference Postgres shape; OP-4.3
(D-055) landed the restore tooling and executed the restore drill — full
restore and PITR both recovered raw `SourceMessage` data within the RPO/RTO
targets, meeting the Phase 8 raw-data durability DoD. OP-5 is complete —
OP-5.1 (D-056) landed the OP-5 *observability* gold eval set
(`eval/retrieval/observability/{gold.json,corpus.jsonl}`), a ~21-query /
19-message set sitting beside the frozen D-038 baseline set rather than
superseding it; OP-5.2a (D-057) added retrieval `hit_rate` / `empty_rate`
metrics to the eval harness; OP-5.2b (D-058) added the answer-path
groundedness-proxy metric (`groundedness_rate` + `fallback_mode_counts`
derived from `AnswerResult.fallback`), closing execution-map row 7.2; and
OP-5.3 (D-059) added token + wall-clock latency aggregation to the eval
harness (`CostMetrics` + `LatencyMetrics` + `CostLatencyMetrics`, populated
by `run_harness` and `run_answer_harness` via a `RecordingChatClient`
single-call / single-consumer shim), closing execution-map row 7.3. **All
five OP-groups have landed; the Stage-2 → Stage-3 operationalization gate
is open.** This document records the *recommended* sequence and the *fixed*
ordering constraints; it is a refinable design surface.

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
| **OP-1 — Schema-migration tooling** *(complete)* | A-34; D-043 Stage-2 exit clause "schema upgrades are non-destructive" | Introduce a migration tool and capture the current bootstrap DDL as the baseline migration — **OP-1.1 landed (D-045)**: `yoyo-migrations`; `src/memory_rag/storage/postgres/migrations/0001.baseline-schema.sql`; `schema.sql` retired; bootstrap applies migrations to head; one-time `stamp` adoption for pre-existing volumes. **OP-1.2 landed (D-046)**: the first non-destructive schema-*changing* upgrade migration `0002.index-embedding-status.sql`, validated as a non-destructive upgrade over populated data. **OP-1 is complete and A-34 is resolved.** |
| **OP-2 — Provider hardening** *(complete)* | Phase 6 (BuildPlan slices 6.1 timeouts & retries, 6.2 dead-letter, 6.3 rate-limit handling) | Bounded retry policy and explicit timeouts on provider calls (R-9); error classification; a dead-letter surface for failed indexing jobs; rate-limit backoff and the matching observability. **Slice 6.1 landed (D-047)**: the shared `adapters/resilience.py` bounded-retry/timeout primitive, wired into both OpenAI adapters with an explicit per-attempt timeout and `max_retries=0` — R-9 is enforced for provider calls. **Slice 6.2 landed (D-048)**: the `IndexingDeadLetter` entity, the additive `0003.indexing-dead-letter-table.sql` migration and `indexing_dead_letters` table (mock / sqlite / postgres parity), and a best-effort dead-letter write on embedding failure — failed indexing jobs survive and are inspectable. **Slice 6.3 landed (D-049)**: exponential-with-jitter inter-attempt backoff and clamped `Retry-After` honoring in `run_with_retries`, `provider_backoff_base_seconds` / `provider_backoff_cap_seconds` knobs, and `delay_ms` / `delay_source` observability — the R-9 worst-case bound is `timeout × attempts + backoff_cap × (attempts − 1)`. The Phase 6 Definition of Done is met. |
| **OP-3 — Failed-embedding reconciliation** *(complete)* | A-35 | A reconciliation job that retries `embedding_status='failed'` chunks with bounded backoff, routes exhausted retries to OP-2's dead-letter surface, and emits retry-outcome logs/metrics. **OP-3.1 landed (D-050)**: the `DomainRepository.list_failed_event_chunks` discovery seam (community-scoped, oldest-first, mock / sqlite / postgres parity) plus a read-only `ReconciliationService` and `python -m memory_rag.services.reconciliation` CLI that replaces the raw `psql` probe — discovery only, no retry. **OP-3.2a landed (D-051)**: `ReconciliationService.retry_failed_chunks` retries the discovered failed chunks grouped by `source_message_id`, persists `EmbeddingRecord` rows and transitions succeeded chunks `failed → ready`, emits a `RetryOutcomeReport` and `reconciliation.retry.*` logs, and adds a `--retry` CLI mode. **OP-3.2b landed (D-052)**: an exhausted retry group is routed to OP-2.2's `indexing_dead_letters` surface with a best-effort, append-only `save_indexing_dead_letter` write; `RetryGroupOutcome.dead_letter_id`, the `reconciliation.retry.group.failed` log, and `render_retry_report` surface the dead-letter identity. **A-35 is resolved**; OP-3 is complete. |
| **OP-4 — Raw-data durability & backup** *(complete)* | Phase 8 raw-data durability/backup slice (Stage 2 only); D-027; D-053; A-40 | Daily backup window (target `03:00–05:00` local) covering at minimum `source_messages` plus enough relational scaffolding to restore `SourceMessage → Note → EventChunk` lineage; a stronger-than-nightly recovery primitive; the A-40 mechanism + RPO/RTO selection. **OP-4.1 landed (D-053)**: A-40 resolved — for the reference Postgres shape, a nightly physical base backup + continuous WAL archiving → PITR (managed-cloud and self-hosted shapes use the provider- or operator-owned equivalent; no vendor named, A-41 stays open); RPO ≤ 5 min / RTO ≤ 1 h for raw `SourceMessage` data; base backups retained 30 days; a restore drill once before the first non-local deployment, then quarterly thereafter. **OP-4.2 landed (D-054)**: backup automation — always-on WAL archiving (`docker-compose.yml`), a separate `memory_rag_pg_archive` volume, and an opt-in `pg_backup` sidecar (Compose profile `backup`) running `pg_basebackup` nightly in the `03:00–05:00` window with `pg_archivecleanup`-based retention. **OP-4.3 landed (D-055)**: restore tooling (`scripts/pg_restore/restore.sh`, the `pg_restore` Compose service) and an executed restore drill — full restore and PITR both recovered raw `SourceMessage` data within the RPO ≤ 5 min / RTO ≤ 1 h targets. **A-40 is resolved; OP-4 is complete** — the Phase 8 raw-data durability DoD is met. |
| **OP-5 — Evaluation & observability** *(complete)* | Phase 7 (BuildPlan slices 7.1 gold eval set, 7.2 retrieval & groundedness metrics, 7.3 cost & latency) | A curated gold eval set (extending the D-038 retrieval harness); retrieval hit-rate / empty-rate / groundedness metrics; parse-success metrics; indexing latency; cost & token aggregation; regression visibility. **OP-5.1 landed (D-056)**: the OP-5 *observability* gold eval set — `eval/retrieval/observability/{gold.json,corpus.jsonl}`, ~21 queries over a 19-message corpus, curated for coverage diversity (negatives, multilingual, paraphrase, single/multi-hit). It sits **beside** the frozen D-038 baseline set rather than superseding it (the D-038 Postgres baseline is still uncaptured); the default mock harness invocation still loads the D-038 set, the observability set is selected via explicit `--gold`/`--corpus` flags. `tests/test_retrieval_harness_shape.py` is parametrized over both fixture pairs (mock-mode, shape-only). **OP-5.2a landed (D-057)**: retrieval `hit_rate` / `empty_rate` metrics on the eval harness — `AggregateMetrics` gains two fields computed by pure helper functions from the existing per-query rows, rendered in the harness report; `hit_rate` uses an owner-confirmed non-empty-gold denominator (distinct from `per_leg_recall_at_20.fused`); inspection only, no thresholds. **OP-5.2b landed (D-058)**: an answer-path groundedness-proxy metric on the eval harness — `run_answer_harness` drives `QueryService.answer` over every gold query and grades `groundedness_rate` + a `fallback_mode_counts` breakdown from `AnswerResult.fallback`. The metric is an explicit **fallback-derived proxy** (`{NONE, WEAK_EVIDENCE, AMBIGUOUS}` → grounded; `PARSE_FAILURE` — the I-9 citation-subset violation contour — and `PROVIDER_UNAVAILABLE` / `NO_EVIDENCE` not grounded), not a citation-coverage or factuality score; named "Groundedness proxy (answer-path, fallback-derived, inspection only)" verbatim in the CLI and RUNBOOK; non-empty-gold denominator mirrors `hit_rate`; inspection only, no thresholds. Together OP-5.2a + OP-5.2b close execution-map row 7.2. **OP-5.3 landed (D-059)**: token + wall-clock latency aggregation on the eval harness — `CostMetrics` / `LatencyMetrics` / `CostLatencyMetrics` dataclasses populated by `run_harness` (retrieval wall-clock around dense+sparse+RRF, query-embedding lookup intentionally excluded as mode-asymmetric) and `run_answer_harness` (wall-clock around `QueryService.answer(...)` + provider-reported `ChatResponse.token_counts` captured via a `RecordingChatClient` single-call / single-consumer shim whose `consume_last` clear-on-read semantics structurally prevent misattribution onto no-chat-call rows). Aggregate latency is wall-clock only (mean / p50 / max); the provider-attributed `ChatResponse.latency_ms` remains trace-level provenance on `AnswerTrace` (D-034 / D-035) and is not re-aggregated. `p95` intentionally omitted at the current ~20-21-query gold-set size — too noisy. CLI section title `Cost & latency (wall-clock + provider-reported tokens, inspection only)` matches the RUNBOOK subsection verbatim; explicit denominator annotations on every metric line. Inspection only, no thresholds. **OP-5.3 closes execution-map row 7.3 and completes OP-5; the Stage-2 → Stage-3 operationalization gate is open.** |

---

## 3. Recommended implementation roadmap

Execution order: **OP-1 → OP-2 → OP-3 → (OP-4 ‖) → OP-5.** OP-4 may run
concurrently with OP-2/OP-3 once OP-1 is merged.

| Packet | Group | Preconditions | Exit criterion (by reference) | Validation |
| --- | --- | --- | --- | --- |
| **OP-1** *(complete — OP-1.1 / D-045 + OP-1.2 / D-046)* | Schema-migration tooling | D-044 merged. None on Phase 6/7 behavior — OP-1 leads Stage 2. | A-34 resolved: schema upgrades are non-destructive (D-043 Stage-2→3 exit clause; A-34 closed in `docs/assumptions.md`). | A fresh-environment bootstrap and an upgrade from the prior schema both succeed without a destructive volume reset. OP-1.1 validated the fresh-bootstrap and stamp-adoption halves; OP-1.2 validated the schema-changing-upgrade half — `0002` applied over populated data, index present, all rows survive. |
| **OP-2** | Provider hardening | OP-1 merged (the dead-letter surface adds persistent state and rides OP-1's non-destructive upgrades). | Phase 6 Definition of Done (`docs/product/BuildPlan.md` "Phase 6 — Provider Hardening"): provider failures do not corrupt durable state; retries are bounded and visible; fallback behavior is explicit and logged. | `make check`; provider-failure paths exercised with bounded retries and an inspectable dead-letter surface. |
| **OP-3** *(complete — OP-3.1 / D-050, OP-3.2a / D-051, OP-3.2b / D-052 landed)* | Failed-embedding reconciliation | OP-1 and OP-2 merged — OP-3 consumes OP-2's bounded-backoff retry (6.1) and dead-letter (6.2) primitives, per A-35's own specification. | A-35 resolved (`docs/assumptions.md`), governed by the same Phase 6 Definition of Done. OP-3.1 landed the read-only discovery seam, OP-3.2a the retry execution (`failed → ready`), and OP-3.2b the exhausted-retry dead-letter routing that resolves A-35. | `make check`; a `failed` chunk is retried, succeeds or lands in the dead-letter surface, and the outcome is observable. |
| **OP-4** *(complete — OP-4.1 / D-053, OP-4.2 / D-054, OP-4.3 / D-055 landed)* | Raw-data durability & backup | OP-1 merged (recovery restores into a schema-versioned database). Independent of OP-2/OP-3 — may run in parallel. | Phase 8 raw-data durability Definition of Done (`docs/product/BuildPlan.md` "Phase 8"): raw is recoverable from at least the prior nightly window plus a tighter recovery point than nightly-only (D-027); A-40 mechanism + RPO/RTO selected. OP-4.1 (D-053) resolved A-40 — base backup + continuous WAL archiving → PITR, RPO ≤ 5 min / RTO ≤ 1 h; OP-4.2 (D-054) landed the backup automation; OP-4.3 (D-055) landed the restore tooling and executed the restore drill. | A restore drill recovered raw `SourceMessage` data from the backup window (full restore) and from the stronger-than-nightly primitive (PITR), both within the RPO/RTO targets — Phase 8 raw-data durability DoD met. |
| **OP-5** *(complete — OP-5.1 / D-056 + OP-5.2a / D-057 + OP-5.2b / D-058 + OP-5.3 / D-059 landed)* | Evaluation & observability | OP-2 merged so quality is measured against hardened infrastructure. The gold-eval-set work (7.1) extends the D-038 harness and may begin in parallel with OP-2; the group as a whole closes Stage 2. OP-5.1 (D-056) landed the observability gold eval set, OP-5.2a (D-057) landed retrieval `hit_rate` / `empty_rate` metrics, OP-5.2b (D-058) landed the answer-path groundedness-proxy metric (closes execution-map row 7.2), and OP-5.3 (D-059) landed token + wall-clock latency aggregation (closes execution-map row 7.3). | Phase 7 Definition of Done (`docs/product/BuildPlan.md` "Phase 7 — Evaluation and Observability"): quality is measurable; regressions are visible; rollout decisions can rely on metrics. | `make check`; the eval harness produces retrieval / groundedness / cost / latency aggregates over both fixture pairs (D-038 baseline + OP-5 observability). |

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
  aggregation consumes. OP-5.3 (D-059) realized this cross-cut: provider-reported
  `ChatResponse.token_counts` and wall-clock around the existing retrieval and
  `QueryService.answer(...)` calls feed `CostMetrics` and `LatencyMetrics` in
  the eval harness — no production telemetry change, no new signal emission,
  inspection only.

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
- `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` — the structurally analogous D-060
  roadmap doc for **DEPLOY-1** (self-hosted VPS + Telegram, the first
  implemented reference deployment shape) and the deferred DEPLOY-2
  managed-cloud reference deployment. Deployment-shape rollout is sequenced
  there, separately from the OP-1..OP-5 Stage-2 axis decomposed in this doc;
  DEPLOY-1.6 (off-box backup sink wiring) reuses the OP-4 WAL / base-backup
  primitives.
- A-34, A-35, A-40 in `docs/assumptions.md` / `docs/assumption-audit.md`.
