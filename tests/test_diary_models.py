"""Unit tests for ``core/domain`` value objects.

Currently covers the ``DateRange`` retrieval-filter value object
(Slice 3.4, D-040): both bounds optional and inclusive, both-``None``
is a valid no-constraint range, and a contradictory ``start > end``
range is rejected at construction.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from memory_rag.core.domain.models import DateRange

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
