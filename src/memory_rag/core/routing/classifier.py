"""Routing for plain-text messages without an explicit command.

When the user sends a message without a slash command, the webhook calls
:func:`classify_plain_text` to pick a destination. Per the D-078 contract
(enforced in code by D-079), command-less plain text routes only to the
draft floor:

- ``RouteKind.DRAFT``  — any non-empty text. The draft floor
  (D-027 / D-028 / R-13) is the only route for command-less plain text:
  the message is persisted raw (never parsed, chunked, embedded, indexed,
  or retrieved) and the user can promote it later with ``/note``. No
  heuristic auto-routes plain text to NOTE or ASK — those lifecycles are
  reached only via the explicit ``/note`` / ``/ask`` commands (D-079).
- ``RouteKind.CLARIFY`` — empty / whitespace-only text. The webhook
  short-circuits empty payloads to UNKNOWN before invoking the
  classifier, so this branch is defensive rather than a normal path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from memory_rag.core.routing.models import RouteKind

Confidence = Literal["high", "low"]


@dataclass(frozen=True, slots=True)
class ClassifiedRoute:
    route: RouteKind
    payload: str
    confidence: Confidence
    reason: str


def classify_plain_text(text: str) -> ClassifiedRoute:
    stripped = (text or "").strip()
    if not stripped:
        return ClassifiedRoute(RouteKind.CLARIFY, text or "", "low", "empty_after_strip")

    return ClassifiedRoute(RouteKind.DRAFT, text, "low", "draft_floor_no_signal")
