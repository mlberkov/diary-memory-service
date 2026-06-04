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

from memory_rag.config import Settings
from memory_rag.core.domain import AnswerResult, Evidence, FallbackMode
from memory_rag.core.domain.models import AnswerContext, EventChunk
from memory_rag.core.embeddings import EmbeddingStatus
from memory_rag.core.routing import InboundMessage, RouteKind
from memory_rag.services.dispatcher import Dispatcher


class _RaisingQueryService:
    def answer(self, message: InboundMessage) -> AnswerResult:
        raise NotImplementedError("sqlite hybrid retrieval not supported; postgres is canonical")


class _FixedAnswerQueryService:
    """Returns a pre-built ``AnswerResult`` so dispatcher behavior is testable."""

    def __init__(self, result: AnswerResult) -> None:
        self._result = result

    def answer(self, message: InboundMessage) -> AnswerResult:
        return self._result


class _UnusedDomainService:
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
        community_id="fam-A",
        text=f"/ask {query}",
        route=RouteKind.ASK,
        received_at=datetime.now(tz=UTC),
        route_source=route_source,
        payload=query,
    )


def _build_dispatcher(answer: AnswerResult) -> Dispatcher:
    return Dispatcher(
        _UnusedDomainService(),  # type: ignore[arg-type]
        _FixedAnswerQueryService(answer),  # type: ignore[arg-type]
        _UnusedExportService(),  # type: ignore[arg-type]
        Settings(_env_file=None),  # type: ignore[call-arg]
    )


def _evidence(text: str = "Walked the dog") -> list[Evidence]:
    return [Evidence(chunk_id="c1", note_date=date(2026, 5, 9), chunk_text=text)]


def test_not_implemented_error_translates_to_no_evidence(
    caplog: pytest.LogCaptureFixture,
) -> None:
    dispatcher = Dispatcher(
        _UnusedDomainService(),  # type: ignore[arg-type]
        _RaisingQueryService(),  # type: ignore[arg-type]
        _UnusedExportService(),  # type: ignore[arg-type]
        Settings(_env_file=None),  # type: ignore[call-arg]
    )

    with caplog.at_level(logging.WARNING, logger="memory_rag.services.dispatcher"):
        result = dispatcher.dispatch(_ask("book"))

    assert result.route is RouteKind.ASK
    assert result.reply_text == (
        "Nothing in your saved notes matched 'book'. "
        "Try rephrasing the question, or use words that appear in your notes."
    )
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
    # Slice 4.4 (D-036): body is answer_text, not evidence bullets.
    assert "Maybe a book." in result.reply_text
    assert "Walked the dog" not in result.reply_text


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
    assert "Could mean several things." in result.reply_text
    assert "Walked the dog" not in result.reply_text


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

    assert empty.reply_text == (
        "Nothing in your saved notes matched 'book'. "
        "Try rephrasing the question, or use words that appear in your notes."
    )
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


# Heuristic-routed ASK is no longer reachable after D-079 (ASK comes only from
# the explicit /ask command), so the dispatcher no longer appends a routing
# marker on top of the fallback trailers. The test that pinned that combination
# was removed with the marker machinery.


# --- D-091: ASK DispatchResult carries opaque grounding chunks --------------


def _chunk(chunk_id: str = "c1", author_user_id: str = "user-abcdef12") -> EventChunk:
    return EventChunk(
        chunk_id=chunk_id,
        note_id=f"e-{chunk_id}",
        source_message_id=f"s-{chunk_id}",
        community_id="fam-A",
        author_user_id=author_user_id,
        note_date=date(2026, 5, 9),
        event_index=0,
        chunk_text="Walked the dog",
        created_at=datetime.now(tz=UTC),
        embedding_status=EmbeddingStatus.READY,
    )


def _context(chunks: tuple[EventChunk, ...]) -> AnswerContext:
    return AnswerContext(
        query_id="q-1",
        query_text="book",
        ordered_chunks=chunks,
        model_name="mock",
        created_at=datetime.now(tz=UTC),
    )


def test_grounded_ask_threads_grounding_chunks_onto_dispatch_result() -> None:
    # The channel-neutral dispatcher carries the opaque grounding chunks
    # (mirroring source_chunks); it composes no display name (D-091).
    chunks = (_chunk("c1"), _chunk("c2"))
    dispatcher = _build_dispatcher(
        AnswerResult(
            fallback=FallbackMode.NONE,
            query_text="book",
            evidence=_evidence(),
            context=_context(chunks),
            answer_text="A book.",
        )
    )

    result = dispatcher.dispatch(_ask("book"))

    assert result.grounding_chunks == chunks
    # No display name composed in the core reply.
    assert "Contributors:" not in result.reply_text
    assert "@" not in result.reply_text


def test_weak_evidence_ask_still_carries_grounding_chunks() -> None:
    chunks = (_chunk("c1"),)
    dispatcher = _build_dispatcher(
        AnswerResult(
            fallback=FallbackMode.WEAK_EVIDENCE,
            query_text="book",
            evidence=_evidence(),
            context=_context(chunks),
            answer_text="Maybe a book.",
        )
    )

    result = dispatcher.dispatch(_ask("book"))

    assert result.grounding_chunks == chunks


def test_no_evidence_ask_carries_no_grounding_chunks() -> None:
    # Empty-retrieval NO_EVIDENCE has no context → grounding_chunks is None, so
    # the adapter renders no contributor footer (D-091 render condition).
    dispatcher = _build_dispatcher(
        AnswerResult(fallback=FallbackMode.NO_EVIDENCE, query_text="book", evidence=[])
    )

    result = dispatcher.dispatch(_ask("book"))

    assert result.grounding_chunks is None


def test_empty_context_ask_carries_no_grounding_chunks() -> None:
    # A present-but-empty ordered_chunks set is treated as no grounding.
    dispatcher = _build_dispatcher(
        AnswerResult(
            fallback=FallbackMode.NO_EVIDENCE,
            query_text="book",
            evidence=[],
            context=_context(()),
        )
    )

    result = dispatcher.dispatch(_ask("book"))

    assert result.grounding_chunks is None


def test_sibling_fallback_wording_unchanged() -> None:
    """Anti-bleed guard: empty-evidence wording packet must not touch sibling fallback replies.

    Asserts byte-equality of ``PROVIDER_UNAVAILABLE`` and ``PARSE_FAILURE``
    reply literals so any accidental cross-contour wording change is caught
    in this packet's own test diff, not only by the per-mode tests above.
    """
    provider_dispatcher = _build_dispatcher(
        AnswerResult(
            fallback=FallbackMode.PROVIDER_UNAVAILABLE,
            query_text="book",
            evidence=_evidence(),
        )
    )
    parse_dispatcher = _build_dispatcher(
        AnswerResult(
            fallback=FallbackMode.PARSE_FAILURE,
            query_text="book",
            evidence=_evidence(),
        )
    )

    provider = provider_dispatcher.dispatch(_ask("book"))
    parse = parse_dispatcher.dispatch(_ask("book"))

    assert provider.reply_text == (
        "Couldn't generate an answer — chat provider is unavailable. Try again later."
    )
    assert parse.reply_text == (
        "Couldn't generate an answer — provider response was unparseable. Try again."
    )
