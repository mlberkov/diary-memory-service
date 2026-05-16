"""Embedding-provider adapters.

Concrete implementations of :class:`memory_rag.core.embeddings.EmbeddingClient`.
Adapter selection is driven by ``Settings.embedding_backend`` (``mock``
or ``openai``); domain code remains SDK-free (Invariant I-11).

``build_embedding_client`` is the single factory used by both the app
boot gate and the webhook dispatcher so the two paths cannot disagree
on which backend / model / dimension they expect.
"""

from memory_rag.adapters.embeddings.factory import build_embedding_client
from memory_rag.adapters.embeddings.mock import MockEmbeddingClient

__all__ = ["MockEmbeddingClient", "build_embedding_client"]
