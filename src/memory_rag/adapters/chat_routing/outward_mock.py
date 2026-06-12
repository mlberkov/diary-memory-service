"""Deterministic mock outward rewriter (RC-4, D-108).

Used by every automated test by default and by any boot configured with
``CLASSIFIER_BACKEND=mock`` (the outward rewriter rides the classifier
contour — same backend knob, same model pin, like the RC-3 retrieval
rewriter). The ``model_name`` is the literal string ``"mock"`` —
provider provenance in rows and logs stays honest.

The default behavior is an identity rewrite: ``search_query`` is the
question unchanged. Unit tests steer it via the ``rewrite_to``
constructor knob; the received ``notes_context`` is captured on
``last_notes_context`` so tests can assert the conditioning seam
without a real provider.

``latency_ms`` is ``0`` — a mock has no real provider latency to
attribute. ``raw_output`` is a deterministic JSON object mirroring the
shape the real adapter's function-call arguments take.
"""

from __future__ import annotations

import json

from memory_rag.core.chat.outward import OutwardRewrite


class MockOutwardRewriter:
    """In-process deterministic outward-rewriter stand-in (RC-4)."""

    def __init__(
        self,
        *,
        model_name: str = "mock",
        rewrite_to: str | None = None,
    ) -> None:
        self._model_name = model_name
        self._rewrite_to = rewrite_to
        self.last_notes_context: tuple[str, ...] | None = None

    @property
    def model_name(self) -> str:
        return self._model_name

    def rewrite_outward(self, question: str, *, notes_context: tuple[str, ...]) -> OutwardRewrite:
        self.last_notes_context = notes_context
        search_query = self._rewrite_to if self._rewrite_to is not None else question
        raw_output = json.dumps({"search_query": search_query}, sort_keys=True)
        return OutwardRewrite(
            search_query=search_query,
            raw_output=raw_output,
            model_name=self._model_name,
            latency_ms=0,
        )
