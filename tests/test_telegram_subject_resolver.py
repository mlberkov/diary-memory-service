"""Adapter-owned community→subject resolver (H-2; D-097).

Pins the single named seam and its default single-subject mapping. Under
the default, one subject per community is community-wide is ``None``
(D-097 §3) — so assignment is behavior- and data-preserving today. The
optional subject retrieval filter is H-3, not here.
"""

from __future__ import annotations

from memory_rag.adapters.telegram.subject import resolve_subject_id


def test_default_mapping_is_community_wide_none() -> None:
    # Single-subject per community → community-wide → None.
    assert resolve_subject_id("42") is None


def test_returns_none_for_any_community() -> None:
    for community_id in ("", "-100123", "fam-A", "  spaces  "):
        assert resolve_subject_id(community_id) is None


def test_return_type_is_opaque_str_or_none() -> None:
    result = resolve_subject_id("community-42")
    assert result is None or isinstance(result, str)
