"""Channel-neutral routing data types.

These cross the adapter boundary. They contain no Telegram-specific
fields (Invariant I-1) so a non-Telegram channel can produce them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from memory_rag.core.domain.models import SourceMessage
    from memory_rag.core.export.models import ExportPayload

RouteSource = Literal["command", "heuristic"]


class RouteKind(StrEnum):
    START = "start"
    HELP = "help"
    NOTE = "note"
    ASK = "ask"
    DRAFT = "draft"
    DRAFTS = "drafts"
    EXPORT = "export"
    SOURCES = "sources"
    CLARIFY = "clarify"
    UNKNOWN = "unknown"


Lifecycle = Literal["draft", "note", "query", "other"]


def lifecycle_for(route: RouteKind) -> Lifecycle:
    """Map a route to its D-027 lifecycle state.

    ``NOTE`` maps to the ``"note"`` lifecycle, ``DRAFT`` to ``"draft"``,
    and ``ASK`` to ``"query"``; every other route maps to ``"other"``.
    """
    if route is RouteKind.DRAFT:
        return "draft"
    if route is RouteKind.NOTE:
        return "note"
    if route is RouteKind.ASK:
        return "query"
    return "other"


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """A channel-neutral inbound message ready for dispatch.

    ``edit_seq`` carries the Telegram-derived edit-state marker (D-023):
    ``0`` for an original delivery, the ``edit_date`` epoch seconds for an
    edited state. Together with ``external_chat_id`` and ``external_message_id``
    it forms the idempotency key for R-2.
    """

    external_message_id: str
    external_chat_id: str
    external_user_id: str
    text: str
    route: RouteKind
    received_at: datetime
    route_source: RouteSource
    payload: str = ""
    edit_seq: int = 0


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """A handler's reply text plus the route it served.

    ``document`` is set when a handler produces a channel-neutral file
    payload that the adapter should deliver out-of-band (e.g. Telegram
    ``sendDocument``). ``drafts`` carries a list of source messages that
    the adapter should render as a combined ordered response (one
    transport message by default; multi-message split only when forced
    by the transport size cap). ``source_blocks`` carries pre-rendered
    string blocks for ``/sources`` (D-036) — the chunks retrieval
    selected for the chat's most recent ``/ask`` turn, rendered as-is.
    The adapter packs them with the same combined-message semantics
    used for ``drafts``. When all three are ``None`` the adapter
    delivers ``reply_text`` only.
    """

    reply_text: str
    route: RouteKind
    metadata: Mapping[str, str] = field(default_factory=dict)
    document: ExportPayload | None = None
    drafts: list[SourceMessage] | None = None
    source_blocks: list[str] | None = None
