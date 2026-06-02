"""Adapter-owned author display-input storage port (D-084).

The Telegram adapter captures a point-in-time snapshot of the host-supplied
``username`` / ``first_name`` alongside the raw message and lands it in a
separate, adapter-owned side table (``author_display_inputs``). That landing
goes through this port — deliberately distinct from the core
``DomainRepository`` (D-083): the snapshot never appears in ``InboundMessage``,
``SourceMessage``, any other core type, or any core repository signature
(D-026 / D-041; I-1, I-6). The core continues to carry authorship only as the
opaque ``author_user_id``.

The port is keyed by the same message idempotency tuple the raw message uses —
``external_chat_id`` + ``external_message_id`` + ``edit_seq`` (R-2 / D-023) —
carried as **opaque scalars**; it imports / embeds no core type. Re-delivery of
the same tuple is a no-op that preserves the original snapshot (never a silent
mutation); an edit (a new ``edit_seq``) lands a new row. ``username`` /
``first_name`` are nullable and non-authoritative — a user may withhold either,
and a both-null snapshot is still recorded (the point-in-time "withheld" state).

``get_author_display_input`` is a raw storage read: it returns the stored
``(username, first_name)`` scalars and contains no display-resolution logic.
The ``username → first_name → opaque short-ID`` fallback chain (A-44 / D-081)
is applied by the adapter-side resolver in this module — :func:`resolve_author_display_name`
and the :func:`resolve_chunk_author_display` bridge — and rendered into the
``/sources`` block by :func:`render_source_block` (D-086). Resolution stays
adapter-only: the channel-neutral dispatcher returns opaque chunks and never
composes a display name.

The owner-fixed topology (D-083) co-locates the port on the existing per-backend
store object: the mock / sqlite / postgres stores each implement these methods
structurally, alongside the core ``DomainRepository`` / ``SearchRepository``
surfaces. ``TelegramBackendStore`` is the combined adapter-side seam the webhook
builds once and hands to both the dispatcher and this port.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from memory_rag.core.domain.models import EventChunk
from memory_rag.storage.search_repository import HybridDomainStore


class AuthorDisplayInputStore(Protocol):
    """Adapter-owned port for the author display-input snapshot (D-084).

    Distinct from the core ``DomainRepository``; keyed by opaque scalars only.
    """

    def save_author_display_input(
        self,
        *,
        external_chat_id: str,
        external_message_id: str,
        edit_seq: int,
        username: str | None,
        first_name: str | None,
    ) -> None:
        """Land one snapshot row, idempotent on the message tuple (R-2).

        A row already keyed by ``(external_chat_id, external_message_id,
        edit_seq)`` is left untouched — re-delivery never duplicates or silently
        mutates the prior snapshot. An edited state arrives under a new
        ``edit_seq`` and lands a new row. ``username`` / ``first_name`` are
        nullable; a both-null snapshot is still written.
        """

    def get_author_display_input(
        self,
        *,
        external_chat_id: str,
        external_message_id: str,
        edit_seq: int,
    ) -> tuple[str | None, str | None] | None:
        """Return the stored ``(username, first_name)`` for the tuple, or ``None``.

        Raw storage read only — no display-resolution / fallback-chain logic
        (deferred per A-44 / D-081).
        """


class TelegramBackendStore(HybridDomainStore, AuthorDisplayInputStore, Protocol):
    """Combined adapter-side store seam (D-084).

    A single per-backend store object satisfies the core ingest + retrieval seam
    (``HybridDomainStore``) and the adapter-owned display-input port
    (``AuthorDisplayInputStore``) at once. The webhook builds one store and
    passes it to the dispatcher (as the core seams) and to the display-input
    port without losing the static-type guarantee at either site. This combined
    Protocol lives in the adapter layer so the storage layer never imports the
    adapter-owned port.
    """


def _present(value: str | None) -> str | None:
    """Return a non-blank ``value`` or ``None`` (withheld fields strip away)."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def resolve_author_display_name(
    username: str | None,
    first_name: str | None,
    author_user_id: str,
) -> str:
    """Resolve a host-supplied snapshot to a display name (D-081 / A-44, D-086).

    Adapter-only fallback chain ``username → first_name → opaque short-ID``:

    * ``username`` present → ``@<username>`` (Telegram convention);
    * else ``first_name`` present → ``<first_name>`` (plain);
    * else → ``user-<last 8 of author_user_id>`` — the opaque floor, derived
      from the core identifier the chunk always carries, so a both-null /
      withheld snapshot (or a missing one) still yields a stable handle.

    A value counts as present only when it is not ``None`` and not blank after
    ``.strip()``. Resolved names are **non-authoritative** presentation — never
    a substitute for ``author_user_id`` in storage, retrieval, or provenance.
    """
    chosen = _present(username)
    if chosen is not None:
        return f"@{chosen}"
    chosen = _present(first_name)
    if chosen is not None:
        return chosen
    return f"user-{author_user_id[-8:]}"


