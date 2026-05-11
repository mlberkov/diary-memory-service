"""Combined-payload packer for the ``/drafts`` recall response (D-030).

The conceptual response is a single ordered sequence: header + N full
draft blocks. The adapter's job is to render that sequence as one
Telegram message whenever it fits and to fall back to multiple
messages only when the Telegram per-message size cap (4096 chars)
forces it.

Rules the packer enforces:

- A whole draft block is never split when it would fit alongside the
  header or alongside other short blocks.
- When the combined payload overflows, splits land on whole-block
  boundaries.
- If a single block is itself larger than the cap, it is emitted as
  its own consecutive multipart sequence with ``(part k/N)`` footers,
  and no neighbour block shares a message with any of its parts.
- Block ordering is preserved end-to-end.

The packer is a pure function over strings; the webhook adapter calls
it and then issues one outbound ``send_message`` per element of the
returned list.
"""

from __future__ import annotations

_DEFAULT_CAP = 4096
_DEFAULT_SEPARATOR = "\n\n"


def pack_drafts_into_messages(
    header: str,
    blocks: list[str],
    *,
    cap: int = _DEFAULT_CAP,
    separator: str = _DEFAULT_SEPARATOR,
) -> list[str]:
    """Pack ``header`` + ordered draft ``blocks`` into Telegram-sized messages.

    Returns a non-empty list of message bodies in send order. A single
    message containing the entire combined payload is returned whenever
    that fits under ``cap``.
    """
    if cap < 1:
        raise ValueError("cap must be positive")
    if not separator:
        raise ValueError("separator must be non-empty")

    messages: list[str] = []
    current = header

    for block in blocks:
        if len(block) > cap:
            if current:
                messages.append(current)
                current = ""
            messages.extend(_split_oversized(block, cap=cap, separator=separator))
            continue

        if not current:
            current = block
            continue

        if len(current) + len(separator) + len(block) <= cap:
            current = f"{current}{separator}{block}"
        else:
            messages.append(current)
            current = block

    if current:
        messages.append(current)

    return messages or [header]


def _split_oversized(block: str, *, cap: int, separator: str) -> list[str]:
    """Split a single oversized block into ``(part k/N)``-suffixed parts.

    Each part except the last is sized so that ``len(part_body) + len(footer)``
    is ``<= cap``. The footer template is ``"{separator}(part {k}/{n})"``.
    Sizing is computed up-front from the body length so the part count is
    known before footers are appended.
    """
    assert len(block) > cap

    # Iteratively grow ``n`` until the per-part body size, computed with the
    # widest footer ``" (part n/n)"`` for that ``n``, accommodates ``block``.
    n = 1
    while True:
        footer_overhead = len(separator) + len(f"(part {n}/{n})")
        body_cap = cap - footer_overhead
        if body_cap < 1:
            raise ValueError(
                f"cap={cap} too small to accommodate the part footer; "
                "increase cap or shorten the separator"
            )
        if body_cap * n >= len(block):
            break
        n += 1

    body_cap = cap - (len(separator) + len(f"(part {n}/{n})"))
    parts: list[str] = []
    for k in range(n):
        start = k * body_cap
        end = start + body_cap
        body = block[start:end]
        parts.append(f"{body}{separator}(part {k + 1}/{n})")
    return parts


__all__ = ["pack_drafts_into_messages"]
