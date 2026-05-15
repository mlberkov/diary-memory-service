# Identifier-Renaming Roadmap

## Purpose & status

This document is the detailed design artifact for the future renaming of the
diary-shaped internal identifiers to the canonical `community` / `subject`
vocabulary.

- **D-026** separated the use case from the core and promised an "explicit
  renaming packet" without naming a target.
- **D-041** named the destination vocabulary (`community`, `subject`,
  `participant`) and deferred the itemized migration path.
- **D-042** is that migration-path packet. It fixes — at contract level — the
  rename scope, the primary migration strategy, the A-34 dependency rule, and
  the definition of "rename complete", and points here for the detailed
  sequencing. See also `docs/GLOSSARY.md` for the canonical vocabulary.

This roadmap is **docs-only**. It renames nothing. The actual rename is a
separate future implementation milestone.

The packet sequence in §4 is the **current recommended roadmap** for that
milestone — not an immutable packet contract. Implementation-time planning may
refine the packet boundaries, provided it preserves the scope, migration
strategy, prerequisites, and completion bar fixed by D-042 (or amends D-042
with a new decision).

---

## 1. Scope axes (D-026)

Every candidate identifier is classified along the D-026 adapter axes:

- **core** — domain types, repositories, services, routing, the core package.
  These are renamed.
- **config** — environment / deployment keys carrying diary vocabulary. These
  are renamed.
- **adapter prose** — use-case-facing Telegram reply strings. These may
  legitimately keep use-case nouns (`docs/GLOSSARY.md`: use-case nouns stay in
  use-case-facing prose) and are **not** part of the core rename.

---

## 2. Identifier inventory

Scope = D-041's deferred identifier set plus the directly entailed surfaces.

### 2.1 `family` → community  (core)

| Surface | Identifier | Location |
| --- | --- | --- |
| DB columns | `family_id` | `src/diary_rag/storage/postgres/schema.sql`; SQLite DDL in `src/diary_rag/storage/sqlite/store.py` (on `diary_entries`, `event_chunks`, `embedding_records`, `queries`) |
| Core type fields | `family_id` | `DiaryEntry`, `SourceMessage`, `EventChunk`, `Query` in `src/diary_rag/core/diary/models.py`; `EmbeddingRecord` in `src/diary_rag/core/embeddings/models.py` |
| Helper | `_family_id_for` | adapter / dispatcher path |
| Eval harness | `family_id`, `family_id_default` | `src/diary_rag/eval/retrieval/harness.py`, `src/diary_rag/eval/retrieval/__main__.py`, and `gold.json` data |

### 2.2 `entry` → note  (core)

| Surface | Identifier | Location |
| --- | --- | --- |
| Core type | `DiaryEntry` | `src/diary_rag/core/diary/models.py` |
| Parser type / fn | `ParsedEntry`, `parse_diary_entry` | `src/diary_rag/core/diary/parser.py` |
| Type fields | `entry_date`, `entry_text`, `diary_entry_id` | `src/diary_rag/core/diary/models.py` (also `entry_date` on `EventChunk`, `Evidence`) |
| DB table / column | `diary_entries`, `diary_entry_id`, `entry_date`, `entry_text` | schema files + all three stores |
| Route kind | `RouteKind.ENTRY` | `src/diary_rag/core/routing/models.py` |
| Persisted route value | `detected_route='entry'` | `source_messages` rows + `detected_route` CHECK constraint |

### 2.3 `diary` container  (core)

| Surface | Identifier | Location |
| --- | --- | --- |
| Repository protocol | `DiaryRepository` | `src/diary_rag/storage/repository.py` |
| Store protocol | `HybridDiaryStore` | `src/diary_rag/storage/search_repository.py` |
| Store classes | `MockDiaryStore`, `SqliteDiaryStore`, `PostgresDiaryStore` | `src/diary_rag/storage/{mock,sqlite,postgres}/store.py` |
| Service | `DiaryService` | `src/diary_rag/services/diary_service.py` |
| Module directory | `core/diary/` | `src/diary_rag/core/diary/` |
| Package | `diary_rag` | `src/diary_rag/` |

### 2.4 Config keys  (config)

| Identifier | Location |
| --- | --- |
| `postgres_db` default `theygrow_diary_rag` | `src/diary_rag/config.py` |
| `sqlite_path` default `./data/diary.db` | `src/diary_rag/config.py` |
| `POSTGRES_DB` env | `docker-compose.yml` |

### 2.5 Prospective — `child` → subject

`child_id` is **not present in code today**; scoping is currently `family_id`
only. When the deferred D-040 child-filter packet introduces child scoping, it
must be born directly as `subject_id`. No rename packet is needed for it.

### 2.6 Explicitly out of roadmap scope

- `EventChunk` / `event_chunks` / `event_index` — `event` is a generic term,
  not D-026 use-case vocabulary, and is absent from D-041's deferred list.
  Left unchanged.
- Telegram reply strings ("diary mode", "diary chunks", etc.) — use-case-facing
  adapter prose; may keep use-case nouns.

---

## 3. Target-name mapping

Vocabulary strength is marked per row.

