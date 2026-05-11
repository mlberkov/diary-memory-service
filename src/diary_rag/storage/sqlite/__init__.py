"""Local SQLite implementation of ``DiaryRepository`` (ingest only).

Opt-in dev/offline backend (D-022). Postgres is the canonical durable
backend and the only retrieval backend (D-025); the SQLite
``SearchRepository`` methods raise ``NotImplementedError`` and the
dispatcher converts that to ``FallbackMode.NO_EVIDENCE``.
"""

from diary_rag.storage.sqlite.store import SqliteDiaryStore

__all__ = ["SqliteDiaryStore"]
