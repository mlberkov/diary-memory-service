# Execution Map — Phases → Files → Slices

Files listed are *targets*. Most do not exist yet. Each row will be split into one or more entries in `docs/todo.md` as the work approaches. Phase headers mirror `docs/product/BuildPlan.md`.

## Phase 0 — Operating Setup
| Slice | Files / artifacts |
| --- | --- |
| 0.1 canonical docs | `docs/product/PRD.md`, `docs/product/BuildPlan.md`, `docs/product/TechSpec.md`, `docs/decision-log.md`, `AGENTS.md`, `CLAUDE.md` |
| 0.2 supporting docs | `README.md`, `QUICKSTART.md`, `docs/ARCHITECTURE.md`, `docs/INVARIANTS.md`, `docs/RUNTIME-INVARIANTS.md`, `docs/CHECKLIST.md`, `docs/RUNBOOK.md`, `docs/execution-map.md`, `docs/assumptions.md`, `docs/assumption-audit.md`, `docs/todo.md` |
| 0.3 scaffold review | `Makefile`, `.env.example`, `.gitignore` |

## Phase 1 — Telegram Shell and Mock Flow
| Slice | Files / artifacts |
| --- | --- |
| 1.1 language & toolchain | `pyproject.toml` (Py 3.11, D-016), `.python-version`, `uv` lockfile (D-017), Ruff + Mypy + Pytest configs (D-018); `Makefile` `format`/`lint`/`typecheck`/`test`/`check`/`run`; `src/diary_rag/{config,logging,app,__main__}.py`; placeholders `adapters/telegram/`, `core/routing/`, `services/`, `storage/mock/`; FastAPI `/health` smoke; `tests/test_smoke.py`, `test_config.py`, `test_app_health.py` |
| 1.2 Telegram adapter shell | `POST /telegram/webhook` (D-019) with secret-token gating; `adapters/telegram/{webhook,models,commands,reply}.py`; channel-neutral `core/routing/models.py` (`RouteKind`, `InboundMessage`, `DispatchResult`); `services/dispatcher.py` with stub handlers; tests `test_telegram_{commands,models,reply,webhook_secret,dispatch}.py`; dev-tunnel docs in `QUICKSTART.md` |
| 1.3 mock services | `core/diary/{models,parser}.py` (channel-neutral dataclasses + ISO date parser); `storage/mock/store.py` (`MockDiaryStore` with deterministic substring search); `services/{diary_service,query_service}.py`; `Dispatcher` wires `ENTRY`/`ASK` to those services. `MockEmbeddingClient` / `MockChatClient` deferred until 3.1/4.1 sketch the real shapes |
| 1.4 routing | `core/routing/classifier.py` (deterministic ENTRY/ASK/CLARIFY) reusing `core/diary/parser.parse_diary_entry`; `RouteKind.CLARIFY`, `RouteSource`, required `InboundMessage.route_source`; webhook calls classifier on UNKNOWN+text; `services/dispatcher.py` adds CLARIFY handler and heuristic markers; `services/query_service.py` adds terminal-punctuation strip; `tests/test_routing_classifier.py`; new heuristic + command-wins-over-heuristic cases in `test_telegram_dispatch.py`; CLARIFY/marker assertions in `test_telegram_reply.py`. Closes A-16/A-17 via D-020. |
| 1.5 mock end-to-end | webhook smoke: `/entry` then `/ask` returns grounded-style reply with date and matched line; heuristic ENTRY/ASK/CLARIFY flows added to `tests/test_end_to_end_smoke.py` and the curl recipe in `QUICKSTART.md`. |

