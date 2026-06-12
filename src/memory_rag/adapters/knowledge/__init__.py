"""Knowledge-source provider adapters (RC-4, D-108)."""

from memory_rag.adapters.knowledge.factory import build_knowledge_source
from memory_rag.adapters.knowledge.mock import MockKnowledgeSource

__all__ = [
    "MockKnowledgeSource",
    "build_knowledge_source",
]
