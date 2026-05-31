"""Author display-input capture + durable landing (D-084).

Two layers:

* **Backend parity** for the adapter-owned ``AuthorDisplayInputStore`` port
  across mock / sqlite / (gated) postgres — round-trip, nullable / withheld
  values, idempotent re-delivery, and edit behaviour, all verified through the
  port's own ``get_author_display_input`` read primitive.
* **Webhook integration** — capture fires only for source-message-bearing
  routes (note/draft), the values flow straight from ``message.from_``, and an
  ``/ask`` turn writes no snapshot.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from memory_rag.adapters.answers import MockChatClient
from memory_rag.adapters.embeddings import MockEmbeddingClient
from memory_rag.adapters.telegram.author_display import AuthorDisplayInputStore
from memory_rag.adapters.telegram.webhook import (
    get_author_display_input_store,
    get_dispatcher,
)
from memory_rag.app import create_app
from memory_rag.config import Settings
from memory_rag.services import Dispatcher, DomainService, ExportService, QueryService
from memory_rag.storage.mock import MockDomainStore
from memory_rag.storage.sqlite import SqliteDomainStore

PG_DSN = os.environ.get("MEMORY_RAG_PG_TEST_DSN")

pgmark = pytest.mark.skipif(
    PG_DSN is None,
    reason="MEMORY_RAG_PG_TEST_DSN not set; Postgres integration tests skipped.",
)

if PG_DSN is not None:
    import psycopg

    from memory_rag.storage.postgres import PostgresDomainStore

_CHAT = "chat-1"
_MSG = "msg-1"


# --------------------------------------------------------------------------- #
# Backend parity
# --------------------------------------------------------------------------- #
@pytest.fixture(params=["mock", "sqlite"] + (["postgres"] if PG_DSN else []))
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[AuthorDisplayInputStore]:
    if request.param == "mock":
        yield MockDomainStore()
    elif request.param == "sqlite":
        yield SqliteDomainStore(str(tmp_path / "display.db"))
    else:
        assert PG_DSN is not None
        with psycopg.connect(PG_DSN, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("TRUNCATE author_display_inputs RESTART IDENTITY CASCADE")
        s = PostgresDomainStore(PG_DSN)
        try:
            yield s
        finally:
            s.close()


def test_save_and_get_round_trip(store: AuthorDisplayInputStore) -> None:
    store.save_author_display_input(
        external_chat_id=_CHAT,
        external_message_id=_MSG,
        edit_seq=0,
        username="alice",
        first_name="Alice",
    )
    assert store.get_author_display_input(
        external_chat_id=_CHAT, external_message_id=_MSG, edit_seq=0
    ) == ("alice", "Alice")


def test_get_missing_returns_none(store: AuthorDisplayInputStore) -> None:
    assert (
        store.get_author_display_input(
            external_chat_id=_CHAT, external_message_id="absent", edit_seq=0
        )
        is None
    )


@pytest.mark.parametrize(
    ("username", "first_name"),
    [(None, "Alice"), ("alice", None), (None, None)],
)
def test_nullable_and_withheld_values_round_trip(
    store: AuthorDisplayInputStore, username: str | None, first_name: str | None
) -> None:
    # Both fields are nullable; a both-null snapshot is still written and read
    # back as a recorded "withheld" state (D-084).
    store.save_author_display_input(
        external_chat_id=_CHAT,
        external_message_id=_MSG,
        edit_seq=0,
        username=username,
        first_name=first_name,
    )
    assert store.get_author_display_input(
        external_chat_id=_CHAT, external_message_id=_MSG, edit_seq=0
    ) == (username, first_name)


def test_redelivery_is_idempotent_and_preserves_original(
    store: AuthorDisplayInputStore,
) -> None:
    store.save_author_display_input(
        external_chat_id=_CHAT,
        external_message_id=_MSG,
        edit_seq=0,
        username="alice",
        first_name="Alice",
    )
    # Same tuple re-delivered carrying DIFFERENT values must not overwrite the
    # original snapshot (R-2: no duplicate, no silent mutation).
    store.save_author_display_input(
        external_chat_id=_CHAT,
        external_message_id=_MSG,
        edit_seq=0,
        username="changed",
        first_name="Changed",
    )
    assert store.get_author_display_input(
        external_chat_id=_CHAT, external_message_id=_MSG, edit_seq=0
    ) == ("alice", "Alice")


def test_edit_lands_new_row_and_keeps_prior(store: AuthorDisplayInputStore) -> None:
    store.save_author_display_input(
        external_chat_id=_CHAT,
        external_message_id=_MSG,
        edit_seq=0,
        username="alice",
        first_name="Alice",
    )
    # An edited state arrives under a new edit_seq -> a distinct row (R-2).
    store.save_author_display_input(
        external_chat_id=_CHAT,
        external_message_id=_MSG,
        edit_seq=1715300100,
        username="alice2",
        first_name="Alice2",
    )
    assert store.get_author_display_input(
        external_chat_id=_CHAT, external_message_id=_MSG, edit_seq=0
    ) == ("alice", "Alice")
    assert store.get_author_display_input(
        external_chat_id=_CHAT, external_message_id=_MSG, edit_seq=1715300100
    ) == ("alice2", "Alice2")


# --------------------------------------------------------------------------- #
# Webhook integration
# --------------------------------------------------------------------------- #
def _settings() -> Settings:
    return Settings(_env_file=None, telegram_webhook_secret="test-secret")  # type: ignore[call-arg]


def _client_with_shared_store() -> tuple[TestClient, MockDomainStore]:
    """Wire one MockDomainStore behind both the dispatcher and the port."""
    store = MockDomainStore()
    embed = MockEmbeddingClient()
    settings = _settings()
    dispatcher = Dispatcher(
        DomainService(store, embedding_client=embed),
        QueryService(store, store, embed, MockChatClient()),
        ExportService(store),
        settings,
    )
    app = create_app(settings)
    app.dependency_overrides[get_dispatcher] = lambda: dispatcher
    app.dependency_overrides[get_author_display_input_store] = lambda: store
    return TestClient(app), store


def _post(client: TestClient, payload: dict[str, Any]) -> Any:
    return client.post(
        "/telegram/webhook",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
    )


def _update(
    text: str,
    *,
    update_id: int = 1,
    message_id: int = 1,
    chat_id: int = 42,
    user_id: int = 7,
    username: str | None = None,
    first_name: str | None = None,
    edit_date: int | None = None,
) -> dict[str, Any]:
    from_: dict[str, Any] = {"id": user_id}
    if username is not None:
        from_["username"] = username
    if first_name is not None:
        from_["first_name"] = first_name
    msg: dict[str, Any] = {
        "message_id": message_id,
        "date": 1715300000 + update_id,
        "chat": {"id": chat_id},
        "from": from_,
        "text": text,
    }
    if edit_date is not None:
        msg["edit_date"] = edit_date
    return {"update_id": update_id, "message": msg}


def test_note_captures_display_input_snapshot() -> None:
    client, store = _client_with_shared_store()
    resp = _post(
        client,
        _update(
            "/note 2026-05-09\nHad a calm morning",
            message_id=1,
            username="alice",
            first_name="Alice",
        ),
    )
    assert resp.status_code == 200
    assert store.get_author_display_input(
        external_chat_id="42", external_message_id="1", edit_seq=0
    ) == ("alice", "Alice")


def test_note_captures_withheld_display_input() -> None:
    client, store = _client_with_shared_store()
    # Neither username nor first_name supplied -> both-null snapshot still lands.
    resp = _post(client, _update("/note 2026-05-09\nQuiet day", message_id=2))
    assert resp.status_code == 200
    assert store.get_author_display_input(
        external_chat_id="42", external_message_id="2", edit_seq=0
    ) == (None, None)


def test_ask_does_not_capture_display_input() -> None:
    client, store = _client_with_shared_store()
    resp = _post(
        client,
        _update("/ask book", message_id=3, username="alice", first_name="Alice"),
    )
    assert resp.status_code == 200
    assert (
        store.get_author_display_input(external_chat_id="42", external_message_id="3", edit_seq=0)
        is None
    )
