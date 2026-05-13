"""Dispatcher tests for the ``/drafts`` recall branch (D-030)."""

from __future__ import annotations

from datetime import UTC, datetime

from diary_rag.adapters.answers import MockChatClient
from diary_rag.adapters.embeddings import MockEmbeddingClient
from diary_rag.config import Settings
from diary_rag.core.diary.models import SourceMessage
from diary_rag.core.routing import InboundMessage, RouteKind
from diary_rag.services import DiaryService, Dispatcher, ExportService, QueryService
from diary_rag.storage.mock import MockDiaryStore


def _settings(*, default: int = 5, maximum: int = 20) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        drafts_default_limit=default,
        drafts_max_limit=maximum,
    )


def _dispatcher(settings: Settings) -> tuple[Dispatcher, MockDiaryStore]:
    store = MockDiaryStore()
    embed = MockEmbeddingClient()
    chat = MockChatClient()
    return (
        Dispatcher(
            DiaryService(store, embedding_client=embed),
            QueryService(store, store, embed, chat),
            ExportService(store),
            settings,
        ),
        store,
    )


def _seed_drafts(store: MockDiaryStore, *, count: int, family: str = "42") -> None:
    base = datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC)
    for i in range(count):
        store.save_source_message(
            SourceMessage(
                source_message_id=f"d-{i:03d}",
                family_id=family,
                author_user_id="7",
                external_chat_id=family,
                external_user_id="7",
                external_message_id=f"m-{i}",
                edit_seq=0,
                raw_text=f"draft body #{i}",
                detected_route=RouteKind.DRAFT,
                created_at=base.replace(minute=i),
            )
        )


def _inbound(payload: str = "") -> InboundMessage:
    return InboundMessage(
        external_message_id="999",
        external_chat_id="42",
        external_user_id="7",
        text=f"/drafts {payload}".rstrip(),
        route=RouteKind.DRAFTS,
        received_at=datetime(2026, 5, 10, tzinfo=UTC),
        route_source="command",
        payload=payload,
    )


def test_drafts_default_serves_default_limit_when_no_payload() -> None:
    settings = _settings(default=5, maximum=20)
    dispatcher, store = _dispatcher(settings)
    _seed_drafts(store, count=7)

    result = dispatcher.dispatch(_inbound(""))

    assert result.route is RouteKind.DRAFTS
    assert result.drafts is not None and len(result.drafts) == 5
    assert result.reply_text == "Most recent 5 drafts:"


def test_drafts_explicit_n_within_max_returns_exact_count() -> None:
    settings = _settings(maximum=20)
    dispatcher, store = _dispatcher(settings)
    _seed_drafts(store, count=10)

    result = dispatcher.dispatch(_inbound("3"))

    assert result.drafts is not None and len(result.drafts) == 3
    assert result.reply_text == "Most recent 3 drafts:"


def test_drafts_more_requested_than_exist_returns_all_with_diagnostic_header() -> None:
    settings = _settings(maximum=20)
    dispatcher, store = _dispatcher(settings)
    _seed_drafts(store, count=3)

    result = dispatcher.dispatch(_inbound("5"))

    assert result.drafts is not None and len(result.drafts) == 3
    assert result.reply_text == "Showing all 3 drafts (you asked for 5)."


def test_drafts_n_above_max_clamps_silently_and_reflects_in_header() -> None:
    settings = _settings(maximum=20)
    dispatcher, store = _dispatcher(settings)
    _seed_drafts(store, count=50)

    result = dispatcher.dispatch(_inbound("100"))

    assert result.drafts is not None and len(result.drafts) == 20
    assert result.reply_text == "Showing the 20 most recent drafts (you asked for 100)."


def test_drafts_n_above_max_with_fewer_drafts_prefers_availability_message() -> None:
    settings = _settings(maximum=20)
    dispatcher, store = _dispatcher(settings)
    _seed_drafts(store, count=5)

    result = dispatcher.dispatch(_inbound("100"))

    assert result.drafts is not None and len(result.drafts) == 5
    assert result.reply_text == "Showing all 5 drafts (you asked for 100)."


def test_drafts_empty_returns_header_only_no_drafts_payload() -> None:
    settings = _settings()
    dispatcher, _ = _dispatcher(settings)

    result = dispatcher.dispatch(_inbound(""))

    assert result.drafts is None
    assert result.reply_text == "No drafts to show."


def test_drafts_zero_returns_usage_reply() -> None:
    settings = _settings()
    dispatcher, store = _dispatcher(settings)
    _seed_drafts(store, count=3)

    result = dispatcher.dispatch(_inbound("0"))

    assert result.drafts is None
    assert "Usage" in result.reply_text
    assert result.metadata["fallback"] == "invalid_input"


def test_drafts_negative_returns_usage_reply() -> None:
    settings = _settings()
    dispatcher, store = _dispatcher(settings)
    _seed_drafts(store, count=3)

    result = dispatcher.dispatch(_inbound("-3"))

    assert result.drafts is None
    assert "Usage" in result.reply_text
    assert result.metadata["fallback"] == "invalid_input"


def test_drafts_non_integer_returns_usage_reply() -> None:
    settings = _settings()
    dispatcher, store = _dispatcher(settings)
    _seed_drafts(store, count=3)

    result = dispatcher.dispatch(_inbound("foo"))

    assert result.drafts is None
    assert "Usage" in result.reply_text
    assert result.metadata["fallback"] == "invalid_input"


def test_drafts_singular_when_only_one_returned() -> None:
    settings = _settings()
    dispatcher, store = _dispatcher(settings)
    _seed_drafts(store, count=1)

    result = dispatcher.dispatch(_inbound("1"))

    assert result.reply_text == "Most recent 1 draft:"


def test_drafts_default_with_no_drafts_does_not_carry_explicit_request() -> None:
    settings = _settings(default=5)
    dispatcher, _ = _dispatcher(settings)

    result = dispatcher.dispatch(_inbound(""))

    # No "you asked for" trailer when the user did not explicitly ask.
    assert "asked for" not in result.reply_text
