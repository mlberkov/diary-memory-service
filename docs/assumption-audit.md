# Assumption Audit

When an item is decided, move it to `docs/decision-log.md` (next D-### id) and remove or strike its row here.

| ID | Assumption | Risk if wrong | Validation method | Owner | Due by |
| --- | --- | --- | --- | --- | --- |
| ~~A-1~~ | ~~Python 3.11+ as implementation language~~ | — | — | — | Closed → D-016 |
| ~~A-2~~ | ~~Dependency manager TBD~~ | — | — | — | Closed → D-017 |
| ~~A-3~~ | ~~Test/format/type toolchain TBD~~ | — | — | — | Closed → D-018 |
| ~~A-4~~ | ~~Telegram transport: webhook (local-dev TBD)~~ | — | — | — | Closed → D-019 |
| ~~A-5~~ | ~~pgvector + Postgres FTS for hybrid~~ | — | — | — | Closed → D-024 (dense via pgvector; sparse remains A-6) |
| A-6 | Hybrid merge location (DB vs app) | Latency + correctness | Prototype merge in code vs SQL | agent | Phase 3.3 |
| ~~A-7~~ | ~~Sync vs async indexing~~ | — | — | — | Closed → D-024 (sync on ingest) |
| ~~A-8~~ | ~~Embedding model & dim~~ | — | — | — | Closed → D-024 (`text-embedding-3-large` @ 3072) |
| A-9 | Chat model | Quality, cost, fallback compatibility | Smoke + eval in Phase 4 | agent | Phase 4 |
| A-10 | Edit/delete strategy | Data loss / duplication | Spec + small prototype | human + agent | Phase 2.5 |
| A-11 | Entry grouping rule | Wrong split/merge of entries | Walk 10 sample sessions | human | Phase 2.3 |
| A-12 | Date parsing scope | Misclassification of entries | List supported formats + tests | agent | Phase 2.3 |
| A-13 | Timezone source | Wrong `entry_date` | Spec + tests | agent | Phase 2.3 |
| A-14 | Family/child bootstrap | UX confusion; orphan records | Define onboarding flow | human | Phase 2.1 |
| A-15 | Visibility scopes | Privacy gaps in shared mode | Enumerate + review | human | Phase 8 |
| A-16 | Routing confidence threshold | Misclassification or noise | Heuristic + small eval | agent | Phase 1.4 |
| A-17 | Clarification UX | User confusion | Mock chat exchange + review | human | Phase 1.4 |
| A-18 | Data residency | Compliance failure | Stakeholder confirmation | human | before prod |
| A-19 | Retention policy | Storage growth; user trust | Policy doc + sample math | human | Phase 8 |
| A-20 | Export/delete semantics | Compliance, trust | Spec + prototype | human | Phase 8 |
| A-21 | TheyGrow integration surface | Integration cost | API/SDK sketch | human | Phase 9 |
| A-22 | Hosting target | Operational rework | Decision + runbook update | human | Phase 6 |
| A-23 | Backup strategy | Data loss | Drill + runbook | human | Phase 7 |
| A-24 | Python package name `diary_rag` | Rename cost grows over time | Confirm before Phase 9 integration surface | human | Phase 9 |
| A-25 | `/health` is liveness-only at 1.1 | Misleading readiness signal | Replace with R-10 readiness checks | agent | Phase 2/3 |
| A-26 | Webhook fails closed when `TELEGRAM_WEBHOOK_SECRET` is unset or mismatched | Open webhook accepts spoofed traffic | Verified in Slice 1.2 secret-header tests | agent | end of Phase 1 |
| A-28 | Mock `/entry` accepts ISO-only `YYYY-MM-DD` on first line | Demos misclassify locale dates / relative dates as invalid | Replaced by A-12 decision (Phase 2.3) | agent | Phase 2.3 |
| A-29 | Mock retrieval is case-insensitive substring match | Wrong recall/precision shape sets bad expectations | Replaced by hybrid retrieval (A-5/A-6) | agent | Phase 3 |
| ~~A-30~~ | ~~Mock state is process-local and non-idempotent~~ | — | — | — | Closed → D-023 |
| A-34 | No migration tool; local schema upgrades are destructive | Production schema evolution unsafe; dev volume drops feel like data loss | Document destructive upgrade in RUNBOOK; revisit before non-local deploy | agent | before prod |
