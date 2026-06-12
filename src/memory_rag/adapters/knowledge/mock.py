"""Deterministic mock knowledge source (RC-4, D-108).

Used by every automated test by default and by any boot configured with
``KNOWLEDGE_BACKEND=mock``. The ``provider_name`` is the literal string
``"mock"`` — provider provenance in rows and logs stays honest (the
D-024-style convention applied to the knowledge seam).

The default behavior returns no excerpts — a provider that answered and
found nothing, which keeps mock-mode routed answers free of fabricated
web-plane content. Unit tests steer it via the ``excerpts`` constructor
knob. ``latency_ms`` is ``0`` — a mock has no real provider latency to
attribute. ``raw_output`` is a deterministic JSON object mirroring the
shape of the real adapter's response body.
"""

from __future__ import annotations

import json

from memory_rag.core.chat.knowledge import KnowledgeExcerpt, KnowledgeResult


class MockKnowledgeSource:
    """In-process deterministic knowledge-source stand-in (RC-4)."""

    def __init__(
        self,
        *,
        provider_name: str = "mock",
        excerpts: tuple[KnowledgeExcerpt, ...] = (),
    ) -> None:
        self._provider_name = provider_name
        self._excerpts = excerpts

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def search(self, query: str) -> KnowledgeResult:
        raw_output = json.dumps(
            {
                "query": query,
                "results": [
                    {"url": e.ref, "title": e.title, "content": e.text} for e in self._excerpts
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return KnowledgeResult(
            excerpts=self._excerpts,
            raw_output=raw_output,
            latency_ms=0,
        )
