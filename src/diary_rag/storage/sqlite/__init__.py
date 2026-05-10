"""Local SQLite implementation of ``DiaryRepository``.

Thinnest durable seam for restart-survival validation. PostgreSQL
(D-007) replaces this implementation in a follow-up packet behind the
same ``DiaryRepository`` Protocol.
"""

from diary_rag.storage.sqlite.store import SqliteDiaryStore

__all__ = ["SqliteDiaryStore"]
