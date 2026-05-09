"""In-memory mock storage for Phase 1 slices.

Mocks are intentionally minimal stand-ins. Real repositories
(`MockSourceMessageRepository`, `MockSearchRepository`, ...) with the
shape from TechSpec §5 land in Slice 1.3.
"""

from diary_rag.storage.mock.in_memory import InMemorySourceMessageStore

__all__ = ["InMemorySourceMessageStore"]
