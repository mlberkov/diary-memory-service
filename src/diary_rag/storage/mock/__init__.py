"""In-memory mock storage.

Mocks stand in for the durable PostgreSQL repositories that arrive in
Phase 2. They are intentionally minimal and process-local.
"""

from diary_rag.storage.mock.store import MockDiaryStore

__all__ = ["MockDiaryStore"]
