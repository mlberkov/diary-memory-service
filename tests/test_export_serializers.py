"""Unit tests for raw-export serializers (D-029)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from memory_rag.core.domain.models import SourceMessage
from memory_rag.core.export.serializers import SCHEMA_VERSION, serialize_json, serialize_txt
from memory_rag.core.routing import RouteKind


def _source(
    *,
    sid: str = "src-1",
    community_id: str = "fam-A",
    author: str = "user-1",
    chat_id: str = "fam-A",
    msg_id: str = "100",
    edit_seq: int = 0,
    raw_text: str = "hello",
    route: RouteKind = RouteKind.NOTE,
    created_at: datetime | None = None,
) -> SourceMessage:
    return SourceMessage(
        source_message_id=sid,
        community_id=community_id,
        author_user_id=author,
        external_chat_id=chat_id,
        external_user_id=author,
        external_message_id=msg_id,
        edit_seq=edit_seq,
        raw_text=raw_text,
        detected_route=route,
        created_at=created_at or datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC),
    )


def test_json_serializer_envelope_keys() -> None:
    generated_at = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)
    payload = serialize_json(
        [_source()],
        community_id="fam-A",
        requester_user_id="user-1",
        generated_at=generated_at,
    )
    document = json.loads(payload.decode("utf-8"))
    assert set(document.keys()) == {"export", "records"}
    envelope = document["export"]
    assert envelope["format"] == "json"
    assert envelope["schema_version"] == SCHEMA_VERSION
    assert envelope["scope"] == {"community_id": "fam-A", "requester_user_id": "user-1"}
    assert envelope["generated_at"] == generated_at.isoformat()
    assert envelope["record_count"] == 1


def test_json_serializer_records_carry_every_source_field_with_iso_timestamps() -> None:
    src = _source(
        sid="src-1",
        chat_id="fam-A",
        author="user-1",
        msg_id="100",
        edit_seq=2,
        raw_text="line one\nline two",
        route=RouteKind.DRAFT,
        created_at=datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC),
    )
    payload = serialize_json(
        [src],
        community_id="fam-A",
        requester_user_id="user-1",
        generated_at=datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC),
    )
    document = json.loads(payload.decode("utf-8"))
    record = document["records"][0]
    assert record == {
        "source_message_id": "src-1",
        "community_id": "fam-A",
        "author_user_id": "user-1",
        "external_chat_id": "fam-A",
        "external_user_id": "user-1",
        "external_message_id": "100",
        "edit_seq": 2,
        "raw_text": "line one\nline two",
        "detected_route": "draft",
        "created_at": "2026-05-09T10:00:00+00:00",
    }


def test_json_serializer_empty_records_preserves_envelope() -> None:
    payload = serialize_json(
        [],
        community_id="fam-A",
        requester_user_id="user-1",
        generated_at=datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC),
    )
    document = json.loads(payload.decode("utf-8"))
    assert document["records"] == []
    assert document["export"]["record_count"] == 0


def test_json_serializer_preserves_unicode() -> None:
    src = _source(raw_text="привет мир")
    payload = serialize_json(
        [src],
        community_id="fam-A",
        requester_user_id="user-1",
        generated_at=datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC),
    )
    assert "привет мир".encode() in payload


def test_txt_serializer_header_lines() -> None:
    generated_at = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)
    payload = serialize_txt(
        [_source()],
        community_id="fam-A",
        requester_user_id="user-1",
        generated_at=generated_at,
    )
    text = payload.decode("utf-8")
    assert text.startswith("# raw export\n")
    assert "# format: txt\n" in text
    assert f"# schema_version: {SCHEMA_VERSION}\n" in text
    assert "# community_id: fam-A\n" in text
    assert "# requester_user_id: user-1\n" in text
    assert f"# generated_at: {generated_at.isoformat()}\n" in text
    assert "# record_count: 1\n" in text


def test_txt_serializer_block_preserves_multiline_raw_text() -> None:
    src = _source(raw_text="line one\nline two\nline three")
    payload = serialize_txt(
        [src],
        community_id="fam-A",
        requester_user_id="user-1",
        generated_at=datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC),
    )
    text = payload.decode("utf-8")
    assert "raw_text:\nline one\nline two\nline three" in text


def test_txt_serializer_blocks_are_separated_by_blank_line() -> None:
    a = _source(sid="src-A", msg_id="1", raw_text="alpha")
    b = _source(sid="src-B", msg_id="2", raw_text="beta")
    payload = serialize_txt(
        [a, b],
        community_id="fam-A",
        requester_user_id="user-1",
        generated_at=datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC),
    )
    text = payload.decode("utf-8")
    assert "alpha\n\nsource_message_id: src-B" in text


def test_txt_serializer_empty_records_still_produces_header() -> None:
    payload = serialize_txt(
        [],
        community_id="fam-A",
        requester_user_id="user-1",
        generated_at=datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC),
    )
    text = payload.decode("utf-8")
    assert "# record_count: 0\n" in text
    assert "source_message_id:" not in text