def resolve_chunk_author_display(
    chunk: EventChunk, store: TelegramBackendStore, *, community_id: str
) -> str:
    """Resolve a chunk's author display name from the durable snapshot (D-086).

    Bridges the opaque core boundary: ``EventChunk`` carries only
    ``author_user_id`` + ``source_message_id``, not the external message tuple
    that keys ``author_display_inputs``. So this looks the source message up
    (``get_source_message``) to recover ``(external_chat_id,
    external_message_id, edit_seq)``, reads the snapshot
    (``get_author_display_input``), and applies
    :func:`resolve_author_display_name`. A missing source row or missing
    snapshot falls through to the opaque short-ID floor — never blank, never a
    raise.

    ``community_id`` is the requester-scoped community of the ``/sources`` caller
    (resolved at the adapter edge from the inbound chat via the current identity
    mapping). The source lookup is community-scoped (Slice 8.1.2 / D-089): a
    source owned by another community reads as ``None`` and so resolves to the
    opaque floor — the read can never cross a community boundary (I-7, R-3).
    """
    username: str | None = None
    first_name: str | None = None
    source = store.get_source_message(chunk.source_message_id, community_id=community_id)
    if source is not None:
        snapshot = store.get_author_display_input(
            external_chat_id=source.external_chat_id,
            external_message_id=source.external_message_id,
            edit_seq=source.edit_seq,
        )
        if snapshot is not None:
            username, first_name = snapshot
    return resolve_author_display_name(username, first_name, chunk.author_user_id)


def render_source_block(
    chunk: EventChunk,
    *,
    index: int,
    total: int,
    store: TelegramBackendStore,
    community_id: str,
) -> str:
    """Render one ``/sources`` block with an adapter-resolved author (D-086).

    Layout: the unchanged date/index header, a ``— <author>`` attribution
    line, then the verbatim ``chunk_text``::

        [2026-05-09] (1/3)
        — @alice

        Walked the dog

    Block layout moved here from the channel-neutral dispatcher so author
    resolution stays adapter-only (D-081), mirroring how ``/drafts`` blocks are
    rendered adapter-side. The ``(i/N)`` index is per-last-``/ask`` ephemeral
    ordering, not a stable identifier; the underlying ``chunk_id`` is not
    surfaced (D-069). ``community_id`` is the requester-scoped community,
    forwarded to the community-scoped author lookup (Slice 8.1.2 / D-089).
    """
    author = resolve_chunk_author_display(chunk, store, community_id=community_id)
    return (
        f"[{chunk.note_date.isoformat()}] ({index}/{total})\n"
        f"— {author}\n\n"
        f"{chunk.chunk_text}"
    )


_CONTRIBUTORS_LABEL = "Contributors:"


def render_contributors_footer(
    chunks: Sequence[EventChunk],
    store: TelegramBackendStore,
    *,
    community_id: str,
) -> str:
    """Render the ``/ask``-reply contributor-attribution footer (D-091).

    The contributors are the **distinct authors of the answer's grounding
    chunks** — deduplicated on the opaque ``author_user_id`` *before* display
    resolution, in first-appearance order over ``chunks`` (the RRF
    ``ordered_chunks`` order; no re-sort). One representative chunk per distinct
    ``author_user_id`` is resolved through the adapter-only
    :func:`resolve_chunk_author_display` fallback chain (``@username →
    first_name → opaque short-ID``), so the same non-authoritative /
    opaque-floor semantics as ``/sources`` apply. Two distinct
    ``author_user_id``\\s that resolve to the same display string intentionally
    stay two separate entries — dedup is on authorship truth (I-6), never on
    the display string.

    Returns a single labeled line: ``Contributors: <name1>, <name2>, …``
    (comma-space separated; a single contributor renders as
    ``Contributors: @alice``). ``community_id`` is the requester-scoped
    community, forwarded to the community-scoped author lookup so resolution
    never crosses a community boundary (Slice 8.1.2 / D-089; I-7, R-3). Callers
    render this footer only when ``chunks`` is non-empty (D-091).
    """
    seen: set[str] = set()
    representatives: list[EventChunk] = []
    for chunk in chunks:
        if chunk.author_user_id in seen:
            continue
        seen.add(chunk.author_user_id)
        representatives.append(chunk)
    names = [
        resolve_chunk_author_display(chunk, store, community_id=community_id)
        for chunk in representatives
    ]
    return f"{_CONTRIBUTORS_LABEL} {', '.join(names)}"
