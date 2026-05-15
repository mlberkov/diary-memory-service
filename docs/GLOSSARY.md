# Glossary

Canonical vocabulary for the shared-memory core. D-041 fixes these terms; this file is the single reference the other docs link to. It **extends — and does not relax —** the D-026 boundary rule that use-case vocabulary must not leak into newly added core code.

## Core vocabulary

- **community** — the outer scope that owns a note corpus and bounds retrieval and authorship. A community has **one or more** participants: a one-person community is the individual-memory (solo) use case, a multi-person community is the shared/group use case. Solo and shared are the same concept at different sizes, not separate models.
- **subject** — a sub-entity within a community that a note can be *about*.
- **participant** — a person who belongs to a community and can author notes within it.

New **core** code adopts `community` / `subject` for the outer-scope and sub-entity concepts rather than ad-hoc generic names or use-case nouns (D-041, extending D-026).

## First-use-case mapping

The first implemented use case is a family/child diary in Telegram. Its use-case nouns map onto the core vocabulary as:

| Use-case noun | Core term |
| --- | --- |
| `family` | community |
| `child` | subject |
| `parent` | participant |

Use-case nouns (`family`, `child`, `parent`) stay in use-case-facing prose. They are not the core's definition — see D-026 and `docs/product/PRD.md` §1.

## Identifiers

Existing internal identifiers keep their historical names until their own renaming packet (D-026; the ordered, non-destructive roadmap is the next packet of the D-041 milestone). These include `family_id`, `child_id`, `DiaryEntry`, `entry_date` / `entry_text`, `parse_diary_entry`, `DiaryRepository`, the `diary_rag` package, and `RouteKind.ENTRY` / `detected_route='entry'`.

`docs/INVARIANTS.md` and `docs/RUNTIME-INVARIANTS.md` therefore still describe these current identifier names: their wording matches what code enforces today, not the target vocabulary. Naming the canonical terms here does not rename anything in code or schema.

## See also

- D-026 and D-041 in `docs/decision-log.md`.
- `docs/product/PRD.md` §1 "Canonical vocabulary (D-041)".
