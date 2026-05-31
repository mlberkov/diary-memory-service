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
``(username, first_name)`` scalars and contains no display-resolution logic —
the ``username → first_name → opaque short-ID`` fallback chain stays deferred
(A-44 / D-081).

The owner-fixed topology (D-083) co-locates the port on the existing per-backend
store object: the mock / sqlite / postgres stores each implement these methods
structurally, alongside the core ``DomainRepository`` / ``SearchRepository``
surfaces. ``TelegramBackendStore`` is the combined adapter-side seam the webhook
builds once and hands to both the dispatcher and this port.
"""

from __future__ import annotations

from typing import Protocol

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
