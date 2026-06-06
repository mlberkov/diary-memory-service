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
    from memory_rag.core.domain.models import EventChunk, SourceMessage
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

    ``community_id`` is the resolved opaque community scope, set by the
    event-source adapter via its chat→community resolver (D-093 / G-1;
    D-026 axis 5). The core scopes on this opaque id and never re-derives
    scope from ``external_chat_id`` (I-1). ``external_chat_id`` is retained
    as the transport / idempotency identifier only: together with
    ``external_message_id`` and ``edit_seq`` it forms the R-2 key (D-023),
    and the adapter uses it to address the reply. Under the default 1:1
    Telegram mapping the two carry the same value but are distinct concerns.

    ``edit_seq`` carries the Telegram-derived edit-state marker (D-023):
    ``0`` for an original delivery, the ``edit_date`` epoch seconds for an
    edited state.
    """

    external_message_id: str
    external_chat_id: str
    external_user_id: str
    community_id: str
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
    by the transport size cap). ``source_chunks`` carries the opaque
    chunks retrieval selected for the chat's most recent ``/ask`` turn
    (``/sources``, D-036); the adapter renders each block as-is and
    resolves the (adapter-only, D-081 / D-086) author display name,
    packing the blocks with the same combined-message semantics used for
    ``drafts``. When ``document``, ``drafts``, and ``source_chunks`` are
    all ``None`` the adapter delivers ``reply_text`` only.
    """

    reply_text: str
    route: RouteKind
    metadata: Mapping[str, str] = field(default_factory=dict)
    document: ExportPayload | None = None
    drafts: list[SourceMessage] | None = None
    source_chunks: tuple[EventChunk, ...] | None = None
