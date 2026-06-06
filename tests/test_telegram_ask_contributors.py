"""Telegram-adapter guard: the ``/ask`` reply carries no contributor footer (D-101).

The ``Contributors: …`` footer (contract D-091, code D-092) was removed as a
user-facing element: ``/sources`` (cited-only, D-100) is the sole attribution
surface. These tests pin the removal at the webhook's outbound ASK render path —
even when the grounding chunks have fully resolvable authors, no footer (and no
adapter-composed display name) is appended to the reply.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from fastapi.testclient import TestClient

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
from memory_rag.services import Dispatcher, DomainService, ExportService
from memory_rag.storage.mock import MockDomainStore


class _RecordingTelegramClient:
    def __init__(self) -> None:
        self.message_calls: list[dict[str, Any]] = []

    def send_document(self, **kwargs: Any) -> None:  # pragma: no cover - unused
        raise AssertionError("send_document should not be called for /ask")

    def send_message(self, *, chat_id: str, text: str) -> None:  # pragma: no cover
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


def _chunk(
    chunk_id: str,
    text: str,
    *,
    author_user_id: str = "7",
    community_id: str = "42",
) -> EventChunk:
    return EventChunk(
        chunk_id=chunk_id,
        note_id=f"e-{chunk_id}",
        source_message_id=f"s-{chunk_id}",
        community_id=community_id,
        author_user_id=author_user_id,
        note_date=date(2026, 5, 9),
        event_index=0,
        chunk_text=text,
        created_at=datetime.now(tz=UTC),
        embedding_status=EmbeddingStatus.READY,
    )


class _FixedAnswerQueryService:
    """Returns a fixed answer; ``fallback`` selects the rendered contour."""

    def __init__(
        self,
        chunks: tuple[EventChunk, ...],
        *,
        fallback: FallbackMode = FallbackMode.NONE,
        answer_text: str = "Mock answer.",
        with_context: bool = True,
    ) -> None:
        self._chunks = chunks
        self._fallback = fallback
        self._answer_text = answer_text
        self._with_context = with_context

    def answer(self, message: InboundMessage) -> AnswerResult:
        context = None
        if self._with_context:
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
            fallback=self._fallback,
            query_text=message.payload,
            evidence=evidence,
            context=context,
            answer_text=self._answer_text,
            cited_chunk_ids=tuple(c.chunk_id for c in self._chunks),
        )


def _build_client(
    query_service: Any,
    *,
    store: MockDomainStore,
) -> tuple[TestClient, _RecordingTelegramClient]:
    settings = _settings()
    embed = MockEmbeddingClient()
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
    # The author display store is still wired (it backs /sources); point it at the
    # same store so a footer, if any were composed, would resolve real names.
    app.dependency_overrides[get_backend_store] = lambda: store
    return TestClient(app), telegram_client


def _save_source_and_snapshot(
    store: MockDomainStore,
    *,
    chunk: EventChunk,
    external_message_id: str,
    username: str | None,
    first_name: str | None,
) -> None:
    store.save_source_message(
        SourceMessage(
            source_message_id=chunk.source_message_id,
            community_id=chunk.community_id,
            author_user_id=chunk.author_user_id,
            external_chat_id="42",
            external_user_id=chunk.author_user_id,
            external_message_id=external_message_id,
            edit_seq=0,
            raw_text=chunk.chunk_text,
            detected_route=RouteKind.NOTE,
            created_at=datetime.now(tz=UTC),
        )
    )
    store.save_author_display_input(
        external_chat_id="42",
        external_message_id=external_message_id,
        edit_seq=0,
        username=username,
        first_name=first_name,
    )


def test_grounded_ask_reply_has_no_contributors_footer() -> None:
    # Two grounding chunks with fully resolvable @username authors. Pre-D-101 this
    # appended "Contributors: @alice, @bob"; the footer is now gone, so the reply
    # is the answer text alone, with no footer and no adapter-composed name.
    c_alice = _chunk("c-1", "Tried a new book", author_user_id="user-alice000")
    c_bob = _chunk("c-2", "Had a calm morning", author_user_id="user-bob00000")
    store = MockDomainStore()
    _save_source_and_snapshot(
        store, chunk=c_alice, external_message_id="101", username="alice", first_name=None
    )
    _save_source_and_snapshot(
        store, chunk=c_bob, external_message_id="102", username="bob", first_name=None
    )
    client, _tg = _build_client(_FixedAnswerQueryService((c_alice, c_bob)), store=store)

    response = _post(client, _update("/ask book"))

    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "sendMessage"
    assert body["text"] == "Mock answer."
    assert "Contributors:" not in body["text"]
    assert "@" not in body["text"]


def test_weak_evidence_ask_reply_has_no_footer_beneath_trailer() -> None:
    # WEAK_EVIDENCE carries grounding chunks (so it would have carried a footer);
    # the reply now ends at the evidence-strength trailer, with no footer below it.
    c = _chunk("c-1", "note", author_user_id="user-alice000")
    store = MockDomainStore()
    _save_source_and_snapshot(
        store, chunk=c, external_message_id="101", username="alice", first_name=None
    )
    client, _tg = _build_client(
        _FixedAnswerQueryService((c,), fallback=FallbackMode.WEAK_EVIDENCE), store=store
    )

    body = _post(client, _update("/ask thing")).json()
    assert body["text"] == "Mock answer.\n\n(weak evidence — model expressed uncertainty)"
    assert "Contributors:" not in body["text"]
