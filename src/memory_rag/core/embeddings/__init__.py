"""Channel-neutral embeddings domain.

The :class:`EmbeddingClient` Protocol is the seam every adapter (mock,
OpenAI) satisfies; the :class:`EmbeddingRecord` dataclass is what the
storage layer persists per chunk per model (TechSpec §5). Failure /
ready state lives on :class:`EmbeddingStatus`, attached to each
``EventChunk`` so SQL inspection alone tells the operator which chunks
made it through the embedding step.
"""

from memory_rag.core.embeddings.client import EmbeddingClient
from memory_rag.core.embeddings.models import EmbeddingRecord, EmbeddingStatus

__all__ = ["EmbeddingClient", "EmbeddingRecord", "EmbeddingStatus"]
