"""Mock-backend tests for ``DomainRepository.list_source_messages`` (D-029)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from diary_rag.core.domain.models import SourceMessage
from diary_rag.core.routing import RouteKind
from diary_rag.storage.mock import MockDomainStore


def _source(
    *,
    sid: str,
    family_id: str = "fam-A",
    msg_id: str,
    raw_text: str = "hello",
    route: RouteKind = RouteKind.NOTE,
    created_at: datetime,
) -> SourceMessage:
    return SourceMessage(
        source_message_id=sid,
        family_id=family_id,
        author_user_id="user-1",
        external_chat_id=family_id,
        external_user_id="user-1",
        external_message_id=msg_id,
        edit_seq=0,
        raw_text=raw_text,
        detected_route=route,
        created_at=created_at,
    )


def test_mock_list_source_messages_is_family_scoped() -> None:
    store = MockDomainStore()
    now = datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC)
    store.save_source_message(_source(sid="a", family_id="fam-A", msg_id="1", created_at=now))
    store.save_source_message(_source(sid="b", family_id="fam-B", msg_id="2", created_at=now))

    rows = store.list_source_messages("fam-A")
    assert [r.source_message_id for r in rows] == ["a"]


def test_mock_list_source_messages_includes_notes_and_drafts() -> None:
    store = MockDomainStore()
    base = datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC)
    store.save_source_message(_source(sid="note", msg_id="1", created_at=base))
    store.save_source_message(
        _source(sid="draft", msg_id="2", route=RouteKind.DRAFT, created_at=base.replace(hour=11))
    )

    rows = store.list_source_messages("fam-A")
    routes = {r.detected_route for r in rows}
    assert routes == {RouteKind.NOTE, RouteKind.DRAFT}


def test_mock_list_source_messages_orders_by_created_at_then_source_message_id() -> None:
    store = MockDomainStore()
    same = datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC)
    later = same.replace(hour=11)
    store.save_source_message(_source(sid="later-one", msg_id="3", created_at=later))
    store.save_source_message(_source(sid="b", msg_id="2", created_at=same))
    store.save_source_message(_source(sid="a", msg_id="1", created_at=same))

    rows = store.list_source_messages("fam-A")
    assert [r.source_message_id for r in rows] == ["a", "b", "later-one"]


def test_mock_list_source_messages_respects_limit() -> None:
    store = MockDomainStore()
    base = datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC)
    for i in range(5):
        store.save_source_message(
            _source(sid=f"row-{i}", msg_id=str(i), created_at=base.replace(minute=i))
        )

    rows = store.list_source_messages("fam-A", limit=2)
    assert [r.source_message_id for r in rows] == ["row-0", "row-1"]


def test_mock_list_source_messages_empty_when_no_rows_for_family() -> None:
    store = MockDomainStore()
    assert store.list_source_messages("fam-A") == []


def test_mock_list_source_messages_rejects_empty_family_id() -> None:
    store = MockDomainStore()
    with pytest.raises(ValueError):
        store.list_source_messages("")


def test_mock_list_source_messages_rejects_negative_limit() -> None:
    store = MockDomainStore()
    with pytest.raises(ValueError):
        store.list_source_messages("fam-A", limit=-1)
