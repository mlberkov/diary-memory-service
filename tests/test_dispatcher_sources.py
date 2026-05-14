"""Dispatcher ``/sources`` cache lifecycle (Slice 4.4, D-036).

The cache holds the chunks retrieval selected for the chat's most
recent ``/ask`` turn — rendered as-is by ``/sources``. These tests
exercise the lifecycle invariants the owner committed to in D-036:

- Every ``/ask`` dispatch updates the cache; no contour skips it.
- Non-empty ``answer.context.ordered_chunks`` → overwrite.
- Empty (empty-query, empty-retrieval, retrieval-unavailable) → clear.
- Only ``/ask`` touches the cache; other routes leave it intact.
- The cache is per-family.

These tests use a stub ``QueryService`` so the dispatcher's behaviour
is exercised independently of retrieval / chat / repository wiring.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from diary_rag.config import Settings
from diary_rag.core.diary import AnswerResult, Evidence, FallbackMode
from diary_rag.core.diary.models import AnswerContext, EventChunk
from diary_rag.core.embeddings import EmbeddingStatus
from diary_rag.core.routing import InboundMessage, RouteKind
from diary_rag.services.dispatcher import Dispatcher


def _chunk(chunk_id: str, text: str, *, family_id: str = "fam-A") -> EventChunk:
    return EventChunk(
        chunk_id=chunk_id,
        diary_entry_id=f"entry-{chunk_id}",
        source_message_id=f"src-{chunk_id}",
        family_id=family_id,
        author_user_id="user-1",
        entry_date=date(2026, 5, 9),
        event_index=0,
        chunk_text=text,
        created_at=datetime.now(tz=UTC),
        embedding_status=EmbeddingStatus.READY,
    )


def _context(query_text: str, chunks: tuple[EventChunk, ...]) -> AnswerContext:
    return AnswerContext(
        query_id="q-1",
        query_text=query_text,
        ordered_chunks=chunks,
        model_name="mock",
        created_at=datetime.now(tz=UTC),
    )


def _answer(
    *,
    fallback: FallbackMode,
    query_text: str,
    chunks: tuple[EventChunk, ...] = (),
    answer_text: str | None = None,
) -> AnswerResult:
    evidence = [
        Evidence(chunk_id=c.chunk_id, entry_date=c.entry_date, chunk_text=c.chunk_text)
        for c in chunks
    ]
    context: AnswerContext | None
    if chunks or fallback is FallbackMode.NO_EVIDENCE:
        context = _context(query_text, chunks)
    else:
        context = None
    return AnswerResult(
        fallback=fallback,
        query_text=query_text,
        evidence=evidence,
        context=context,
        answer_text=answer_text,
    )


class _ScriptedQueryService:
    """Returns pre-built answers in order; raises if exhausted."""

    def __init__(self, answers: list[AnswerResult]) -> None:
        self._answers = list(answers)

    def answer(self, message: InboundMessage) -> AnswerResult:
        if not self._answers:
            raise AssertionError("scripted query service exhausted")
        return self._answers.pop(0)


class _UnusedDiaryService:
    def ingest(self, message: InboundMessage) -> object:  # pragma: no cover
        raise AssertionError("ingest should not be called on /ask or /sources")


class _UnusedExportService:
    def export(self, **kwargs: object) -> object:  # pragma: no cover
        raise AssertionError("export should not be called on /ask or /sources")


def _dispatcher(answers: list[AnswerResult]) -> Dispatcher:
    return Dispatcher(
        _UnusedDiaryService(),  # type: ignore[arg-type]
        _ScriptedQueryService(answers),  # type: ignore[arg-type]
        _UnusedExportService(),  # type: ignore[arg-type]
        Settings(_env_file=None),  # type: ignore[call-arg]
    )


def _ask(
    query: str,
    *,
    chat_id: str = "fam-A",
    route_source: Literal["command", "heuristic"] = "command",
) -> InboundMessage:
    return InboundMessage(
        external_message_id="m",
        external_chat_id=chat_id,
        external_user_id="7",
        text=f"/ask {query}",
        route=RouteKind.ASK,
        received_at=datetime.now(tz=UTC),
        route_source=route_source,
        payload=query,
    )


def _sources(*, chat_id: str = "fam-A") -> InboundMessage:
    return InboundMessage(
        external_message_id="m",
        external_chat_id=chat_id,
        external_user_id="7",
        text="/sources",
        route=RouteKind.SOURCES,
        received_at=datetime.now(tz=UTC),
        route_source="command",
        payload="",
    )


# ---- fail-closed contour ----------------------------------------------------


def test_sources_without_prior_ask_fails_closed() -> None:
    dispatcher = _dispatcher([])
    result = dispatcher.dispatch(_sources())

    assert result.route is RouteKind.SOURCES
    assert result.reply_text == "No selected chunks available — ask a question with /ask first."
    assert result.source_blocks is None
    assert result.metadata["returned"] == "0"


# ---- successful answer-producing turn populates cache -----------------------


def test_ask_success_then_sources_returns_selected_chunks() -> None:
    c1 = _chunk("c-1", "Tried a new book")
    c2 = _chunk("c-2", "Had a calm morning")
    dispatcher = _dispatcher(
        [
            _answer(
                fallback=FallbackMode.NONE,
                query_text="book",
                chunks=(c1, c2),
                answer_text="Mock grounded answer.",
            )
        ]
    )

    ask_result = dispatcher.dispatch(_ask("book"))
    sources_result = dispatcher.dispatch(_sources())

    assert ask_result.route is RouteKind.ASK
    assert sources_result.route is RouteKind.SOURCES
    assert sources_result.reply_text == "Selected chunks for your last /ask (2 chunk(s)):"
    assert sources_result.source_blocks is not None
    assert sources_result.source_blocks == [
        "[2026-05-09] c-1\n\nTried a new book",
        "[2026-05-09] c-2\n\nHad a calm morning",
    ]
    assert sources_result.metadata["returned"] == "2"


# ---- next /ask invalidates previous selected chunks -------------------------


def test_two_successful_asks_sources_returns_only_latest() -> None:
    t1_chunks = (_chunk("c-1", "Tried a new book"),)
    t2_chunks = (_chunk("c-2", "Walked the dog"),)
    dispatcher = _dispatcher(
        [
            _answer(fallback=FallbackMode.NONE, query_text="book", chunks=t1_chunks),
            _answer(fallback=FallbackMode.NONE, query_text="dog", chunks=t2_chunks),
        ]
    )

    dispatcher.dispatch(_ask("book"))
    dispatcher.dispatch(_ask("dog"))
    sources_result = dispatcher.dispatch(_sources())

    assert sources_result.source_blocks == ["[2026-05-09] c-2\n\nWalked the dog"]
    assert sources_result.metadata["returned"] == "1"


# ---- empty-retrieval /ask clears the cache (R-6) ----------------------------


def test_empty_retrieval_ask_clears_prior_cache() -> None:
    c1 = _chunk("c-1", "Tried a new book")
    dispatcher = _dispatcher(
        [
            _answer(fallback=FallbackMode.NONE, query_text="book", chunks=(c1,)),
            _answer(fallback=FallbackMode.NO_EVIDENCE, query_text="snow", chunks=()),
        ]
    )

    dispatcher.dispatch(_ask("book"))
    dispatcher.dispatch(_ask("snow"))
    sources_result = dispatcher.dispatch(_sources())

    expected = "No selected chunks available — ask a question with /ask first."
    assert sources_result.reply_text == expected
    assert sources_result.source_blocks is None


# ---- empty-query /ask clears the cache --------------------------------------


def test_empty_query_ask_clears_prior_cache() -> None:
    c1 = _chunk("c-1", "Tried a new book")
    dispatcher = _dispatcher(
        [
            _answer(fallback=FallbackMode.NONE, query_text="book", chunks=(c1,)),
            _answer(fallback=FallbackMode.NO_EVIDENCE, query_text="", chunks=()),
        ]
    )

    dispatcher.dispatch(_ask("book"))
    dispatcher.dispatch(_ask(""))
    sources_result = dispatcher.dispatch(_sources())

    expected = "No selected chunks available — ask a question with /ask first."
    assert sources_result.reply_text == expected


# ---- provider_unavailable still updates the cache (D-036 lifecycle) ---------


def test_provider_unavailable_ask_overwrites_cache_with_retrieved_chunks() -> None:
    t1_chunks = (_chunk("c-1", "Tried a new book"),)
    t2_chunks = (_chunk("c-2", "Walked the dog"),)
    dispatcher = _dispatcher(
        [
            _answer(fallback=FallbackMode.NONE, query_text="book", chunks=t1_chunks),
            _answer(
                fallback=FallbackMode.PROVIDER_UNAVAILABLE,
                query_text="dog",
                chunks=t2_chunks,
            ),
        ]
    )

    dispatcher.dispatch(_ask("book"))
    dispatcher.dispatch(_ask("dog"))
    sources_result = dispatcher.dispatch(_sources())

    # PROVIDER_UNAVAILABLE retrieval still surfaced chunks, so /sources
    # returns the second turn's chunks (cache lifecycle: update on every /ask).
    assert sources_result.source_blocks == ["[2026-05-09] c-2\n\nWalked the dog"]


def test_parse_failure_ask_overwrites_cache_with_retrieved_chunks() -> None:
    t1_chunks = (_chunk("c-1", "Tried a new book"),)
    t2_chunks = (_chunk("c-2", "Walked the dog"),)
    dispatcher = _dispatcher(
        [
            _answer(fallback=FallbackMode.NONE, query_text="book", chunks=t1_chunks),
            _answer(
                fallback=FallbackMode.PARSE_FAILURE,
                query_text="dog",
                chunks=t2_chunks,
            ),
        ]
    )

    dispatcher.dispatch(_ask("book"))
    dispatcher.dispatch(_ask("dog"))
    sources_result = dispatcher.dispatch(_sources())

    assert sources_result.source_blocks == ["[2026-05-09] c-2\n\nWalked the dog"]


# ---- two-family isolation ---------------------------------------------------


def test_two_family_caches_are_independent() -> None:
    a_chunks = (_chunk("a-1", "Family A note"),)
    b_chunks = (_chunk("b-1", "Family B note", family_id="fam-B"),)
    dispatcher = _dispatcher(
        [
            _answer(fallback=FallbackMode.NONE, query_text="A?", chunks=a_chunks),
            _answer(fallback=FallbackMode.NONE, query_text="B?", chunks=b_chunks),
        ]
    )

    dispatcher.dispatch(_ask("A?", chat_id="fam-A"))
    dispatcher.dispatch(_ask("B?", chat_id="fam-B"))

    a_sources = dispatcher.dispatch(_sources(chat_id="fam-A"))
    b_sources = dispatcher.dispatch(_sources(chat_id="fam-B"))

    assert a_sources.source_blocks == ["[2026-05-09] a-1\n\nFamily A note"]
    assert b_sources.source_blocks == ["[2026-05-09] b-1\n\nFamily B note"]


# ---- /sources is read-only --------------------------------------------------


def test_repeated_sources_does_not_clear_cache() -> None:
    c1 = _chunk("c-1", "Tried a new book")
    dispatcher = _dispatcher([_answer(fallback=FallbackMode.NONE, query_text="book", chunks=(c1,))])

    dispatcher.dispatch(_ask("book"))
    first = dispatcher.dispatch(_sources())
    second = dispatcher.dispatch(_sources())

    assert first.source_blocks == second.source_blocks
    assert second.source_blocks == ["[2026-05-09] c-1\n\nTried a new book"]
