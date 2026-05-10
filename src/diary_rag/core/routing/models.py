"""Channel-neutral routing data types.

These cross the adapter boundary. They contain no Telegram-specific
fields (Invariant I-1) so a non-Telegram channel can produce them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal

RouteSource = Literal["command", "heuristic"]


class RouteKind(StrEnum):
    START = "start"
    HELP = "help"
    ENTRY = "entry"
    ASK = "ask"
    CLARIFY = "clarify"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """A channel-neutral inbound message ready for dispatch."""

    external_message_id: str
    external_chat_id: str
    external_user_id: str
    text: str
    route: RouteKind
    received_at: datetime
    route_source: RouteSource
    payload: str = ""


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """A handler's reply text plus the route it served."""

    reply_text: str
    route: RouteKind
    metadata: Mapping[str, str] = field(default_factory=dict)