| From | To | Strength |
| --- | --- | --- |
| `family`, `family_id` | `community`, `community_id` | **canonical** — `community` fixed by D-041 |
| `child`, `child_id` (prospective) | `subject`, `subject_id` | **canonical** — `subject` fixed by D-041 |
| `parent` / author terms | `participant` | **canonical** — `participant` fixed by D-041 |
| `entry`, `entry_date`, `entry_text`, `diary_entry_id`, `diary_entries` | `note`, `note_date`, `note_text`, `note_id`, `notes` | **recommended target** — `note` is the current recommended replacement for `entry`; not canonized by this packet |
| `DiaryEntry`, `ParsedEntry`, `parse_diary_entry` | `Note`, `ParsedNote`, `parse_note` | **recommended target** — follows the `entry`→`note` choice |
| `DiaryRepository`, `*DiaryStore`, `HybridDiaryStore`, `DiaryService` | `NoteRepository`, `*NoteStore`, `HybridNoteStore`, `NoteService` | **recommended target** |
| `RouteKind.ENTRY`, `detected_route='entry'` | `RouteKind.NOTE`, `detected_route='note'` | **recommended target** |
| `diary_rag` package, `core/diary/` dir | a generic core package / module name | **proposed** — confirm at execution time |

`community` / `subject` / `participant` are settled; the executing packets
rename against them directly. `note` and the package name are the current
best recommendation and may be re-confirmed (or replaced) when the executing
packet runs — they are not canonized by D-042.

---

## 4. Recommended implementation roadmap

The recommended packets are **concept-by-concept**: each renames one concept
across every layer atomically (type, store, schema, tests), so there is no
intermediate state needing a store-layer field↔column translation shim. The
sequence is recommended; the constraints it embodies (concept-by-concept
atomicity; schema-touching steps ride the destructive reset; invariants/docs
alignment last) are fixed by D-042.

| Packet | Concept | Preconditions | Validation |
| --- | --- | --- | --- |
| **R-1** | `diary`-container code identifiers — `DiaryRepository`, `*DiaryStore`, `HybridDiaryStore`, `DiaryService`, `core/diary/` directory. Pure code; no schema; no reset. | D-042 merged; target names confirmed against `docs/GLOSSARY.md`. | `make check`; import sanity. |
| **R-2** | `entry` → `note` — types, parser, `RouteKind.ENTRY`, persisted `detected_route='entry'` + CHECK constraint, `diary_entries` table and its columns. First destructive-reset packet. | R-1 merged; pre-deployment / destructive-reset contour confirmed (§5). | `make check`; store parity tests; fresh-env bootstrap. |
| **R-3** | `family` → `community` — `family_id` across all tables, type fields, `_family_id_for`, eval harness + `gold.json`. Largest blast radius — run after the rename workflow is proven. | R-1, R-2 merged. | `make check`; store parity; fresh-env bootstrap; confirm the scoping invariant (INVARIANTS I-7) still holds under the new column name. |
| **R-4** | Package + config — `diary_rag` package → new core package name, `postgres_db` / `sqlite_path` / `POSTGRES_DB` / `docker-compose.yml`. Mechanical, broad. | R-1–R-3 merged. | `make check`; fresh-env bootstrap. |
| **R-5** | Invariants & canonical-docs alignment + cleanup — `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` wording, TechSpec §5 entity names, ARCHITECTURE, execution-map nouns, GLOSSARY "Identifiers" section (legacy names → historical), remove transitional notes in TechSpec §4/§5. | R-1–R-4 merged & green. | Cross-reference consistency; `grep` scoped to active surfaces confirms legacy tokens are gone (excluding negative tests and historical decision-log narration). |

Implementation-time planning may split or merge these packets — for example,
splitting R-3 if `family_id`'s breadth proves unwieldy — as long as each
resulting packet still renames a whole concept atomically and the ordering
constraints above are preserved.

---

## 5. Prerequisites & A-34 dependency

- **Target names confirmed.** `community` / `subject` / `participant` are
  fixed; `note` and the replacement package name are confirmed at the start of
  R-2 / R-4 respectively.
- **Local data is disposable.** The recommended path assumes all data is local
  and seedable from scratch when the schema-touching packets (R-2, R-3) run.
- **A-34 dependency rule.** A-34 (no migration tool; local schema upgrades are
  destructive) is **not a hard blocker** for this rename: R-2 and R-3 ride the
  destructive-reset contour A-34 already documents. The *conditional*
  precondition for R-2/R-3 is that no non-local deployment holding
  irreplaceable data exists when they run. **If that precondition fails** (the
  rename slips past the first non-local deployment), R-2/R-3 are blocked until
  A-34 is resolved with migration tooling, and the migration strategy switches
  to expand-contract (§6).
- **Staging environment** is *not* required for the recommended path.

---

## 6. Migration strategy

- **Primary (recommended).** Destructive local reset per schema-touching
  packet: `docker compose down -v` for Postgres, delete the SQLite file,
  re-seed from scratch. Valid because the rename is expected to land before
  any non-local deployment, while data is disposable.
- **Secondary (fallback).** If the rename must happen *after* a non-local
  deployment with real data, an expand-contract dual-read/write migration via
  migration tooling (A-34 resolution, e.g. an Alembic-style system) is
  required instead. This is noted for completeness; the recommended path is
  "rename before staging/prod".

---

## 7. Definition of "rename complete"

The rename is complete when:

1. No core code, schema, migration, or test references a legacy identifier
   from §2.1–§2.4 — verified by a `grep` scoped to active surfaces (excluding
   negative tests and historical decision-log narration).
2. `docs/INVARIANTS.md` / `docs/RUNTIME-INVARIANTS.md` wording names the new
   identifiers and matches what code enforces.
3. The `docs/GLOSSARY.md` "Identifiers" section lists the legacy names as
   historical, with their live mapping.
4. `make check` is green and a fresh-environment bootstrap succeeds.

Use-case-facing adapter prose (Telegram reply strings) retaining use-case
nouns is explicitly **not** a blocker for completeness.

---

## See also

- D-026, D-041, D-042 in `docs/decision-log.md`.
- `docs/GLOSSARY.md` — canonical `community` / `subject` / `participant`
  vocabulary and the first-use-case mapping.
- A-34 in `docs/assumptions.md` / `docs/assumption-audit.md`.
