"""Raw-export serializers (D-029).

Pure functions that turn an ordered ``list[SourceMessage]`` plus the
scope and a generation timestamp into UTF-8 bytes carrying an inline
provenance envelope.

Schema is versioned via ``SCHEMA_VERSION`` so downstream tooling can
detect drift without inspecting field shapes.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime

from diary_rag.core.domain.models import SourceMessage

SCHEMA_VERSION = 1


def _record_dict(source: SourceMessage) -> dict[str, object]:
    return {
        "source_message_id": source.source_message_id,
        "community_id": source.community_id,
        "author_user_id": source.author_user_id,
        "external_chat_id": source.external_chat_id,
        "external_user_id": source.external_user_id,
        "external_message_id": source.external_message_id,
        "edit_seq": source.edit_seq,
        "raw_text": source.raw_text,
        "detected_route": source.detected_route.value,
        "created_at": source.created_at.isoformat(),
    }


def _envelope_dict(
    *,
    format_name: str,
    community_id: str,
    requester_user_id: str,
    generated_at: datetime,
    record_count: int,
) -> dict[str, object]:
    return {
        "format": format_name,
        "schema_version": SCHEMA_VERSION,
        "scope": {
            "community_id": community_id,
            "requester_user_id": requester_user_id,
        },
        "generated_at": generated_at.isoformat(),
        "record_count": record_count,
    }


def serialize_json(
    messages: Iterable[SourceMessage],
    *,
    community_id: str,
    requester_user_id: str,
    generated_at: datetime,
) -> bytes:
    """Serialize source messages as a self-describing JSON document."""
    records = [_record_dict(m) for m in messages]
    envelope = _envelope_dict(
        format_name="json",
        community_id=community_id,
        requester_user_id=requester_user_id,
        generated_at=generated_at,
        record_count=len(records),
    )
    document = {"export": envelope, "records": records}
    return json.dumps(document, indent=2, ensure_ascii=False, sort_keys=False).encode("utf-8")


_TXT_BLOCK_FIELDS: tuple[str, ...] = (
    "source_message_id",
    "created_at",
    "detected_route",
    "external_chat_id",
    "external_message_id",
    "edit_seq",
    "author_user_id",
)


def _txt_block(source: SourceMessage) -> str:
    lines = [
        f"source_message_id: {source.source_message_id}",
        f"created_at: {source.created_at.isoformat()}",
        f"detected_route: {source.detected_route.value}",
        f"external_chat_id: {source.external_chat_id}",
        f"external_message_id: {source.external_message_id}",
        f"edit_seq: {source.edit_seq}",
        f"author_user_id: {source.author_user_id}",
        "raw_text:",
        source.raw_text,
    ]
    return "\n".join(lines)


def serialize_txt(
    messages: Iterable[SourceMessage],
    *,
    community_id: str,
    requester_user_id: str,
    generated_at: datetime,
) -> bytes:
    """Serialize source messages as a TXT document with a ``#``-prefixed header."""
    records = list(messages)
    header_lines = [
        "# raw export",
        "# format: txt",
        f"# schema_version: {SCHEMA_VERSION}",
        f"# community_id: {community_id}",
        f"# requester_user_id: {requester_user_id}",
        f"# generated_at: {generated_at.isoformat()}",
        f"# record_count: {len(records)}",
    ]
    parts = ["\n".join(header_lines), ""]
    for record in records:
        parts.append(_txt_block(record))
        parts.append("")
    text = "\n".join(parts)
    if not text.endswith("\n"):
        text += "\n"
    return text.encode("utf-8")
