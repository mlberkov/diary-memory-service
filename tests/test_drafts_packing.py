"""Unit tests for ``pack_drafts_into_messages`` (D-030 combined-payload packer)."""

from __future__ import annotations

from diary_rag.adapters.telegram.drafts_packing import pack_drafts_into_messages


def test_header_alone_returns_single_message() -> None:
    msgs = pack_drafts_into_messages("Header.", [])
    assert msgs == ["Header."]


def test_short_blocks_fit_in_single_message_by_default() -> None:
    msgs = pack_drafts_into_messages(
        "Most recent 3 drafts:",
        ["block A", "block B", "block C"],
    )
    assert len(msgs) == 1
    body = msgs[0]
    assert body.startswith("Most recent 3 drafts:")
    assert "block A" in body and "block B" in body and "block C" in body
    # Order preserved.
    assert body.index("block A") < body.index("block B") < body.index("block C")


def test_overflow_splits_between_whole_blocks() -> None:
    cap = 60
    blocks = ["A" * 25, "B" * 25, "C" * 25]
    msgs = pack_drafts_into_messages("H", blocks, cap=cap, separator="\n\n")
    assert len(msgs) >= 2
    # Each block appears whole in exactly one message.
    for marker, expected_len in (("A", 25), ("B", 25), ("C", 25)):
        full = marker * expected_len
        hits = sum(full in m for m in msgs)
        assert hits == 1, f"block {marker!r} should appear whole in exactly one message"
    # No message exceeds the cap.
    for m in msgs:
        assert len(m) <= cap


def test_oversized_block_is_standalone_multipart_with_part_footers() -> None:
    cap = 40
    big = "X" * 120  # > cap, will be split
    msgs = pack_drafts_into_messages("H", [big], cap=cap, separator="\n\n")
    # Header alone (since the next block is oversized and must start fresh)
    assert msgs[0] == "H"
    # Remaining messages are the multipart parts.
    parts = msgs[1:]
    assert len(parts) >= 2
    n = len(parts)
    for k, part in enumerate(parts, start=1):
        assert part.endswith(f"(part {k}/{n})")
        # The body chars are all X.
        body = part.split("\n\n(part ")[0]
        assert set(body) == {"X"}
    # All parts together reconstruct the original body.
    reconstructed = "".join(p.split("\n\n(part ")[0] for p in parts)
    assert reconstructed == big


def test_oversized_block_does_not_share_message_with_neighbours() -> None:
    cap = 40
    short_before = "before"
    big = "Y" * 120
    short_after = "after"
    msgs = pack_drafts_into_messages(
        "H", [short_before, big, short_after], cap=cap, separator="\n\n"
    )
    # Locate the oversized parts: any message ending in "(part k/N)".
    part_indices = [i for i, m in enumerate(msgs) if m.endswith(")") and "\n\n(part " in m]
    assert part_indices, "expected at least one multipart part"
    first_part = part_indices[0]
    last_part = part_indices[-1]
    # No neighbour content appears inside any part message.
    for i in part_indices:
        assert short_before not in msgs[i]
        assert short_after not in msgs[i]
    # The message immediately before the first part must not contain ``Y``.
    assert "Y" not in msgs[first_part - 1]
    # The message immediately after the last part must not contain ``Y``.
    if last_part + 1 < len(msgs):
        assert "Y" not in msgs[last_part + 1]
    # short_after begins fresh after the oversized sequence.
    assert any(short_after in m for m in msgs[last_part + 1 :])


def test_block_order_preserved_under_packing() -> None:
    cap = 50
    blocks = [f"block-{i}" for i in range(10)]
    msgs = pack_drafts_into_messages("H", blocks, cap=cap)
    combined = "\n--MSG--\n".join(msgs)
    positions = [combined.index(b) for b in blocks]
    assert positions == sorted(positions)


def test_typical_short_drafts_fit_alongside_header() -> None:
    cap = 4096
    # Three short drafts of ~100 chars each plus header. Should fit in one message.
    blocks = ["x" * 100, "y" * 100, "z" * 100]
    msgs = pack_drafts_into_messages("Most recent 3 drafts:", blocks, cap=cap)
    assert len(msgs) == 1
