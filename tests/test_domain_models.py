"""Unit tests for ``core/domain`` value objects.

Covers the ``DateRange`` retrieval-filter value object (Slice 3.4,
D-040): both bounds optional and inclusive, both-``None`` is a valid
no-constraint range, and a contradictory ``start > end`` range is
rejected at construction. Also pins the H-1 (D-097) ``subject_id``
contract: an opaque, nullable scope field that defaults to ``None``
(``None`` = community-wide) on ``Note`` and ``EventChunk``, and the
RC-3 ``AnswerResult.model_text`` additive default (``None`` on every
pre-existing contour).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime

import pytest

from memory_rag.core.domain.models import AnswerResult, DateRange, EventChunk, FallbackMode, Note

_EARLY = date(2026, 5, 10)
_LATE = date(2026, 5, 12)


def test_both_none_constructs() -> None:
    assert DateRange() == DateRange(start=None, end=None)


def test_only_lower_bound_constructs() -> None:
    rng = DateRange(start=_EARLY)
    assert rng.start == _EARLY
    assert rng.end is None


def test_only_upper_bound_constructs() -> None:
    rng = DateRange(end=_LATE)
    assert rng.start is None
    assert rng.end == _LATE


def test_equal_bounds_single_day_is_valid() -> None:
    rng = DateRange(start=_EARLY, end=_EARLY)
    assert rng.start == rng.end == _EARLY


def test_start_after_end_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"start must be <= end"):
        DateRange(start=_LATE, end=_EARLY)


def test_date_range_is_frozen() -> None:
    rng = DateRange(start=_EARLY, end=_LATE)
    with pytest.raises(dataclasses.FrozenInstanceError):
        rng.start = _LATE  # type: ignore[misc]


def _now() -> datetime:
    return datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC)


def test_note_subject_id_defaults_to_none() -> None:
    """A Note constructed without subject_id is community-wide (H-1, D-097)."""
    note = Note(
        note_id="e1",
        source_message_id="s1",
        community_id="fam-A",
        author_user_id="u1",
        note_date=_EARLY,
        note_text="Walked the dog",
        created_at=_now(),
    )
    assert note.subject_id is None


def test_event_chunk_subject_id_defaults_to_none() -> None:
    """An EventChunk constructed without subject_id is community-wide (H-1, D-097)."""
    chunk = EventChunk(
        chunk_id="c1",
        note_id="e1",
        source_message_id="s1",
        community_id="fam-A",
        author_user_id="u1",
        note_date=_EARLY,
        event_index=0,
        chunk_text="Walked the dog",
        created_at=_now(),
    )
    assert chunk.subject_id is None


def test_answer_result_model_text_defaults_to_none() -> None:
    """RC-3 additive carriage: every pre-existing AnswerResult construction
    stays valid and carries no model segment."""
    result = AnswerResult(fallback=FallbackMode.NONE, query_text="book")
    assert result.model_text is None
