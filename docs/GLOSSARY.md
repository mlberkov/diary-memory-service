# Glossary

Canonical vocabulary for the shared-memory core. D-041 fixes these terms; this file is the single reference the other docs link to. It **extends — and does not relax —** the D-026 boundary rule that use-case vocabulary must not leak into newly added core code.

## Core vocabulary

- **community** — the outer scope that owns a note corpus and bounds retrieval and authorship. A community has **one or more** participants: a one-person community is the individual-memory (solo) use case, a multi-person community is the shared/group use case. Solo and shared are the same concept at different sizes, not separate models.
- **subject** — a sub-entity within a community that a note can be *about*.
- **participant** — a person who belongs to a community and can author notes within it.

New **core** code adopts `community` / `subject` for the outer-scope and sub-entity concepts rather than ad-hoc generic names or use-case nouns (D-041, extending D-026).

## Author display name

The canonical author identity is the **opaque `author_user_id`** carried on `SourceMessage`, `Note`, and `EventChunk` (I-6). An **author display name** is a presentation-only rendering of that identity, resolved **only at the host adapter seam** (the Telegram adapter today) from host-supplied identity fields — for Telegram, the fallback chain `username → first_name → opaque short-ID`. Display names are host-supplied and **non-authoritative**; they never replace `author_user_id` in storage, retrieval, scoping, or provenance. See D-081 and `docs/assumptions.md` A-44.

## Author display input

The **host-supplied identity fields** (`username`, `first_name`) snapshotted at the adapter/storage seam at ingest time (D-082), used only as inputs to later adapter-side author-display-name resolution. They are **nullable** (a user may withhold either) and **non-authoritative** (a user may change them at any time); they are never a core field and never a substitute for `author_user_id`. The snapshot lands in a separate **Telegram-adapter-owned side table** written through an **adapter-owned storage port** distinct from the core `DomainRepository`, keyed by the message idempotency tuple `external_chat_id + external_message_id + edit_seq` as opaque scalars (D-083). See D-082, D-083 and `docs/assumptions.md` A-44.

## First-use-case mapping

The first implemented use case is a family/child diary in Telegram. Its use-case nouns map onto the core vocabulary as:

| Use-case noun | Core term |
| --- | --- |
| `family` | community |
| `child` | subject |
| `parent` | participant |

Use-case nouns (`family`, `child`, `parent`) stay in use-case-facing prose. They are not the core's definition — see D-026 and `docs/product/PRD.md` §1.

## Identifiers

The D-042 renaming roadmap (`docs/RENAMING-ROADMAP.md`) renamed the diary-shaped internal identifiers to the canonical vocabulary. The legacy names below are historical; code, schema, and tests now use the live names:

| Legacy identifier | Live identifier |
| --- | --- |
| `family_id` | `community_id` |
| `DiaryEntry` | `Note` |
| `entry_date` / `entry_text` | `note_date` / `note_text` |
| `diary_entry_id` | `note_id` |
| `ParsedEntry` / `parse_diary_entry` | `ParsedNote` / `parse_note` |
| `diary_entries` table | `notes` table |
| `RouteKind.ENTRY` / `detected_route='entry'` | `RouteKind.NOTE` / `detected_route='note'` |
| `DiaryRepository` | `DomainRepository` |
| `DiaryService` | `DomainService` |
| `*DiaryStore` / `HybridDiaryStore` | `*DomainStore` / `HybridDomainStore` |
| `core/diary/` module | `core/domain/` module |
| `diary_rag` package | `memory_rag` package |

`child_id` was never present in code; child scoping was born directly as `subject_id` — an opaque, community-scoped, nullable identifier whose contract is ratified by D-097 and whose code realization landed as Milestone H (see `docs/SUBJECT-SCOPING-ROADMAP.md`). `docs/INVARIANTS.md` and `docs/RUNTIME-INVARIANTS.md` describe the live identifier names — their wording matches what code enforces today. Naming the canonical terms here does not rename anything in code or schema.

## See also

- D-026 and D-041 in `docs/decision-log.md`.
- `docs/product/PRD.md` §1 "Canonical vocabulary (D-041)".
