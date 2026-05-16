"""Smoke tests for Slice 1.1.

Confirms the package imports and the minimal toolchain wiring is alive.
"""

from __future__ import annotations

import memory_rag


def test_package_version_is_string() -> None:
    assert isinstance(memory_rag.__version__, str)
    assert memory_rag.__version__
