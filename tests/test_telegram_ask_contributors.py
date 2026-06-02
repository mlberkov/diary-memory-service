"""Telegram-adapter tests for the ``/ask``-reply contributor footer (D-091).

Asserts the webhook's outbound ASK render path for
``DispatchResult.grounding_chunks``:

- A grounded reply appends a single ``Contributors: …`` footer line beneath
  ``answer_text``, blank-line separated; contributors are the distinct authors
  of the grounding chunks, deduped by opaque ``author_user_id`` in
  first-appearance order, resolved through the adapter-only fallback chain.
- ``WEAK_EVIDENCE`` / ``AMBIGUOUS`` (which carry grounding chunks) keep the
  footer beneath their trailer.
- ``NO_EVIDENCE`` / empty-query / ``PROVIDER_UNAVAILABLE`` (no grounding
  chunks) render no footer — byte-identical to the pre-D-091 reply.
- Author resolution is requester-``community_id``-scoped (D-089): a chunk whose
  source is owned by another community resolves to the opaque floor.
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
    # Contributor resolution reads through the backend store; point it at the
    # same store the dispatcher uses so lookups are deterministic (D-086 / D-089).
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


def test_grounded_ask_reply_appends_contributors_footer() -> None:
    # Two distinct authors resolved via the @username tier, deduped and ordered
    # by first appearance over the grounding chunks.
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
    assert body["text"] == "Mock answer.\n\nContributors: @alice, @bob"


def test_grounded_ask_footer_dedups_and_preserves_first_appearance() -> None:
    # Authors appear alice, bob, alice — alice deduped to one entry, order kept.
    c_a1 = _chunk("c-1", "one", author_user_id="user-alice000")
    c_b = _chunk("c-2", "two", author_user_id="user-bob00000")
    c_a2 = _chunk("c-3", "three", author_user_id="user-alice000")
    store = MockDomainStore()
    _save_source_and_snapshot(
        store, chunk=c_a1, external_message_id="101", username="alice", first_name=None
    )
    _save_source_and_snapshot(
        store, chunk=c_b, external_message_id="102", username="bob", first_name=None
    )
    _save_source_and_snapshot(
        store, chunk=c_a2, external_message_id="103", username="alice", first_name=None
    )
    client, _tg = _build_client(_FixedAnswerQueryService((c_a1, c_b, c_a2)), store=store)

    body = _post(client, _update("/ask anything")).json()
    assert body["text"] == "Mock answer.\n\nContributors: @alice, @bob"


def test_weak_evidence_ask_reply_keeps_footer_beneath_trailer() -> None:
    c = _chunk("c-1", "note", author_user_id="user-alice000")
    store = MockDomainStore()
    _save_source_and_snapshot(
        store, chunk=c, external_message_id="101", username="alice", first_name=None
    )
    client, _tg = _build_client(
        _FixedAnswerQueryService((c,), fallback=FallbackMode.WEAK_EVIDENCE), store=store
    )

    body = _post(client, _update("/ask thing")).json()
    # The footer sits beneath the weak-evidence trailer, which itself sits
    # beneath the answer body.
    assert body["text"] == (
        "Mock answer.\n\n(weak evidence — model expressed uncertainty)" "\n\nContributors: @alice"
    )


def test_no_evidence_ask_reply_has_no_footer() -> None:
    # NO_EVIDENCE with no grounding context → grounding_chunks is None → no
    # footer; the reply is byte-identical to the pre-D-091 surface.
    store = MockDomainStore()
    client, _tg = _build_client(
        _FixedAnswerQueryService((), fallback=FallbackMode.NO_EVIDENCE, with_context=False),
        store=store,
    )

    body = _post(client, _update("/ask nothing matches")).json()
    assert "Contributors:" not in body["text"]
    assert body["text"] == (
        "Nothing in your saved notes matched 'nothing matches'. "
        "Try rephrasing the question, or use words that appear in your notes."
    )


def test_grounded_ask_footer_floor_when_source_in_other_community() -> None:
    # The grounding chunk's source is owned by community "99"; the requester is
    # community "42". The community-scoped read returns None, so the contributor
    # resolves to the opaque floor — the read never crosses a community boundary
    # (D-089, I-7). author_user_id="user-XYZ12345" → floor `user-XYZ12345` (last8).
    c = _chunk("c-1", "note", author_user_id="user-XYZ12345", community_id="99")
    store = MockDomainStore()
    # Source persisted under the other community; the requester ("42") cannot read it.
    _save_source_and_snapshot(
        store, chunk=c, external_message_id="101", username="mallory", first_name=None
    )
    client, _tg = _build_client(_FixedAnswerQueryService((c,)), store=store)

    body = _post(client, _update("/ask cross")).json()
    assert body["text"] == "Mock answer.\n\nContributors: user-XYZ12345"
