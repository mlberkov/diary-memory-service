"""Unit tests for ``ExportService`` (D-029)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import pytest

from diary_rag.core.domain.models import SourceMessage
from diary_rag.core.export.models import ExportFormat
from diary_rag.core.routing import RouteKind
from diary_rag.services.export_service import ExportService
from diary_rag.storage.mock import MockDomainStore


def _source(
    *,
    sid: str,
    family_id: str = "fam-A",
    author: str = "user-1",
    msg_id: str,
    raw_text: str = "hello",
    route: RouteKind = RouteKind.NOTE,
    created_at: datetime,
) -> SourceMessage:
    return SourceMessage(
        source_message_id=sid,
        family_id=family_id,
        author_user_id=author,
        external_chat_id=family_id,
        external_user_id=author,
        external_message_id=msg_id,
        edit_seq=0,
        raw_text=raw_text,
        detected_route=route,
        created_at=created_at,
    )


def _seed_two_families(store: MockDomainStore) -> None:
    base = datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC)
    store.save_source_message(
        _source(sid="A-1", family_id="fam-A", msg_id="1", raw_text="alpha", created_at=base)
    )
    store.save_source_message(
        _source(
            sid="A-2",
            family_id="fam-A",
            msg_id="2",
            raw_text="beta",
            route=RouteKind.DRAFT,
            created_at=base.replace(hour=11),
        )
    )
    store.save_source_message(
        _source(
            sid="B-1",
            family_id="fam-B",
            msg_id="3",
            raw_text="other family",
            created_at=base,
        )
    )


def test_export_json_envelope_includes_notes_and_drafts_in_order() -> None:
    store = MockDomainStore()
    _seed_two_families(store)
    service = ExportService(store)

    payload = service.export(
        family_id="fam-A",
        requester_user_id="user-1",
        format=ExportFormat.JSON,
    )
    document = json.loads(payload.content.decode("utf-8"))
    assert payload.format is ExportFormat.JSON
    assert payload.media_type == "application/json"
    assert payload.record_count == 2
    assert document["export"]["scope"]["family_id"] == "fam-A"
    assert document["export"]["scope"]["requester_user_id"] == "user-1"
    ids = [r["source_message_id"] for r in document["records"]]
    routes = [r["detected_route"] for r in document["records"]]
    assert ids == ["A-1", "A-2"]
    assert routes == ["note", "draft"]


def test_export_txt_format_uses_text_media_type_and_block_layout() -> None:
    store = MockDomainStore()
    _seed_two_families(store)
    service = ExportService(store)

    payload = service.export(
        family_id="fam-A",
        requester_user_id="user-1",
        format=ExportFormat.TXT,
    )
    text = payload.content.decode("utf-8")
    assert payload.media_type == "text/plain; charset=utf-8"
    assert text.startswith("# raw export\n")
    assert "source_message_id: A-1" in text
    assert "source_message_id: A-2" in text
    assert text.index("source_message_id: A-1") < text.index("source_message_id: A-2")


def test_export_family_scoped_excludes_other_families() -> None:
    store = MockDomainStore()
    _seed_two_families(store)
    service = ExportService(store)

    payload = service.export(
        family_id="fam-A",
        requester_user_id="user-1",
        format=ExportFormat.JSON,
    )
    document = json.loads(payload.content.decode("utf-8"))
    ids = [r["source_message_id"] for r in document["records"]]
    assert "B-1" not in ids


def test_export_empty_scope_produces_valid_empty_envelope() -> None:
    store = MockDomainStore()
    service = ExportService(store)

    payload = service.export(
        family_id="fam-empty",
        requester_user_id="user-1",
        format=ExportFormat.JSON,
    )
    document = json.loads(payload.content.decode("utf-8"))
    assert payload.record_count == 0
    assert document["records"] == []
    assert document["export"]["record_count"] == 0


def test_export_deterministic_ordering_breaks_created_at_ties_by_source_message_id() -> None:
    store = MockDomainStore()
    same = datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC)
    store.save_source_message(
        _source(sid="b-second-id", family_id="fam-A", msg_id="2", created_at=same)
    )
    store.save_source_message(
        _source(sid="a-first-id", family_id="fam-A", msg_id="1", created_at=same)
    )
    service = ExportService(store)

    payload = service.export(
        family_id="fam-A",
        requester_user_id="user-1",
        format=ExportFormat.JSON,
    )
    document = json.loads(payload.content.decode("utf-8"))
    ids = [r["source_message_id"] for r in document["records"]]
    assert ids == ["a-first-id", "b-second-id"]


def test_export_filename_carries_family_and_timestamp() -> None:
    store = MockDomainStore()
    service = ExportService(store)
    payload = service.export(
        family_id="fam-A",
        requester_user_id="user-1",
        format=ExportFormat.JSON,
    )
    assert payload.filename.startswith("raw_export_fam-A_")
    assert payload.filename.endswith(".json")


def test_export_logs_provenance(caplog: pytest.LogCaptureFixture) -> None:
    store = MockDomainStore()
    _seed_two_families(store)
    service = ExportService(store)

    with caplog.at_level(logging.INFO, logger="diary_rag.services.export_service"):
        service.export(
            family_id="fam-A",
            requester_user_id="user-1",
            format=ExportFormat.JSON,
        )

    line = next(line for line in caplog.text.splitlines() if "export.ok" in line)
    assert "family_id=fam-A" in line
    assert "format=json" in line
    assert "count=2" in line
    assert "bytes=" in line


def test_export_rejects_empty_family_id() -> None:
    service = ExportService(MockDomainStore())
    with pytest.raises(ValueError):
        service.export(family_id="", requester_user_id="user-1", format=ExportFormat.JSON)
