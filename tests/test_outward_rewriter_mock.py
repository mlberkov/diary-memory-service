"""MockOutwardRewriter behavior (RC-4, D-108).

The deterministic stand-in behind ``CLASSIFIER_BACKEND=mock`` for the
outward-rewrite seam: identity rewrite by default, constructor-steered
rewrites for tests, honest ``model_name`` provenance, and the captured
``notes_context`` so the conditioning seam is assertable without a real
provider.
"""

from __future__ import annotations

import json

from memory_rag.adapters.chat_routing import MockOutwardRewriter


def test_default_is_an_identity_rewrite() -> None:
    rewriter = MockOutwardRewriter()
    outward = rewriter.rewrite_outward("why won't he nap", notes_context=("He is 2",))
    assert outward.search_query == "why won't he nap"
    assert outward.model_name == "mock"
    assert outward.latency_ms == 0


def test_rewrite_to_steers_the_search_query() -> None:
    rewriter = MockOutwardRewriter(rewrite_to="2 year old nap refusal")
    outward = rewriter.rewrite_outward("why won't he nap", notes_context=())
    assert outward.search_query == "2 year old nap refusal"


def test_notes_context_is_captured_for_conditioning_assertions() -> None:
    rewriter = MockOutwardRewriter()
    rewriter.rewrite_outward("q", notes_context=("chunk one", "chunk two"))
    assert rewriter.last_notes_context == ("chunk one", "chunk two")


def test_raw_output_mirrors_the_function_call_arguments_shape() -> None:
    rewriter = MockOutwardRewriter(rewrite_to="external query")
    outward = rewriter.rewrite_outward("q", notes_context=())
    assert json.loads(outward.raw_output) == {"search_query": "external query"}
