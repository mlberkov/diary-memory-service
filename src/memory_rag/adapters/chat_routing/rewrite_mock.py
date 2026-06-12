"""Deterministic mock query rewriter (RC-3, D-108).

Used by every automated test by default and by any boot configured with
``CLASSIFIER_BACKEND=mock`` (the rewriter rides the classifier contour —
same backend knob, same model pin). The ``model_name`` is the literal
string ``"mock"`` — provider provenance in rows and logs stays honest
(the D-024-style convention applied to the rewriter seam).

The default behavior is an identity rewrite: ``retrieval_query`` is the
question unchanged with no date constraint. Unit tests steer it via the
``rewrite_to`` / ``date_range`` constructor knobs. ``subject_scope`` is
never emitted (see ``docs/assumptions.md``).

``latency_ms`` is ``0`` — a mock has no real provider latency to
attribute. ``raw_output`` is a deterministic JSON object mirroring the
shape the real adapter's function-call arguments take.
"""

from __future__ import annotations

import json
from datetime import date

from memory_rag.core.chat.rewrite import QueryRewrite
from memory_rag.core.domain.models import DateRange


class MockQueryRewriter:
    """In-process deterministic query-rewriter stand-in (RC-3)."""

    def __init__(
        self,
        *,
        model_name: str = "mock",
        rewrite_to: str | None = None,
        date_range: DateRange | None = None,
    ) -> None:
        self._model_name = model_name
        self._rewrite_to = rewrite_to
        self._date_range = date_range

    @property
    def model_name(self) -> str:
        return self._model_name

    def rewrite(self, question: str, *, today: date) -> QueryRewrite:
        retrieval_query = self._rewrite_to if self._rewrite_to is not None else question
        arguments: dict[str, str] = {"retrieval_query": retrieval_query}
        if self._date_range is not None:
            if self._date_range.start is not None:
                arguments["date_from"] = self._date_range.start.isoformat()
            if self._date_range.end is not None:
                arguments["date_to"] = self._date_range.end.isoformat()
        raw_output = json.dumps(arguments, sort_keys=True)
        return QueryRewrite(
            retrieval_query=retrieval_query,
            date_range=self._date_range,
            subject_scope=None,
            raw_output=raw_output,
            model_name=self._model_name,
            latency_ms=0,
        )