## Phase 2 — Durable Backend Core
| Slice | Files / artifacts |
| --- | --- |
| 2.0 canonical local Postgres backend | `src/diary_rag/storage/postgres/{__init__,store}.py`, `src/diary_rag/storage/postgres/schema.sql`, `docker-compose.yml`, `tests/test_postgres_store.py`; `_build_store` postgres branch in `adapters/telegram/webhook.py`; `Settings.postgres_dsn()` (D-022) |
| 2.1 schema (identities) | initial migration: `users`, `families`, `children`, `telegram_chats`, `source_messages` |
| 2.2 schema (entries) | migration: `diary_entries`, `event_chunks` with lineage |
| 2.3 ingestion pipeline | parser (`parse_version`), event splitter, chunk creation; raw persisted first (I-3, R-1) |
| 2.4 idempotent webhook | `DiaryRepository.get_or_create_source_message` keyed on `(external_chat_id, external_message_id, edit_seq)`; `UNIQUE` constraint + `INSERT ... ON CONFLICT DO NOTHING` (Postgres) / `INSERT OR IGNORE` (SQLite) / dict dedupe (mock); `DiaryService.ingest` short-circuits on replay; webhook logs `effective_path=fresh|replay`; D-023 |
| 2.5 edit/delete strategy | implementation of the decision recorded for TechSpec §12 (assumption A-10) |
| 2.6 stage status tracking | per-record `parse_status`, `embedding_status`, `index_status` |

## Phase 3 — Embeddings and Hybrid Retrieval
| Slice | Files / artifacts |
| --- | --- |
| 3.1+3.2 embedding adapter + sync indexing | `core/embeddings/{client,models}.py` (`EmbeddingClient` Protocol, `EmbeddingRecord`, `EmbeddingStatus`); `adapters/embeddings/{mock,openai_client,factory}.py`; `event_chunks.embedding_status` column + `embedding_records` table with `vector(3072)`; pgvector image swap in `docker-compose.yml`; boot dimension + pgvector probe (R-10); `DiaryService` calls embedding client after `save_event_chunks`; failure → `embedding_status='failed'`; replay short-circuits before embedding. Closes A-5 / A-7 / A-8 via D-024; opens A-35 / A-36 |
| 3.3 hybrid retrieval | `SearchRepository` with dense + sparse (assumption A-6); 3072-dim ANN strategy fork (A-36) |
| 3.4 metadata filtering | family / child / visibility / date filters (I-7) |
| 3.5 retrieval traces | `RetrievalHit` rows; debug command for inspecting top-k |

## Phase 4 — Grounded Answer Pipeline
| Slice | Files / artifacts |
| --- | --- |
| 4.1 context assembler | top-k selection, dedup, optional date grouping |
| 4.2 answer prompt contract | versioned prompt, structured answer schema |
| 4.3 fallback modes | no-evidence, weak-evidence, ambiguous, provider-unavailable (I-9, R-5, R-6) |
| 4.4 evidence rendering | Telegram-side reply formatter with citations |

## Phase 5 — Optional AI Quality Boosters
| Slice | Files / artifacts |
| --- | --- |
| 5.1 feature-flag system | flag registry, per-request resolution, log of effective flags (R-12) |
| 5.2 query rewriting | rewriter behind flag |
| 5.3 reranking | reranker behind flag |
| 5.4 answer modes | timeline mode, analytical synthesis mode |

## Phase 6 — Provider Hardening
| Slice | Files / artifacts |
| --- | --- |
| 6.1 timeouts & retries | bounded retry policy, classified errors (R-9) |
| 6.2 dead-letter | failed indexing jobs survive and are inspectable |
| 6.3 rate-limit handling | backoff and observability |

## Phase 7 — Evaluation and Observability
| Slice | Files / artifacts |
| --- | --- |
| 7.1 gold eval set | curated questions + expected evidence chunks |
| 7.2 retrieval & groundedness metrics | hit-rate, empty-rate, groundedness check |
| 7.3 cost & latency | token + latency aggregation |

## Phase 8 — Privacy and Shared-Diary Controls
| Slice | Files / artifacts |
| --- | --- |
| 8.1 family-scoped access | enforced at every read (I-7, R-3) |
| 8.2 visibility model | per-entry scopes (assumption A-15) |
| 8.3 export/delete flow | tombstones + audit log + retention policy |

## Phase 9 — TheyGrow Integration Seam
| Slice | Files / artifacts |
| --- | --- |
| 9.1 internal API/SDK | non-Telegram client surface (assumption A-21) |
| 9.2 identity mapping | family / child mapping into TheyGrow identities |
| 9.3 isolation audit | confirm no Telegram leakage outside the adapter (I-1) |
