"""Dispatcher answer-side fallback surfacing.

Two layers are exercised:

- Slice 3.3 / D-025: ``NotImplementedError`` from the retrieval seam
  (sqlite has no hybrid retrieval) is translated to
  ``FallbackMode.NO_EVIDENCE`` with a clean reply and a
  ``retrieval.unavailable`` warning log line.
- Slice 4.3b / D-035: each new answer-side ``FallbackMode`` produces a
  distinct reply text (R-6 requested-vs-effective signaling). The
  ``NO_EVIDENCE`` enum value has two surface forms: empty retrieval and
  LLM-marker (retrieval returned chunks but the model judged them
  not-evidence). The Dispatcher disambiguates on
  ``bool(result.evidence)``.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Literal

import pytest

from diary_rag.config import Settings
from diary_rag.core.diary import AnswerResult, Evidence, FallbackMode
from diary_rag.core.routing import InboundMessage, RouteKind
from diary_rag.services.dispatcher import Dispatcher


class _RaisingQueryService:
    def answer(self, message: InboundMessage) -> AnswerResult:
        raise NotImplementedError("sqlite hybrid retrieval not supported; postgres is canonical")


class _FixedAnswerQueryService:
    """Returns a pre-built ``AnswerResult`` so dispatcher behavior is testable."""

    def __init__(self, result: AnswerResult) -> None:
        self._result = result

    def answer(self, message: InboundMessage) -> AnswerResult:
        return self._result


class _UnusedDiaryService:
    def ingest(self, message: InboundMessage) -> object:  # pragma: no cover - not called
        raise AssertionError("ingest should not be called on an /ask path")


class _UnusedExportService:
    def export(self, **kwargs: object) -> object:  # pragma: no cover - not called
        raise AssertionError("export should not be called on an /ask path")


def _ask(
    query: str,
    *,
    route_source: Literal["command", "heuristic"] = "command",
) -> InboundMessage:
    return InboundMessage(
        external_message_id="1",
        external_chat_id="fam-A",
        external_user_id="7",
        text=f"/ask {query}",
        route=RouteKind.ASK,
        received_at=datetime.now(tz=UTC),
        route_source=route_source,
        payload=query,
    )


def _build_dispatcher(answer: AnswerResult) -> Dispatcher:
    return Dispatcher(
        _UnusedDiaryService(),  # type: ignore[arg-type]
        _FixedAnswerQueryService(answer),  # type: ignore[arg-type]
        _UnusedExportService(),  # type: ignore[arg-type]
        Settings(_env_file=None),  # type: ignore[call-arg]
    )


def _evidence(text: str = "Walked the dog") -> list[Evidence]:
    return [Evidence(chunk_id="c1", entry_date=date(2026, 5, 9), chunk_text=text)]


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


# --- Slice 4.3b answer-side fallback surfacing ------------------------------


def test_weak_evidence_appends_marker_trailer() -> None:
    dispatcher = _build_dispatcher(
        AnswerResult(
            fallback=FallbackMode.WEAK_EVIDENCE,
            query_text="book",
            evidence=_evidence(),
            answer_text="Maybe a book.",
        )
    )

    result = dispatcher.dispatch(_ask("book"))

    assert result.metadata["fallback"] == FallbackMode.WEAK_EVIDENCE.value
    assert "(weak evidence — model expressed uncertainty)" in result.reply_text
    assert "[2026-05-09] Walked the dog" in result.reply_text


def test_ambiguous_appends_marker_trailer() -> None:
    dispatcher = _build_dispatcher(
        AnswerResult(
            fallback=FallbackMode.AMBIGUOUS,
            query_text="walks?",
            evidence=_evidence(),
            answer_text="Could mean several things.",
        )
    )

    result = dispatcher.dispatch(_ask("walks?"))

    assert result.metadata["fallback"] == FallbackMode.AMBIGUOUS.value
    assert "(ambiguous question — refine and ask again)" in result.reply_text
    assert "[2026-05-09] Walked the dog" in result.reply_text


def test_llm_marker_no_evidence_distinct_from_empty_retrieval() -> None:
    """Two NO_EVIDENCE sub-branches must produce different reply text (D-035)."""
    empty_dispatcher = _build_dispatcher(
        AnswerResult(fallback=FallbackMode.NO_EVIDENCE, query_text="book", evidence=[])
    )
    llm_dispatcher = _build_dispatcher(
        AnswerResult(
            fallback=FallbackMode.NO_EVIDENCE,
            query_text="book",
            evidence=_evidence(),
            answer_text="No usable evidence.",
        )
    )

    empty = empty_dispatcher.dispatch(_ask("book"))
    llm = llm_dispatcher.dispatch(_ask("book"))

    assert empty.reply_text == "No memories matched 'book'."
    assert llm.reply_text == (
        "Found possible matches but couldn't ground an answer for 'book'. "
        "Try refining the question."
    )
    assert empty.reply_text != llm.reply_text


def test_provider_unavailable_replies_with_retry_hint() -> None:
    dispatcher = _build_dispatcher(
        AnswerResult(
            fallback=FallbackMode.PROVIDER_UNAVAILABLE,
            query_text="book",
            evidence=_evidence(),
        )
    )

    result = dispatcher.dispatch(_ask("book"))

    assert result.metadata["fallback"] == FallbackMode.PROVIDER_UNAVAILABLE.value
    assert result.reply_text == (
        "Couldn't generate an answer — chat provider is unavailable. Try again later."
    )
    # Provider-unavailable does NOT render the evidence list.
    assert "Walked the dog" not in result.reply_text


def test_parse_failure_replies_with_retry_hint() -> None:
    dispatcher = _build_dispatcher(
        AnswerResult(
            fallback=FallbackMode.PARSE_FAILURE,
            query_text="book",
            evidence=_evidence(),
        )
    )

    result = dispatcher.dispatch(_ask("book"))

    assert result.metadata["fallback"] == FallbackMode.PARSE_FAILURE.value
    assert result.reply_text == (
        "Couldn't generate an answer — provider response was unparseable. Try again."
    )
    assert "Walked the dog" not in result.reply_text


def test_weak_evidence_heuristic_still_appends_route_marker() -> None:
    """Heuristic-routed marker is still appended on top of the new fallback trailers."""
    dispatcher = _build_dispatcher(
        AnswerResult(
            fallback=FallbackMode.WEAK_EVIDENCE,
            query_text="book",
            evidence=_evidence(),
        )
    )

    result = dispatcher.dispatch(_ask("book", route_source="heuristic"))

    assert "(weak evidence — model expressed uncertainty)" in result.reply_text
    assert "(routed as question — send /ask next time to be explicit)" in result.reply_text
