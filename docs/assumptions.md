# Open Assumptions

Not yet locked. Each item must either be promoted to `docs/decision-log.md` (with the next D-### id) or explicitly deferred before the phase that depends on it begins.

Add new items here the moment one is identified. Do not let assumptions live only in code or chat.

## Storage & search
*A-5 → D-024. A-6 → D-025. A-7 → D-024. A-8 → D-024. A-9 → D-037.*

## Domain semantics
- **A-10. Edit/delete strategy**: TechSpec §12 explicitly leaves this open — revisions vs in-place mutation, tombstones vs hard delete, re-indexing trigger. Required before Phase 2.5.
- **A-11. Note grouping**: whether consecutive Telegram messages within a window can form one logical note, or each Telegram message is one note. PRD example shows a single multi-line message. Required before Phase 2.3.
- **A-12. Date parsing scope**: which date formats are accepted (ISO only? localized? relative like "yesterday"?). Required before Phase 2.3.
- **A-13. Timezone handling**: where the note timezone comes from (per-user setting, Telegram metadata, default). Required before Phase 2.3.
- **A-14. Family/child bootstrap**: how `Family` and `Child` records are first created — implicit on first message, or explicit `/setup`. Required before Phase 2.1.
- **A-15. Visibility scopes**: enumerated values for `visibility_scope` are undefined. Required before Phase 8.

## Routing & UX
*A-16 → D-020. A-17 → D-020.*

## Privacy & lifecycle
- **A-18. Data residency**: not stated.
- **A-19. Retention policy**: revision and trace retention are not bounded. Required before Phase 8.
- **A-20. Export/delete semantics**: directionally answered by D-027 for the export half — raw export on demand in JSON or TXT, scope-bounded. Remaining open: delivery channel per host (Telegram file reply / HTTP download / host-app screen), request shape, and the deletion half (still tied to A-10 edit/delete strategy).

## Integration target
- **A-21. TheyGrow integration surface**: HTTP API, in-process SDK, or message bus. Required before Phase 9.

## Operational
*A-22 → D-060.*
- **A-23. Backup strategy**: directionally answered by D-027 — daily backup window (`03:00–05:00` target) covering at minimum `source_messages` plus enough relational scaffolding to restore lineage, plus a stronger-than-nightly recovery primitive. The remaining open part — specific tooling and RPO/RTO targets — is resolved by D-053 (A-40 closed). Required before Phase 7/8.

## Naming & layout
- **A-25. Health endpoint contract**: `/health` currently returns `{status, version, env}`. The full set of boot health checks (PostgreSQL connectivity, schema version, embedding-model dimension — see R-10) lands in Phase 2/3. The Slice 1.1 endpoint is a liveness probe only.

## Adapter security
- **A-26. Webhook secret enforcement**: the `/telegram/webhook` endpoint fails closed when `TELEGRAM_WEBHOOK_SECRET` is unset or mismatched (returns 401). The `X-Telegram-Bot-Api-Secret-Token` header is compared with `secrets.compare_digest`.

## Mock contour (current)
- **A-28. Mock `/note` accepts ISO-only dates**: the date parser in `core/domain/parser.py` recognizes only `YYYY-MM-DD` on the first non-empty line. Anything else returns `INVALID_INPUT`. Precursor to A-12 (date parsing scope).
*A-29 → D-025.*
*A-30 → D-023.*
- **A-31. Mock per-route persistence**: in the current in-memory contour, only NOTE messages persist a `SourceMessage`; ASK and CLARIFY do not. This describes mock behavior only — it is not an architectural rule about durable storage. Per-route persistence semantics are an open design question for Phase 2 and are not bound by this assumption.

## Local Postgres contour (current)
- **A-33. Local Postgres durable contour**: with `STORAGE_BACKEND=postgres`, the service writes through `PostgresDomainStore` (psycopg3 sync + `psycopg_pool.ConnectionPool`) to the Postgres provided by `docker-compose.yml`. Schema is bootstrapped at construction by applying the versioned migrations under `src/memory_rag/storage/postgres/migrations/` to head via `yoyo-migrations` (OP-1.1 / D-045). Retrieval reuses the same case-insensitive substring contract as the mock (A-29), now executed against Postgres with `lower(chunk_text) LIKE %s`. Webhook idempotency (R-2) is enforced by `UNIQUE (external_chat_id, external_message_id, edit_seq)` plus `INSERT ... ON CONFLICT DO NOTHING` in `get_or_create_source_message` (D-023). SQLite remains opt-in for offline dev; the canonical durable target is Postgres (D-007 / D-022).

## Phase 3.1+3.2 indexing contour (current)
*A-35 → D-052 (OP-3 reconciliation — discovery OP-3.1 / D-050, retry OP-3.2a / D-051, exhausted-retry dead-letter routing OP-3.2b / D-052; failed embeddings are now discoverable, retryable, and dead-lettered).*
*A-36 → D-025 (replaced by A-36b — see below).*

## Phase 3.3 baseline-hybrid contour (current)
- **A-36b. 3072-dim ANN-index strategy remains open**: D-025 ships the dense leg as an exact community-scoped sequential scan over `vector(3072)`, which is correct at current diary scale and requires no schema churn. pgvector's HNSW / IVFFlat still cap at 2000 dim, so when corpus size demands ANN the choice is between `halfvec(3072)` + HNSW (small precision loss) or another approach. External vector DBs remain rejected on I-2 grounds. Revisit in the next quality-decision packet alongside BM25 / reranker / Qdrant evaluation.
*A-37 → D-039 (sparse dictionary `simple` retired for a dual-config `russian` + `english` tsvector union; no language detection).*

## Target-state architecture forks (opened by D-027)
- **A-38. Draft lifecycle semantics**: the lifecycle-representation slice is answered by D-028 — `SourceMessage.detected_route` is the lifecycle carrier (extended with `RouteKind.DRAFT`), and `core.routing.lifecycle_for` is the canonical mapping helper. D-030 cancels the **promotion slice** product-wide (drafts are not note-candidates; there is no `/promote` and no draft-to-note transition) and removes the explicit `/draft` command — drafts are created only by the no-command default and recalled via `/drafts`. Remaining open: how long a captured draft is retained and whether it expires by inactivity or by explicit cleanup. Required before the draft retention implementation packet. `/drafts` recall (D-030) uses a community-scoped sequential scan filtered by `detected_route='draft'`; a composite index on `(community_id, detected_route, created_at)` is a scale-driven follow-up, not committed here.
- **A-39. Raw export packaging and delivery**: D-027 commits the formats (JSON and TXT) and the scope (raw `SourceMessage` rows within the requester's scope); D-029 closes the Telegram-delivery-channel slice (outbound `sendDocument` via multipart upload) and the request-shape slice (synchronous, single-shot — no time-range arguments, no async generation). Remaining open: audit-row schema for export provenance, inclusion of derived state as an optional flag, time-range arguments and async generation when scale demands them, and delivery channels for non-Telegram hosts (HTTP download endpoint, host-app screen). Required before each respective follow-up packet.
- **A-41. Cloud-first reference environment** (open, **deferred until DEPLOY-2**): D-027 names managed cloud as a peer deployment shape; D-060 (DEPLOY-1.1) re-sequences the build order so the self-hosted VPS contour ships first (DEPLOY-1) and the managed cloud reference deployment is the deferred second peer (DEPLOY-2). The specific managed environment (managed Postgres provider, hosting platform, observability stack) is not named here and will be resolved by the DEPLOY-2 packet. Self-hosted OSS and embedded shapes remain peers with their own backend choices; D-026 / D-027 peer parity is preserved by D-060.

## DEPLOY-1 self-hosted reference shape (opened by D-060)
- **A-42. DEPLOY-1 invariants**: closed by D-060 — the DEPLOY-1 self-hosted VPS reference shape pins five invariants (OS family Debian / Ubuntu LTS; single-community / single-tenant default for the first pilot; public DNS + HTTPS required; off-box backup destination required, S3-compatible or equivalent — local-only does not qualify; operator-facing idempotent install/upgrade script). See `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` §2 for the mirrored invariant list and `docs/decision-log.md` D-060 for the authoritative statement.
- **A-43. Observability scope for the first VPS contour**: open. D-060 names a logs-first observability scope with a forward seam to remote sinks for the first DEPLOY-1 contour, but the specific surface and tooling are not pinned. Required before / pinned by the DEPLOY-1.x packet that ships observability (see `docs/SELF-HOSTED-DEPLOYMENT-ROADMAP.md` §4).

---

## Recently closed
- A-1 → D-016 (Python 3.11 as implementation language).
- A-2 → D-017 (`uv` as dependency and environment manager).
- A-3 → D-018 (Ruff + Mypy + Pytest as baseline toolchain).
- A-4 → D-019 (Telegram webhook transport, dev via tunnel).
- A-16 → D-020 (heuristic routing rule set with explicit confidence labels).
- A-17 → D-020 (CLARIFY reply naming both `/entry` and `/ask`).
- A-30 → D-023 (mock non-idempotent state; idempotency now enforced across all backends).
- A-32 → D-022 (Postgres replaces SQLite as the canonical durable backend; SQLite stays opt-in).
- A-5 → D-024 (pgvector chosen for dense storage).
- A-7 → D-024 (sync indexing on ingest).
- A-8 → D-024 (`text-embedding-3-large` @ 3072 dim).
- A-6 → D-025 (hybrid merge lives at the service layer via RRF).
- A-29 → D-025 (substring placeholder retired; baseline hybrid retrieval lands).
- A-36 → D-025 (replaced by A-36b; exact family-scoped scan for now, halfvec/HNSW deferred).
- A-9 → D-037 (`CHAT_MODEL` locked to `gpt-4.1` under `chat_backend=openai`; boot abort on mismatch).
- A-37 → D-039 (sparse FTS dictionary `simple` retired; dual-config `russian` + `english` tsvector union, no language detection).
- A-24 → D-042 (renaming roadmap; the R-4 packet renamed the package `diary_rag` → `memory_rag`).
- A-34 → D-046 (OP-1.2 — first non-destructive schema-changing upgrade migration `0002` applied over populated data without a destructive reset; OP-1 complete, the `docker compose down -v` upgrade contour retired for Postgres).
- A-35 → D-052 (OP-3 failed-embedding reconciliation complete — discovery, operator-run retry, and exhausted-retry routing into the `indexing_dead_letters` surface; sync indexing on ingest is unchanged).
- A-40 → D-053 (OP-4.1 — backup mechanism and recovery objectives resolved: nightly base backup + continuous WAL archiving → PITR for the reference Postgres shape, RPO ≤ 5 min / RTO ≤ 1 h, base backups retained 30 days; restore drill once before the first non-local deployment, then quarterly thereafter; OP-4 decomposed into OP-4.1/4.2/4.3).
- A-22 → D-060 (DEPLOY-1.1 — hosting target re-sequenced: self-hosted VPS first / DEPLOY-1, managed cloud as deferred second peer / DEPLOY-2; D-026 / D-027 peer parity preserved; A-41 stays open and is deferred until DEPLOY-2).
