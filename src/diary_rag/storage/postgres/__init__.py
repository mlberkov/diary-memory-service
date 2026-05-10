"""Local PostgreSQL implementation of ``DiaryRepository`` (D-022)."""

from diary_rag.storage.postgres.store import PostgresDiaryStore

__all__ = ["PostgresDiaryStore"]
