"""Dispatcher converts ``NotImplementedError`` from the retrieval seam
into ``FallbackMode.NO_EVIDENCE`` (Slice 3.3 / D-025).

SQLite is opt-in ingest only and has no pgvector / no FTS parity. When
an operator runs SQLite and sends ``/ask``, the search-repo methods
raise ``NotImplementedError``. The dispatcher catches that and returns
a clean ``NO_EVIDENCE`` reply with an explanatory log line, rather than
a 500.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from diary_rag.config import Settings
from diary_rag.core.diary import AnswerResult, FallbackMode
from diary_rag.core.routing import InboundMessage, RouteKind
from diary_rag.services.dispatcher import Dispatcher


class _RaisingQueryService:
    def answer(self, message: InboundMessage) -> AnswerResult:
        raise NotImplementedError("sqlite hybrid retrieval not supported; postgres is canonical")


class _UnusedDiaryService:
    def ingest(self, message: InboundMessage) -> object:  # pragma: no cover - not called
        raise AssertionError("ingest should not be called on an /ask path")


class _UnusedExportService:
    def export(self, **kwargs: object) -> object:  # pragma: no cover - not called
        raise AssertionError("export should not be called on an /ask path")


def _ask(query: str) -> InboundMessage:
    return InboundMessage(
        external_message_id="1",
        external_chat_id="fam-A",
        external_user_id="7",
        text=f"/ask {query}",
        route=RouteKind.ASK,
        received_at=datetime.now(tz=UTC),
        route_source="command",
        payload=query,
    )


def test_not_implemented_error_translates_to_no_evidence(
    caplog: pytest.LogCaptureFixture,
) -> None:
    dispatcher = Dispatcher(
        _UnusedDiaryService(),  # type: ignore[arg-type]
        _RaisingQueryService(),  # type: ignore[arg-type]
        _UnusedExportService(),  # type: ignore[arg-type]
        Settings(_env_file=None),  # type: ignore[call-arg]
    )

    with caplog.at_level(logging.WARNING, logger="diary_rag.services.dispatcher"):
        result = dispatcher.dispatch(_ask("book"))

    assert result.route is RouteKind.ASK
    assert result.reply_text == "No memories matched 'book'."
    assert result.metadata["fallback"] == FallbackMode.NO_EVIDENCE.value
    assert any("retrieval.unavailable" in line for line in caplog.text.splitlines())
