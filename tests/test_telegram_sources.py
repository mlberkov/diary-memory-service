"""Telegram-adapter tests for ``/sources`` outbound delivery (Slice 4.4, D-036).

Asserts the webhook's outbound branch for ``DispatchResult.source_chunks``:

- Default delivery is one combined ``send_message`` (header + all blocks).
- Each block carries an adapter-resolved ``— <author>`` attribution line
  (D-086): ``@username → first_name → user-<last8>`` fallback chain.
- Multi-message split activates when the combined payload exceeds the
  4096-char cap; splits land on whole-block boundaries.
- The fail-closed reply path returns inline ``sendMessage`` with no
  outbound call.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from fastapi.testclient import TestClient

from memory_rag.adapters.answers import MockChatClient
from memory_rag.adapters.embeddings import MockEmbeddingClient
from memory_rag.adapters.telegram.webhook import (
    get_backend_store,
    get_dispatcher,
    get_telegram_client,
)
from memory_rag.app import create_app
from memory_rag.config import Settings
from memory_rag.core.domain import AnswerResult, Evidence, FallbackMode
from memory_rag.core.domain.models import AnswerContext, EventChunk, SourceMessage
from memory_rag.core.embeddings import EmbeddingStatus
from memory_rag.core.routing import InboundMessage, RouteKind
from memory_rag.services import Dispatcher, DomainService, ExportService, QueryService
from memory_rag.storage.mock import MockDomainStore


class _RecordingTelegramClient:
    def __init__(self) -> None:
        self.message_calls: list[dict[str, Any]] = []

    def send_document(self, **kwargs: Any) -> None:  # pragma: no cover - unused
        raise AssertionError("send_document should not be called for /sources")

    def send_message(self, *, chat_id: str, text: str) -> None:
        self.message_calls.append({"chat_id": chat_id, "text": text})


def _settings() -> Settings:
    return Settings(_env_file=None, telegram_webhook_secret="test-secret")  # type: ignore[call-arg]


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


def _chunk(chunk_id: str, text: str) -> EventChunk:
    return EventChunk(
        chunk_id=chunk_id,
        note_id=f"e-{chunk_id}",
        source_message_id=f"s-{chunk_id}",
        community_id="42",
        author_user_id="7",
        note_date=date(2026, 5, 9),
        event_index=0,
        chunk_text=text,
        created_at=datetime.now(tz=UTC),
        embedding_status=EmbeddingStatus.READY,
    )


class _FixedAnswerQueryService:
    def __init__(self, chunks: tuple[EventChunk, ...]) -> None:
        self._chunks = chunks

    def answer(self, message: InboundMessage) -> AnswerResult:
        context = AnswerContext(
            query_id="q-1",
            query_text=message.payload,
            ordered_chunks=self._chunks,
            model_name="mock",
            created_at=datetime.now(tz=UTC),
        )
        evidence = [
            Evidence(chunk_id=c.chunk_id, note_date=c.note_date, chunk_text=c.chunk_text)
            for c in self._chunks
        ]
        return AnswerResult(
            fallback=FallbackMode.NONE,
            query_text=message.payload,
            evidence=evidence,
            context=context,
            cited_chunk_ids=tuple(c.chunk_id for c in self._chunks),
            answer_text="Mock answer.",
        )


def _build_client(
    chunks: tuple[EventChunk, ...] | None = None,
    *,
    store: MockDomainStore | None = None,
) -> tuple[TestClient, _RecordingTelegramClient]:
    settings = _settings()
    store = store if store is not None else MockDomainStore()
    embed = MockEmbeddingClient()
    chat = MockChatClient()
    if chunks is None:
        query_service: Any = QueryService(store, store, embed, chat)
    else:
        query_service = _FixedAnswerQueryService(chunks)
    dispatcher = Dispatcher(
        DomainService(store, embedding_client=embed),
        query_service,
        ExportService(store),
        settings,
    )
    telegram_client = _RecordingTelegramClient()
    app = create_app(settings)
    app.dependency_overrides[get_dispatcher] = lambda: dispatcher
    app.dependency_overrides[get_telegram_client] = lambda: telegram_client
    # /sources author resolution reads through the backend store; point it at
    # the same store the dispatcher uses so lookups are deterministic (D-086).
    app.dependency_overrides[get_backend_store] = lambda: store
    return TestClient(app), telegram_client


def test_sources_after_ask_delivers_one_combined_outbound_message() -> None:
    chunks = (
        _chunk("c-1", "Tried a new book"),
        _chunk("c-2", "Had a calm morning"),
    )
    client, tg = _build_client(chunks=chunks)

    _post(client, _update("/ask book", update_id=1, message_id=1))
    response = _post(client, _update("/sources", update_id=2, message_id=2))

    assert response.status_code == 200
    assert response.json() == {}
    assert len(tg.message_calls) == 1
    body = tg.message_calls[0]["text"]
    assert body.startswith("Selected chunks for your last /ask (2 chunk(s)):")
    # No source row / snapshot persisted for these chunks → author falls to the
    # opaque short-ID floor `user-<last8>` (author_user_id="7").
    assert "[2026-05-09] (1/2)\n— user-7\n\nTried a new book" in body
    assert "[2026-05-09] (2/2)\n— user-7\n\nHad a calm morning" in body
    # As-is rendering: chunk text appears verbatim (no excerpt, no truncation).
    assert body.index("Tried a new book") < body.index("Had a calm morning")


def _save_source_and_snapshot(
    store: MockDomainStore,
    *,
    chunk: EventChunk,
    external_chat_id: str,
    external_message_id: str,
    edit_seq: int,
    username: str | None,
    first_name: str | None,
) -> None:
    """Persist a source row keyed to ``chunk`` plus its display-input snapshot."""
    store.save_source_message(
        SourceMessage(
            source_message_id=chunk.source_message_id,
            community_id=chunk.community_id,
            author_user_id=chunk.author_user_id,
            external_chat_id=external_chat_id,
            external_user_id=chunk.author_user_id,
            external_message_id=external_message_id,
            edit_seq=edit_seq,
            raw_text=chunk.chunk_text,
            detected_route=RouteKind.NOTE,
            created_at=datetime.now(tz=UTC),
        )
    )
    store.save_author_display_input(
        external_chat_id=external_chat_id,
        external_message_id=external_message_id,
        edit_seq=edit_seq,
        username=username,
        first_name=first_name,
    )


def test_sources_renders_resolved_author_tiers_from_snapshot() -> None:
    # Three chunks, one per fallback tier: @username, first_name, short-ID floor.
    c_user = _chunk("c-user", "Walked the dog")
    c_first = _chunk("c-first", "Read a book")
    c_floor = _chunk("c-floor", "Cooked dinner")
    store = MockDomainStore()
    _save_source_and_snapshot(
        store,
        chunk=c_user,
        external_chat_id="42",
        external_message_id="101",
        edit_seq=0,
        username="alice",
        first_name="Alice A",
    )
    _save_source_and_snapshot(
        store,
        chunk=c_first,
        external_chat_id="42",
        external_message_id="102",
        edit_seq=0,
        username=None,
        first_name="Bob",
    )
    _save_source_and_snapshot(
        store,
        chunk=c_floor,
        external_chat_id="42",
        external_message_id="103",
        edit_seq=0,
        username=None,
        first_name=None,
    )
    client, tg = _build_client(chunks=(c_user, c_first, c_floor), store=store)

    _post(client, _update("/ask anything", update_id=1, message_id=1))
    _post(client, _update("/sources", update_id=2, message_id=2))

    body = tg.message_calls[0]["text"]
    # username present → @username; first_name only → plain; both-null → floor
    # (author_user_id="7" → `user-7`).
    assert "[2026-05-09] (1/3)\n— @alice\n\nWalked the dog" in body
    assert "[2026-05-09] (2/3)\n— Bob\n\nRead a book" in body
    assert "[2026-05-09] (3/3)\n— user-7\n\nCooked dinner" in body


def test_sources_without_prior_ask_returns_inline_fail_closed_reply() -> None:
    client, tg = _build_client()

    response = _post(client, _update("/sources", update_id=1, message_id=1))

    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "sendMessage"
    assert body["text"] == "No selected chunks available — ask a question with /ask first."
    # Fail-closed reply uses the inline response body; no outbound call.
    assert tg.message_calls == []


def test_sources_after_cited_empty_ask_returns_inline_empty_cited_reply() -> None:
    # An /ask over an empty store yields a cited-empty NO_EVIDENCE answer
    # (cited_chunk_ids == ()), so /sources returns the empty-cited reply
    # inline — distinct from the never-asked reply — with no outbound call
    # (D-100).
    client, tg = _build_client()  # real QueryService over an empty store

    _post(client, _update("/ask nothing matches", update_id=1, message_id=1))
    response = _post(client, _update("/sources", update_id=2, message_id=2))

    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "sendMessage"
    assert body["text"] == "Your last /ask answer didn't cite any specific notes."
    assert tg.message_calls == []


def test_oversized_chunks_force_multi_message_split() -> None:
    # Each chunk text ~1500 chars; combined header + 3 blocks exceeds the 4096 cap.
    chunks = (
        _chunk("c-1", "x" * 1500),
        _chunk("c-2", "y" * 1500),
        _chunk("c-3", "z" * 1500),
    )
    client, tg = _build_client(chunks=chunks)

    _post(client, _update("/ask book", update_id=1, message_id=1))
    response = _post(client, _update("/sources", update_id=2, message_id=2))

    assert response.status_code == 200
    assert response.json() == {}
    # Combined payload exceeds the cap, so the packer splits at block boundaries.
    assert len(tg.message_calls) >= 2
    joined = "\n".join(call["text"] for call in tg.message_calls)
    # All three chunk bodies are present across the split messages.
    assert "x" * 1500 in joined
    assert "y" * 1500 in joined
    assert "z" * 1500 in joined
    # Header lands on the first message only.
    assert tg.message_calls[0]["text"].startswith("Selected chunks for your last /ask")
