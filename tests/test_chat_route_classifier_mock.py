"""MockRouteClassifier contract (RC-2, D-108).

Deterministic and steerable two ways: in-band (a route value appearing
in the question text wins) and via the ``default_route`` constructor
knob. ``model_name`` is the literal ``"mock"`` and ``latency_ms`` is 0 —
honest provenance, mirroring the chat-client mock conventions.
"""

from __future__ import annotations

import json

import pytest

from memory_rag.adapters.chat_routing import MockRouteClassifier
from memory_rag.core.chat import ChatRoute


@pytest.mark.parametrize("route", list(ChatRoute))
def test_in_band_token_steers_to_each_route(route: ChatRoute) -> None:
    classification = MockRouteClassifier().classify(f"please use {route.value} here")
    assert classification.route is route


def test_default_route_is_notes_lookup() -> None:
    classification = MockRouteClassifier().classify("when did he first walk")
    assert classification.route is ChatRoute.NOTES_LOOKUP


def test_default_route_override() -> None:
    classifier = MockRouteClassifier(default_route=ChatRoute.MODEL_ONLY)
    classification = classifier.classify("when did he first walk")
    assert classification.route is ChatRoute.MODEL_ONLY


def test_raw_output_is_route_json() -> None:
    classification = MockRouteClassifier().classify("model_only question")
    assert json.loads(classification.raw_output) == {"route": "model_only"}


def test_provenance_is_honest() -> None:
    classification = MockRouteClassifier().classify("anything")
    assert classification.model_name == "mock"
    assert classification.latency_ms == 0


def test_classify_is_deterministic() -> None:
    classifier = MockRouteClassifier()
    assert classifier.classify("model_only q") == classifier.classify("model_only q")
