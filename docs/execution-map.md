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
| 1.1 language & toolchain | `pyproject.toml` (Py 3.11, D-016), `.python-version`, `uv` lockfile (D-017), Ruff + Mypy + Pytest configs (D-018); `Makefile` `format`/`lint`/`typecheck`/`test`/`check`/`run`; `src/diary_rag/{config,logging,app,__main__}.py`; placeholders `adapters/telegram/`, `core/routing/`, `services/`, `storage/mock/` (with `InMemorySourceMessageStore` stub); FastAPI `/health` smoke; `tests/test_smoke.py`, `test_config.py`, `test_app_health.py`, `test_mock_store.py` |
| 1.2 Telegram adapter shell | `POST /telegram/webhook` (D-019) with secret-token gating; `adapters/telegram/{webhook,models,commands,reply}.py`; channel-neutral `core/routing/models.py` (`RouteKind`, `InboundMessage`, `DispatchResult`); `services/dispatcher.py` with stub handlers; tests `test_telegram_{commands,models,reply,webhook_secret,dispatch}.py`; dev-tunnel docs in `QUICKSTART.md` |
| 1.3 mock services | `MockSourceMessageRepository`, `MockSearchRepository`, `MockEmbeddingClient`, `MockChatClient` (replaces 1.1 stub) |
| 1.4 routing | command + heuristic routing, low-confidence clarification path |
| 1.5 mock end-to-end | smoke run exercising `/entry` and `/ask` against mocks |

## Phase 2 — Durable Backend Core
| Slice | Files / artifacts |
| --- | --- |
| 2.1 schema (identities) | initial migration: `users`, `families`, `children`, `telegram_chats`, `source_messages` |
| 2.2 schema (entries) | migration: `diary_entries`, `event_chunks` with lineage |
| 2.3 ingestion pipeline | parser (`parse_version`), event splitter, chunk creation; raw persisted first (I-3, R-1) |
| 2.4 idempotent webhook | replay-safe handler keyed on `(telegram_chat_id, telegram_message_id, edit_seq)` |
| 2.5 edit/delete strategy | implementation of the decision recorded for TechSpec §12 (assumption A-10) |
| 2.6 stage status tracking | per-record `parse_status`, `embedding_status`, `index_status` |

## Phase 3 — Embeddings and Hybrid Retrieval
| Slice | Files / artifacts |
| --- | --- |
| 3.1 embedding adapter | `EmbeddingClient`, OpenAI implementation, dimension check at boot (R-10) |
| 3.2 indexing pipeline | sync or async path (assumption A-7); `embedding_records` storage |
| 3.3 hybrid retrieval | `SearchRepository` with dense + sparse (assumption A-5/A-6) |
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
