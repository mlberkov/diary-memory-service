"""Adapter-owned chat→community resolver (D-093 / G-1).

The single site that maps a Telegram chat to a core community scope. This
is the D-026 axis-5 (tenant/auth mapping) function: *the mapping function
is adapter; the scoped query is core*. The core receives the already-
resolved opaque ``community_id`` and never re-derives it from the
transport chat id (D-093 §3; I-1).

The default Telegram mapping is 1:1 from ``external_chat_id`` — a group
chat is one shared community, distinct chats are isolated communities on
one instance (I-6 / I-7). A future host plugs a different mapping here
(e.g. a chat→community lookup table) without pushing transport vocabulary
into the core or touching any core call site.
"""

from __future__ import annotations


def resolve_community_id(external_chat_id: str) -> str:
    """Map a transport chat id to an opaque core ``community_id``.

    Default mapping is identity (1:1). The return value is opaque past the
    adapter edge — the core treats it as a scope id, never as "the Telegram
    chat id" (D-089 framing).
    """
    return external_chat_id
