# Assumption Audit

When an item is decided, move it to `docs/decision-log.md` (next D-### id) and remove or strike its row here.

| ID | Assumption | Risk if wrong | Validation method | Owner | Due by |
| --- | --- | --- | --- | --- | --- |
| ~~A-1~~ | ~~Python 3.11+ as implementation language~~ | — | — | — | Closed → D-016 |
| ~~A-2~~ | ~~Dependency manager TBD~~ | — | — | — | Closed → D-017 |
| ~~A-3~~ | ~~Test/format/type toolchain TBD~~ | — | — | — | Closed → D-018 |
| ~~A-4~~ | ~~Telegram transport: webhook (local-dev TBD)~~ | — | — | — | Closed → D-019 |
| ~~A-5~~ | ~~pgvector + Postgres FTS for hybrid~~ | — | — | — | Closed → D-024 (dense via pgvector; sparse remains A-6) |
| ~~A-6~~ | ~~Hybrid merge location (DB vs app)~~ | — | — | — | Closed → D-025 (service-layer RRF) |
| ~~A-7~~ | ~~Sync vs async indexing~~ | — | — | — | Closed → D-024 (sync on ingest) |
| ~~A-8~~ | ~~Embedding model & dim~~ | — | — | — | Closed → D-024 (`text-embedding-3-large` @ 3072) |
| A-9 | Chat model | Quality, cost, fallback compatibility | Smoke + eval in Phase 4 | agent | Phase 4 |
| A-10 | Edit/delete strategy | Data loss / duplication | Spec + small prototype | human + agent | Phase 2.5 |
| A-11 | Note grouping rule | Wrong split/merge of notes | Walk 10 sample sessions | human | Phase 2.3 |
| A-12 | Date parsing scope | Misclassification of notes | List supported formats + tests | agent | Phase 2.3 |
| A-13 | Timezone source | Wrong `note_date` | Spec + tests | agent | Phase 2.3 |
| A-14 | Family/child bootstrap | UX confusion; orphan records | Define onboarding flow | human | Phase 2.1 |
| A-15 | Visibility scopes | Privacy gaps in shared mode | Enumerate + review | human | Phase 8 |
| ~~A-16~~ | ~~Routing confidence threshold~~ | — | — | — | Closed → D-020; heuristic plain-text NOTE/ASK auto-routing retired → D-078 / enforced in code → D-079 (command-less plain text routes only to the draft floor) |
| ~~A-17~~ | ~~Clarification UX~~ | — | — | — | Closed → D-020; after D-078 CLARIFY survives only as an explicit-command active-conflict reply (not a plain-text route — dormant since D-028) |
| A-18 | Data residency | Compliance failure | Stakeholder confirmation | human | before prod |
| A-19 | Retention policy | Storage growth; user trust | Policy doc + sample math | human | Phase 8 |
| A-20 | Export/delete semantics — export half directionally answered by D-027 (raw export in JSON or TXT, scope-bounded); remaining open: delivery channel and the deletion half (see A-39, A-10) | Compliance, trust | Spec + prototype | human | Phase 8 |
| A-21 | TheyGrow integration surface | Integration cost | API/SDK sketch | human | Phase 9 |
| ~~A-22~~ | ~~Hosting target — directionally answered by D-027 (managed cloud as default; OSS and embedded as peers); remaining open: which specific managed environment (see A-41)~~ | — | — | — | Closed → D-060 (DEPLOY-1.1 — self-hosted VPS first / DEPLOY-1; managed cloud as deferred second peer / DEPLOY-2; D-026 / D-027 peer parity preserved; A-41 stays open and is deferred until DEPLOY-2) |
| A-23 | Backup strategy — directionally answered by D-027 (daily window `03:00–05:00` + stronger-than-nightly recovery); the remaining tooling + RPO/RTO part is resolved by D-053 (A-40 closed) | Data loss | Drill + runbook | human | Phase 7 |
| ~~A-24~~ | ~~Python package name `diary_rag`~~ | — | — | — | Closed → D-042 (renaming roadmap; R-4 renamed `diary_rag` → `memory_rag`) |
| A-25 | `/health` is liveness-only at 1.1 | Misleading readiness signal | Replace with R-10 readiness checks | agent | Phase 2/3 |
| A-26 | Webhook fails closed when `TELEGRAM_WEBHOOK_SECRET` is unset or mismatched | Open webhook accepts spoofed traffic | Verified in Slice 1.2 secret-header tests | agent | end of Phase 1 |
| A-28 | Mock `/note` accepts ISO-only `YYYY-MM-DD` on first line (heuristic NOTE auto-route consumer retired → D-078; `/note`-without-date→today landed → D-085 in the dispatcher seam, INVALID_INPUT now only for empty/whitespace `/note`; parser strictness unchanged so the row stays open) | Demos misclassify locale dates / relative dates as invalid | Replaced by A-12 decision (Phase 2.3) | agent | Phase 2.3 |
| ~~A-29~~ | ~~Mock retrieval is case-insensitive substring match~~ | — | — | — | Closed → D-025 (baseline hybrid retrieval lands) |
| ~~A-30~~ | ~~Mock state is process-local and non-idempotent~~ | — | — | — | Closed → D-023 |
| ~~A-34~~ | ~~No migration tool; local schema upgrades are destructive~~ | — | — | — | Closed → D-046 (OP-1.2 — non-destructive schema-changing upgrade `0002` demonstrated over populated data; OP-1 complete) |
| A-36b | 3072-dim ANN index strategy deferred | Latency at scale once corpus grows past exact-scan budget | Next quality-decision packet: halfvec(3072)+HNSW vs other | agent | next quality-decision packet |
| ~~A-37~~ | ~~Sparse FTS dictionary `simple` (no stemming)~~ | — | — | — | Closed → D-039 (dual-config `russian` + `english` tsvector union; no detection) |
| A-38 | Draft lifecycle semantics (retention, expiry, promotion mechanic, lifecycle field on `SourceMessage`) | Drafts leak forever or expire silently; promotion path is ambiguous | Spec + small prototype alongside draft routing implementation | human + agent | draft routing implementation packet |
| A-39 | Raw export packaging and delivery (per-host channel, request shape, audit-row schema, optional derived-state flag) | Export usable in one host but not another; audit gaps | Spec + prototype alongside export implementation | human + agent | export implementation packet |
| ~~A-40~~ | ~~Backup tooling and recovery objectives (WAL archiving vs replicas vs managed PITR; RPO/RTO; restore-drill cadence)~~ | — | — | — | Closed → D-053 (OP-4.1 — nightly base backup + continuous WAL archiving → PITR; RPO ≤ 5 min / RTO ≤ 1 h; restore drill once before the first non-local deployment, then quarterly thereafter) |
| A-41 | Cloud-first reference environment (managed Postgres provider, hosting platform, observability stack) — open, **deferred until DEPLOY-2** by D-060 (DEPLOY-1.1 re-sequences the build order: self-hosted VPS first / DEPLOY-1, managed cloud second peer / DEPLOY-2) | Managed-cloud peer-shape rollout blocked or rework | Stakeholder confirmation + runbook update | human | DEPLOY-2 |
| A-42 | DEPLOY-1 invariants (Debian / Ubuntu LTS; single-community / single-tenant default; public DNS + HTTPS required; off-box backup destination required, S3-compatible or equivalent; operator-facing idempotent install/upgrade script) | Stack drift; later DEPLOY-1.x packets re-deciding architecture | Mirrored in `SELF-HOSTED-DEPLOYMENT-ROADMAP.md` §2; each DEPLOY-1.x packet cites this invariant set | agent | Closed → D-060 |
| ~~A-43~~ | ~~Observability scope for the first DEPLOY-1 VPS contour (logs-first with a forward seam to remote sinks; specific surface and tooling not pinned)~~ | — | — | — | Closed → D-077 (DEPLOY-1 logs-first observability pinned to the existing `pg_backup.*` / Caddy access / `telegram.webhook` / `retrieval.hybrid` / `answer.*` log families; no new logging contract in `src/`; forward seam to remote sinks deliberately unpinned and deferred) |
| A-44 | Author display-name resolution (adapter-only resolution; fallback `username → first_name → opaque short-ID`; host-supplied / non-authoritative; `/sources` is the sole milestone surface; answer-reply attribution deferred) | Telegram display name mistaken for identity; inconsistent / missing attribution across surfaces | Spec + prototype alongside the author display-name capture / rendering packet; capture/persistence shape pinned by D-082; landing seam pinned by D-083 (Option A — adapter-owned side table + port); capture + durable landing implemented by D-084 | human + agent | author display-name capture / rendering packet (opened → D-081; capture/persistence shape pinned → D-082; landing seam pinned → D-083; capture + durable landing implemented → D-084; resolution/rendering still open) |
