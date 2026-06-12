"""Route-classifier and rewriter provider adapters (RC-2/RC-3/RC-4, D-108)."""

from memory_rag.adapters.chat_routing.factory import (
    build_outward_rewriter,
    build_query_rewriter,
    build_route_classifier,
)
from memory_rag.adapters.chat_routing.mock import MockRouteClassifier
from memory_rag.adapters.chat_routing.outward_mock import MockOutwardRewriter
from memory_rag.adapters.chat_routing.rewrite_mock import MockQueryRewriter

__all__ = [
    "MockOutwardRewriter",
    "MockQueryRewriter",
    "MockRouteClassifier",
    "build_outward_rewriter",
    "build_query_rewriter",
    "build_route_classifier",
]
