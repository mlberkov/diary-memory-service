"""Local PostgreSQL implementation of ``DomainRepository`` (D-022)."""

from memory_rag.storage.postgres.store import PostgresDomainStore

__all__ = ["PostgresDomainStore"]
