"""Dispatcher ``/sources`` cache lifecycle (Slice 4.4, D-036; cited-only since D-100).

The cache holds the chunks the LLM **cited** in the chat's most recent
``/ask`` answer (``AnswerResult.cited_chunk_ids``; D-098) — rendered
as-is by ``/sources``. These tests exercise the lifecycle invariants:

- Every ``/ask`` dispatch writes the cache; no contour skips it, so key
  presence records that an ``/ask`` happened at all.
- A graded answer stores the cited subset of ``context.ordered_chunks``
  (in post-RRF order); ``/sources`` returns exactly those chunks.
- Every cited-empty contour (``cited_chunk_ids == ()`` per D-099) stores
  an empty tuple → ``/sources`` returns the empty-cited reply, kept
  distinct by key presence from the "no prior /ask" reply.
- Only ``/ask`` touches the cache; other routes leave it intact.
- The cache is per-community.
- D-099 guardrail: cited-empty contours never surface free-form
  ``answer_text``.

These tests use a stub ``QueryService`` so the dispatcher's behaviour
is exercised independently of retrieval / chat / repository wiring.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

import pytest

from memory_rag.config import Settings
from memory_rag.core.domain import AnswerResult, Evidence, FallbackMode
from memory_rag.core.domain.models import AnswerContext, EventChunk
from memory_rag.core.embeddings import EmbeddingStatus
from memory_rag.core.routing import InboundMessage, RouteKind
from memory_rag.services.dispatcher import (
    _REPLY_SOURCES_NONE,
    _REPLY_SOURCES_NONE_CITED,
    Dispatcher,
)


def _chunk(chunk_id: str, text: str, *, community_id: str = "fam-A") -> EventChunk:
    return EventChunk(
        chunk_id=chunk_id,
        note_id=f"note-{chunk_id}",
        source_message_id=f"src-{chunk_id}",
        community_id=community_id,
        author_user_id="user-1",
        note_date=date(2026, 5, 9),
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
    cited_chunk_ids: tuple[str, ...] | None = None,
    answer_text: str | None = None,
) -> AnswerResult:
    """Build an ``AnswerResult``.

    ``cited_chunk_ids`` defaults to *every* retrieved chunk id (the
    realistic graded-answer shape: a non-empty I-9 subset). Cited-empty
    contours pass ``cited_chunk_ids=()`` explicitly. ``evidence`` mirrors
    the full retrieved set (``context_chunk_ids``), independent of which
    chunks were cited.
    """
    if cited_chunk_ids is None:
        cited_chunk_ids = tuple(c.chunk_id for c in chunks)
    evidence = [
        Evidence(chunk_id=c.chunk_id, note_date=c.note_date, chunk_text=c.chunk_text)
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
        cited_chunk_ids=cited_chunk_ids,
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


class _UnusedDomainService:
    def ingest(self, message: InboundMessage) -> object:  # pragma: no cover
        raise AssertionError("ingest should not be called on /ask or /sources")


class _UnusedExportService:
    def export(self, **kwargs: object) -> object:  # pragma: no cover
        raise AssertionError("export should not be called on /ask or /sources")


def _dispatcher(answers: list[AnswerResult]) -> Dispatcher:
    return Dispatcher(
        _UnusedDomainService(),  # type: ignore[arg-type]
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
        community_id=chat_id,
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
        community_id=chat_id,
        text="/sources",
        route=RouteKind.SOURCES,
        received_at=datetime.now(tz=UTC),
        route_source="command",
        payload="",
    )


# ---- the two empty contours stay distinct -----------------------------------


def test_sources_without_prior_ask_fails_closed() -> None:
    dispatcher = _dispatcher([])
    result = dispatcher.dispatch(_sources())

    assert result.route is RouteKind.SOURCES
    assert result.reply_text == _REPLY_SOURCES_NONE
    assert result.reply_text == "No selected chunks available — ask a question with /ask first."
    assert result.source_chunks is None
    assert result.metadata["returned"] == "0"


def test_never_asked_and_cited_nothing_replies_are_byte_distinct() -> None:
    # The two empty contours must never be conflated (D-100): "no prior
    # /ask" vs "asked, but cited nothing".
    assert _REPLY_SOURCES_NONE != _REPLY_SOURCES_NONE_CITED
    assert _REPLY_SOURCES_NONE_CITED == "Your last /ask answer didn't cite any specific notes."


# ---- a graded answer caches the cited subset --------------------------------


def test_ask_success_then_sources_returns_cited_chunks() -> None:
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
    # The dispatcher returns the opaque cited chunks (post-RRF order,
    # identity preserved); the adapter renders blocks + resolves the
    # author (D-086).
    assert sources_result.source_chunks == (c1, c2)
    assert sources_result.metadata["returned"] == "2"


def test_sources_returns_only_the_cited_subset_in_post_rrf_order() -> None:
    # Retrieval surfaced three chunks; the LLM cited only two of them.
    # /sources returns exactly the cited subset, in ordered_chunks order;
    # the uncited chunk is absent (D-100 / D-098).
    c1 = _chunk("c-1", "Tried a new book")
    c2 = _chunk("c-2", "Had a calm morning")
    c3 = _chunk("c-3", "Walked the dog")
    dispatcher = _dispatcher(
        [
            _answer(
                fallback=FallbackMode.NONE,
                query_text="book",
                chunks=(c1, c2, c3),
                cited_chunk_ids=("c-3", "c-1"),
                answer_text="Mock grounded answer.",
            )
        ]
    )

    dispatcher.dispatch(_ask("book"))
    sources_result = dispatcher.dispatch(_sources())

    # Order follows ordered_chunks (post-RRF), not cited_chunk_ids order.
    assert sources_result.source_chunks == (c1, c3)
    assert c2 not in (sources_result.source_chunks or ())
    assert sources_result.reply_text == "Selected chunks for your last /ask (2 chunk(s)):"
    assert sources_result.metadata["returned"] == "2"


# ---- next /ask invalidates previous cited chunks ----------------------------


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

    assert sources_result.source_chunks == t2_chunks
    assert sources_result.metadata["returned"] == "1"


def test_graded_then_cited_empty_ask_flips_sources_to_empty_cited_reply() -> None:
    # A grounded /ask caches cited chunks; a follow-up /ask that cites
    # nothing flips /sources from chunks to the empty-cited reply — not
    # the never-asked reply (D-100).
    c1 = _chunk("c-1", "Tried a new book")
    dispatcher = _dispatcher(
        [
            _answer(fallback=FallbackMode.NONE, query_text="book", chunks=(c1,)),
            _answer(
                fallback=FallbackMode.NO_EVIDENCE,
                query_text="snow",
                chunks=(),
                cited_chunk_ids=(),
            ),
        ]
    )

    dispatcher.dispatch(_ask("book"))
    dispatcher.dispatch(_ask("snow"))
    sources_result = dispatcher.dispatch(_sources())

    assert sources_result.reply_text == _REPLY_SOURCES_NONE_CITED
    assert sources_result.source_chunks is None
    assert sources_result.metadata["returned"] == "0"


# ---- every cited-empty contour yields the empty-cited reply -----------------


def test_empty_merged_no_evidence_ask_yields_empty_cited_reply() -> None:
    dispatcher = _dispatcher(
        [
            _answer(
                fallback=FallbackMode.NO_EVIDENCE, query_text="snow", chunks=(), cited_chunk_ids=()
            )
        ]
    )

    dispatcher.dispatch(_ask("snow"))
    sources_result = dispatcher.dispatch(_sources())

    assert sources_result.reply_text == _REPLY_SOURCES_NONE_CITED
    assert sources_result.source_chunks is None


def test_empty_query_no_evidence_ask_yields_empty_cited_reply() -> None:
    dispatcher = _dispatcher(
        [_answer(fallback=FallbackMode.NO_EVIDENCE, query_text="", chunks=(), cited_chunk_ids=())]
    )

    dispatcher.dispatch(_ask(""))
    sources_result = dispatcher.dispatch(_sources())

    assert sources_result.reply_text == _REPLY_SOURCES_NONE_CITED


def test_llm_marker_no_evidence_over_retrieval_yields_empty_cited_reply() -> None:
    # Retrieval surfaced chunks, but the LLM declared them not-evidence:
    # cited_chunk_ids == () even though context is non-empty (D-099).
    c1 = _chunk("c-1", "Tried a new book")
    dispatcher = _dispatcher(
        [
            _answer(
                fallback=FallbackMode.NO_EVIDENCE,
                query_text="book",
                chunks=(c1,),
                cited_chunk_ids=(),
            )
        ]
    )

    dispatcher.dispatch(_ask("book"))
    sources_result = dispatcher.dispatch(_sources())

    assert sources_result.reply_text == _REPLY_SOURCES_NONE_CITED
    assert sources_result.source_chunks is None


def test_provider_unavailable_ask_yields_empty_cited_reply() -> None:
    # PROVIDER_UNAVAILABLE retrieval surfaced chunks but cited nothing
    # (cited_chunk_ids == ()), so /sources is cited-empty (D-100).
    c1 = _chunk("c-1", "Tried a new book")
    dispatcher = _dispatcher(
        [
            _answer(
                fallback=FallbackMode.PROVIDER_UNAVAILABLE,
                query_text="dog",
                chunks=(c1,),
                cited_chunk_ids=(),
            )
        ]
    )

    dispatcher.dispatch(_ask("dog"))
    sources_result = dispatcher.dispatch(_sources())

    assert sources_result.reply_text == _REPLY_SOURCES_NONE_CITED
    assert sources_result.source_chunks is None


def test_parse_failure_ask_yields_empty_cited_reply() -> None:
    c1 = _chunk("c-1", "Tried a new book")
    dispatcher = _dispatcher(
        [
            _answer(
                fallback=FallbackMode.PARSE_FAILURE,
                query_text="dog",
                chunks=(c1,),
                cited_chunk_ids=(),
            )
        ]
    )

    dispatcher.dispatch(_ask("dog"))
    sources_result = dispatcher.dispatch(_sources())

    assert sources_result.reply_text == _REPLY_SOURCES_NONE_CITED
    assert sources_result.source_chunks is None


# ---- D-099 guardrail: cited-empty contours never leak free-form answer_text -


_LEAK_SENTINEL = "SENTINEL_MODEL_PROSE_DO_NOT_LEAK"


def _cited_empty_contour_answers() -> list[tuple[str, AnswerResult]]:
    c1 = _chunk("c-1", "Tried a new book")
    return [
        (
            "empty_query_no_evidence",
            _answer(
                fallback=FallbackMode.NO_EVIDENCE,
                query_text="",
                chunks=(),
                cited_chunk_ids=(),
                answer_text=_LEAK_SENTINEL,
            ),
        ),
        (
            "empty_merged_no_evidence",
            _answer(
                fallback=FallbackMode.NO_EVIDENCE,
                query_text="snow",
                chunks=(),
                cited_chunk_ids=(),
                answer_text=_LEAK_SENTINEL,
            ),
        ),
        (
            "llm_marker_no_evidence",
            _answer(
                fallback=FallbackMode.NO_EVIDENCE,
                query_text="book",
                chunks=(c1,),
                cited_chunk_ids=(),
                answer_text=_LEAK_SENTINEL,
            ),
        ),
        (
            "provider_unavailable",
            _answer(
                fallback=FallbackMode.PROVIDER_UNAVAILABLE,
                query_text="book",
                chunks=(c1,),
                cited_chunk_ids=(),
                answer_text=_LEAK_SENTINEL,
            ),
        ),
        (
            "parse_failure",
            _answer(
                fallback=FallbackMode.PARSE_FAILURE,
                query_text="book",
                chunks=(c1,),
                cited_chunk_ids=(),
                answer_text=_LEAK_SENTINEL,
            ),
        ),
    ]


@pytest.mark.parametrize(
    "answer",
    [a for _, a in _cited_empty_contour_answers()],
    ids=[label for label, _ in _cited_empty_contour_answers()],
)
def test_cited_empty_contours_do_not_surface_free_form_answer_text(answer: AnswerResult) -> None:
    # D-099 ratified property: when cited_chunk_ids is empty, the /ask
    # reply is an explicit technical no-evidence/failure reply and MUST
    # NOT surface the model's free-form answer_text. We pin the property
    # (sentinel absent), not the exact reply bodies — those are pinned by
    # the D-071 sibling guards in tests/test_dispatcher_retrieval_fallback.py.
    assert answer.cited_chunk_ids == ()
    dispatcher = _dispatcher([answer])

    ask_result = dispatcher.dispatch(_ask(answer.query_text or "x"))

    assert _LEAK_SENTINEL not in ask_result.reply_text


# ---- two-family isolation ---------------------------------------------------


def test_two_family_caches_are_independent() -> None:
    a_chunks = (_chunk("a-1", "Family A note"),)
    b_chunks = (_chunk("b-1", "Family B note", community_id="fam-B"),)
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

    assert a_sources.source_chunks == a_chunks
    assert b_sources.source_chunks == b_chunks


# ---- /sources is read-only --------------------------------------------------


def test_repeated_sources_does_not_clear_cache() -> None:
    c1 = _chunk("c-1", "Tried a new book")
    dispatcher = _dispatcher([_answer(fallback=FallbackMode.NONE, query_text="book", chunks=(c1,))])

    dispatcher.dispatch(_ask("book"))
    first = dispatcher.dispatch(_sources())
    second = dispatcher.dispatch(_sources())

    assert first.source_chunks == second.source_chunks
    assert second.source_chunks == (c1,)
