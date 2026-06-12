"""Deterministic mock route classifier (RC-2, D-108).

Used by every automated test by default and by any boot configured with
``CLASSIFIER_BACKEND=mock``. The ``model_name`` is the literal string
``"mock"`` — provider provenance in rows and logs stays honest (the
D-024-style convention applied to the classifier seam).

Steerable two ways: in-band — the first :class:`ChatRoute` value that
appears as a substring of the lowercased question wins, so an
end-to-end test can write ``model_only`` into the message text — and
via the ``default_route`` constructor knob for unit tests that want a
fixed verdict without shaping the question.

``latency_ms`` is ``0`` — a mock has no real provider latency to
attribute. ``raw_output`` is a deterministic JSON object mirroring the
shape the real adapter's function-call arguments take.
"""

from __future__ import annotations

import json

from memory_rag.core.chat.models import ChatRoute, RouteClassification


class MockRouteClassifier:
    """In-process deterministic route-classifier stand-in (RC-2)."""

    def __init__(
        self,
        *,
        model_name: str = "mock",
        default_route: ChatRoute = ChatRoute.NOTES_LOOKUP,
    ) -> None:
        self._model_name = model_name
        self._default_route = default_route

    @property
    def model_name(self) -> str:
        return self._model_name

    def classify(self, question: str) -> RouteClassification:
        lowered = question.lower()
        selected = self._default_route
        for route in ChatRoute:
            if route.value in lowered:
                selected = route
                break
        raw_output = json.dumps({"route": selected.value}, sort_keys=True)
        return RouteClassification(
            route=selected,
            raw_output=raw_output,
            model_name=self._model_name,
            latency_ms=0,
        )
