"""Channel-neutral routing types."""

from diary_rag.core.routing.models import (
    DispatchResult,
    InboundMessage,
    Lifecycle,
    RouteKind,
    RouteSource,
    lifecycle_for,
)

__all__ = [
    "DispatchResult",
    "InboundMessage",
    "Lifecycle",
    "RouteKind",
    "RouteSource",
    "lifecycle_for",
]
