"""Telegram-adapter tests for ``/drafts`` recall (D-030)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from diary_rag.adapters.embeddings import MockEmbeddingClient
from diary_rag.adapters.telegram.webhook import get_dispatcher, get_telegram_client
from diary_rag.app import create_app
from diary_rag.config import Settings
from diary_rag.core.diary.models import SourceMessage
from diary_rag.core.routing import RouteKind
from diary_rag.services import DiaryService, Dispatcher, ExportService, QueryService
from diary_rag.storage.mock import MockDiaryStore


class RecordingTelegramClient:
    def __init__(self) -> None:
        self.message_calls: list[dict[str, Any]] = []
        self.document_calls: list[dict[str, Any]] = []

    def send_document(
        self,
        *,
        chat_id: str,
        filename: str,
        content: bytes,
        media_type: str,
        caption: str | None = None,
    ) -> None:
        self.document_calls.append(
            {
                "chat_id": chat_id,
                "filename": filename,
                "content": content,
                "media_type": media_type,
                "caption": caption,
            }
        )

    def send_message(self, *, chat_id: str, text: str) -> None:
        self.message_calls.append({"chat_id": chat_id, "text": text})


class FailingOnNthMessage:
    """Records messages and raises on the ``fail_at``-th ``send_message`` call."""

    def __init__(self, fail_at: int) -> None:
        self.message_calls: list[dict[str, Any]] = []
        self._fail_at = fail_at

    def send_document(self, **kwargs: Any) -> None:  # pragma: no cover - unused
        raise AssertionError("send_document should not be invoked for /drafts")

    def send_message(self, *, chat_id: str, text: str) -> None:
        self.message_calls.append({"chat_id": chat_id, "text": text})
        if len(self.message_calls) == self._fail_at:
            raise RuntimeError("simulated outbound failure")


def _settings(**overrides: Any) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        telegram_webhook_secret="test-secret",
        **overrides,
    )


def _build_client(
    settings: Settings,
    telegram_client: Any | None = None,
) -> tuple[TestClient, MockDiaryStore, Any]:
    store = MockDiaryStore()
    embed = MockEmbeddingClient()
    dispatcher = Dispatcher(
        DiaryService(store, embedding_client=embed),
        QueryService(store, store, embed),
        ExportService(store),
        settings,
    )
    if telegram_client is None:
        telegram_client = RecordingTelegramClient()
    app = create_app(settings)
    app.dependency_overrides[get_dispatcher] = lambda: dispatcher
    app.dependency_overrides[get_telegram_client] = lambda: telegram_client
    return TestClient(app), store, telegram_client


def _post(client: TestClient, payload: dict[str, Any]) -> Any:
    return client.post(
        "/telegram/webhook",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
    )


def _update(text: str, *, update_id: int = 1, message_id: int = 1) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": message_id,
            "date": 1715300000 + update_id,
            "chat": {"id": 42},
            "from": {"id": 7},
            "text": text,
        },
    }


def _seed_short_drafts(store: MockDiaryStore, *, count: int) -> None:
    base = datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC)
    for i in range(count):
        store.save_source_message(
            SourceMessage(
                source_message_id=f"draft-id-{i:03d}",
                family_id="42",
                author_user_id="7",
                external_chat_id="42",
                external_user_id="7",
                external_message_id=f"m-{i}",
                edit_seq=0,
                raw_text=f"draft body #{i}",
                detected_route=RouteKind.DRAFT,
                created_at=base.replace(minute=i),
            )
        )


# ---------------------------------------------------------------------------


def test_drafts_typical_case_delivers_one_combined_outbound_message() -> None:
    client, store, tg = _build_client(_settings())
    _seed_short_drafts(store, count=3)

    response = _post(client, _update("/drafts"))

    assert response.status_code == 200
    assert response.json() == {}
    assert isinstance(tg, RecordingTelegramClient)
    # One combined outbound message holding the header + all three drafts.
    assert len(tg.message_calls) == 1
    body = tg.message_calls[0]["text"]
    assert body.startswith("Most recent 3 drafts:")
    for i in range(3):
        assert f"draft body #{i}" in body
    # Most-recent-first ordering: draft #2 (latest by minute) appears before #1, then #0.
    assert body.index("draft body #2") < body.index("draft body #1") < body.index("draft body #0")


def test_drafts_empty_returns_inline_send_message_with_no_outbound() -> None:
    client, _store, tg = _build_client(_settings())

    response = _post(client, _update("/drafts"))

    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "sendMessage"
    assert body["text"] == "No drafts to show."
    assert isinstance(tg, RecordingTelegramClient)
    assert tg.message_calls == []


def test_drafts_usage_error_returns_inline_send_message_with_no_outbound() -> None:
    client, store, tg = _build_client(_settings())
    _seed_short_drafts(store, count=3)

    response = _post(client, _update("/drafts foo"))

    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "sendMessage"
    assert "Usage" in body["text"]
    assert isinstance(tg, RecordingTelegramClient)
    assert tg.message_calls == []


def test_drafts_overflow_splits_into_multiple_outbound_messages_at_block_boundaries() -> None:
    client, store, tg = _build_client(_settings(drafts_max_limit=50))
    # Seed enough drafts that the combined payload (~each block ~1500 chars) overflows.
    base = datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC)
    for i in range(6):
        store.save_source_message(
            SourceMessage(
                source_message_id=f"big-{i:02d}",
                family_id="42",
                author_user_id="7",
                external_chat_id="42",
                external_user_id="7",
                external_message_id=f"b-{i}",
                edit_seq=0,
                raw_text="x" * 1500,
                detected_route=RouteKind.DRAFT,
                created_at=base.replace(minute=i),
            )
        )

    response = _post(client, _update("/drafts 6"))

    assert response.status_code == 200
    assert response.json() == {}
    assert isinstance(tg, RecordingTelegramClient)
    # Multiple outbound messages, each under the 4096-char cap.
    assert len(tg.message_calls) >= 2
    for call in tg.message_calls:
        assert len(call["text"]) <= 4096
    # No block is split mid-text: every "x"*1500 run that appears must appear whole.
    combined = "".join(c["text"] for c in tg.message_calls)
    assert combined.count("x" * 1500) == 6


def test_drafts_oversized_block_emits_standalone_multipart_no_neighbour_interleaving() -> None:
    client, store, tg = _build_client(_settings())
    base = datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC)
    # Short before, oversized middle, short after — ordered most-recent-first
    # in storage means the *after* draft has the latest created_at.
    store.save_source_message(
        SourceMessage(
            source_message_id="short-before",
            family_id="42",
            author_user_id="7",
            external_chat_id="42",
            external_user_id="7",
            external_message_id="b1",
            edit_seq=0,
            raw_text="short before",
            detected_route=RouteKind.DRAFT,
            created_at=base.replace(minute=0),
        )
    )
    store.save_source_message(
        SourceMessage(
            source_message_id="oversized-mid",
            family_id="42",
            author_user_id="7",
            external_chat_id="42",
            external_user_id="7",
            external_message_id="b2",
            edit_seq=0,
            raw_text="Y" * 8000,
            detected_route=RouteKind.DRAFT,
            created_at=base.replace(minute=1),
        )
    )
    store.save_source_message(
        SourceMessage(
            source_message_id="short-after",
            family_id="42",
            author_user_id="7",
            external_chat_id="42",
            external_user_id="7",
            external_message_id="b3",
            edit_seq=0,
            raw_text="short after",
            detected_route=RouteKind.DRAFT,
            created_at=base.replace(minute=2),
        )
    )

    response = _post(client, _update("/drafts 3"))

    assert response.status_code == 200
    assert isinstance(tg, RecordingTelegramClient)
    msgs = [c["text"] for c in tg.message_calls]
    # Find part messages (oversized split).
    part_indices = [i for i, m in enumerate(msgs) if m.endswith(")") and "(part " in m]
    assert part_indices, "oversized draft should produce multipart parts"
    # Parts must not contain any neighbour content.
    for i in part_indices:
        assert "short before" not in msgs[i]
        assert "short after" not in msgs[i]
    # The first part must not share its message with the header or short-before
    # (which represents the chronologically-later, most-recent-first ordering).
    first_part = part_indices[0]
    if first_part > 0:
        assert "Y" not in msgs[first_part - 1]


def test_drafts_partial_failure_aborts_and_sends_error_outbound(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failing = FailingOnNthMessage(fail_at=2)
    client, store, _tg = _build_client(_settings(drafts_max_limit=50), telegram_client=failing)
    # Seed many drafts so packing produces ≥ 2 outbound messages.
    base = datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC)
    for i in range(6):
        store.save_source_message(
            SourceMessage(
                source_message_id=f"big-{i:02d}",
                family_id="42",
                author_user_id="7",
                external_chat_id="42",
                external_user_id="7",
                external_message_id=f"b-{i}",
                edit_seq=0,
                raw_text="x" * 2000,
                detected_route=RouteKind.DRAFT,
                created_at=base.replace(minute=i),
            )
        )

    with caplog.at_level(logging.WARNING, logger="diary_rag.adapters.telegram.webhook"):
        response = _post(client, _update("/drafts 6"))

    assert response.status_code == 200
    assert response.json() == {}
    # The failing client recorded the first (successful) call, then raised on the 2nd,
    # and the error reply attempt was recorded too.
    texts = [c["text"] for c in failing.message_calls]
    assert any("Couldn't deliver all drafts" in t for t in texts)
    assert any("drafts.delivery_failed" in line for line in caplog.text.splitlines())


def test_drafts_log_drafts_delivered_on_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, store, _tg = _build_client(_settings())
    _seed_short_drafts(store, count=2)

    with caplog.at_level(logging.INFO, logger="diary_rag.adapters.telegram.webhook"):
        response = _post(client, _update("/drafts"))

    assert response.status_code == 200
    assert any("drafts.delivered" in line for line in caplog.text.splitlines())
