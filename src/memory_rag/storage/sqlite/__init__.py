"""Local SQLite implementation of ``DomainRepository`` (ingest only).

Opt-in dev/offline backend (D-022). Postgres is the canonical durable
backend and the only retrieval backend (D-025); the SQLite
``SearchRepository`` methods raise ``NotImplementedError`` and the
dispatcher converts that to ``FallbackMode.NO_EVIDENCE``.
"""

from memory_rag.storage.sqlite.store import SqliteDomainStore

__all__ = ["SqliteDomainStore"]
