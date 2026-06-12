"""QueryService tests for the baseline hybrid path (D-025).

Mock backend exercises both retrieval legs: sparse matches via token
overlap, dense matches via deterministic cosine over the mock embeddings
(only identical text qualifies — see ``MockDomainStore`` for why). RRF
fuses the two ranked lists in the service layer.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from memory_rag.adapters.answers import MockChatClient
from memory_rag.adapters.embeddings import MockEmbeddingClient
from memory_rag.core.answers import ChatProviderUnavailableError, ChatResponse
from memory_rag.core.domain import DateRange, FallbackMode, RetrievalLeg
from memory_rag.core.domain.answer_prompt import AnswerPrompt
from memory_rag.core.routing import InboundMessage, RouteKind
from memory_rag.services import DomainService, QueryService
from memory_rag.storage.mock import MockDomainStore


def _ask(query: str, *, chat: str = "42", user: str = "7") -> InboundMessage:
    return InboundMessage(
        external_message_id="200",
        external_chat_id=chat,
        external_user_id=user,
        community_id=chat,
        text=f"/ask {query}",
        route=RouteKind.ASK,
        received_at=datetime.now(tz=UTC),
        route_source="command",
        payload=query,
    )


def _note(
    payload: str,
    *,
    chat: str = "42",
    user: str = "7",
    msg_id: str = "100",
    subject_id: str | None = None,
) -> InboundMessage:
    return InboundMessage(
        external_message_id=msg_id,
        external_chat_id=chat,
        external_user_id=user,
        community_id=chat,
        text=f"/note {payload}",
        route=RouteKind.NOTE,
        received_at=datetime.now(tz=UTC),
        route_source="command",
        payload=payload,
        subject_id=subject_id,
    )


def _wire(store: MockDomainStore, *, top_k: int = 5) -> QueryService:
    return QueryService(store, store, MockEmbeddingClient(), MockChatClient(), top_k=top_k)


def _ingest(
    store: MockDomainStore,
    payload: str,
    *,
    chat: str = "42",
    msg_id: str = "100",
    subject_id: str | None = None,
) -> None:
    DomainService(store, embedding_client=MockEmbeddingClient()).ingest(
        _note(payload, chat=chat, msg_id=msg_id, subject_id=subject_id)
    )


def test_empty_store_returns_no_evidence() -> None:
    store = MockDomainStore()
    query = _wire(store)

    result = query.answer(_ask("anything"))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert result.evidence == []
    assert result.context_chunk_ids == []


def test_sparse_leg_recovers_keyword_match() -> None:
    # One /note is one chunk (I-5 / D-106), so distinct chunks come from
    # distinct notes — each line is its own /note here.
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nMorning routine", msg_id="100")
    _ingest(store, "2026-05-09\nTried a new book", msg_id="101")
    _ingest(store, "2026-05-09\nAnother book chapter", msg_id="102")
    query = _wire(store)

    result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.NONE
    matched = {e.chunk_text for e in result.evidence}
    assert "Tried a new book" in matched
    assert "Another book chapter" in matched
    assert "Morning routine" not in matched


def test_dense_leg_returns_identical_text_match() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nWalked the dog")
    query = _wire(store)

    result = query.answer(_ask("Walked the dog"))

    assert result.fallback is FallbackMode.NONE
    assert [e.chunk_text for e in result.evidence] == ["Walked the dog"]


def test_unrelated_query_returns_no_evidence() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nMorning routine")
    query = _wire(store)

    result = query.answer(_ask("snowstorm"))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert result.evidence == []


def test_cross_chat_isolation() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nFamily A book", chat="42")
    _ingest(store, "2026-05-09\nFamily B novel", chat="99")
    query = _wire(store)

    result_a = query.answer(_ask("book", chat="42"))
    result_b = query.answer(_ask("book", chat="99"))

    assert [e.chunk_text for e in result_a.evidence] == ["Family A book"]
    assert result_b.evidence == []


def test_top_k_caps_evidence_count() -> None:
    # One /note is one chunk (I-5 / D-106): four chunks need four notes.
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nbook one", msg_id="100")
    _ingest(store, "2026-05-09\nbook two", msg_id="101")
    _ingest(store, "2026-05-09\nbook three", msg_id="102")
    _ingest(store, "2026-05-09\nbook four", msg_id="103")
    query = _wire(store, top_k=2)

    result = query.answer(_ask("book"))

    assert len(result.evidence) == 2


def test_missing_community_id_raises() -> None:
    store = MockDomainStore()
    query = _wire(store)

    with pytest.raises(ValueError, match="community_id"):
        query.answer(
            InboundMessage(
                external_message_id="200",
                external_chat_id="42",
                external_user_id="7",
                community_id="",
                text="/ask book",
                route=RouteKind.ASK,
                received_at=datetime.now(tz=UTC),
                route_source="command",
                payload="book",
            )
        )
    assert store.len_queries() == 0  # R-3 rejection happens before persistence


def test_blank_query_returns_no_evidence() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nMorning routine")
    query = _wire(store)

    result = query.answer(_ask("   "))

    assert result.fallback is FallbackMode.NO_EVIDENCE


def test_terminal_punctuation_does_not_block_match() -> None:
    """``recipe?`` normalizes to ``recipe`` before sparse tokenization."""
    store = MockDomainStore()
    _ingest(store, "2026-05-10\nLearned a new recipe")
    query = _wire(store)

    result = query.answer(_ask("recipe?"))

    assert result.fallback is FallbackMode.NONE
    assert [e.chunk_text for e in result.evidence] == ["Learned a new recipe"]


def test_successful_retrieval_persists_query_and_hits() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nMorning routine\nTried a new book")
    query = _wire(store)

    result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.NONE
    assert store.len_queries() == 1
    # Persisted Query mirrors the AnswerResult.
    persisted = next(iter(store._queries.values()))
    assert persisted.community_id == "42"
    assert persisted.query_text == "book"
    assert persisted.fallback is FallbackMode.NONE
    assert persisted.model_name == MockEmbeddingClient().model_name

    hits = store.get_retrieval_hits_for_query(
        persisted.query_id, community_id=persisted.community_id
    )
    legs = {h.leg for h in hits}
    assert RetrievalLeg.SPARSE in legs  # sparse matched "book"
    assert RetrievalLeg.MERGED in legs  # merged carries the surviving evidence
    merged_chunk_ids = [h.chunk_id for h in hits if h.leg is RetrievalLeg.MERGED]
    assert merged_chunk_ids == [e.chunk_id for e in result.evidence]
    # All ranks are 1-based and unique per leg.
    for leg in legs:
        leg_ranks = sorted(h.rank for h in hits if h.leg is leg)
        assert leg_ranks == list(range(1, len(leg_ranks) + 1))


def test_no_evidence_persists_query_with_zero_hits() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nMorning routine")
    query = _wire(store)

    result = query.answer(_ask("snowstorm"))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert store.len_queries() == 1
    persisted = next(iter(store._queries.values()))
    assert persisted.fallback is FallbackMode.NO_EVIDENCE
    assert persisted.query_text == "snowstorm"
    assert (
        store.get_retrieval_hits_for_query(persisted.query_id, community_id=persisted.community_id)
        == []
    )
    assert store.len_retrieval_hits() == 0


def test_empty_query_persists_query_with_zero_hits() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nMorning routine")
    query = _wire(store)

    result = query.answer(_ask("   "))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert store.len_queries() == 1
    persisted = next(iter(store._queries.values()))
    assert persisted.query_text == ""
    assert persisted.fallback is FallbackMode.NO_EVIDENCE
    assert store.len_retrieval_hits() == 0


def test_successful_retrieval_attaches_answer_context() -> None:
    """Slice 4.1: every successful retrieval carries an assembled context."""
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nMorning routine\nTried a new book")
    query = _wire(store)

    result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.NONE
    assert result.context is not None
    persisted = next(iter(store._queries.values()))
    assert result.context.query_id == persisted.query_id
    assert result.context.query_text == "book"
    assert result.context.model_name == MockEmbeddingClient().model_name
    assert result.context.created_at == persisted.created_at
    # Context chunk order matches the evidence (RRF rank).
    assert [c.chunk_id for c in result.context.ordered_chunks] == [
        e.chunk_id for e in result.evidence
    ]


def test_no_evidence_attaches_empty_answer_context() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nMorning routine")
    query = _wire(store)

    result = query.answer(_ask("snowstorm"))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert result.context is not None
    assert result.context.query_text == "snowstorm"
    assert result.context.ordered_chunks == ()


def test_empty_query_attaches_empty_answer_context() -> None:
    store = MockDomainStore()
    query = _wire(store)

    result = query.answer(_ask("   "))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert result.context is not None
    assert result.context.query_text == ""
    assert result.context.ordered_chunks == ()


def test_invalid_constructor_arguments() -> None:
    store = MockDomainStore()
    client = MockEmbeddingClient()
    chat = MockChatClient()

    with pytest.raises(ValueError, match="top_k"):
        QueryService(store, store, client, chat, top_k=0)
    with pytest.raises(ValueError, match="candidate_k"):
        QueryService(store, store, client, chat, top_k=5, candidate_k=2)


def test_successful_answer_persists_answer_trace_with_chat_output() -> None:
    """Slice 4.3a: success persists an ``AnswerTrace`` with the LLM output."""
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nMorning routine\nTried a new book")
    query = _wire(store)

    result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.NONE
    assert store.len_answer_traces() == 1
    persisted_query = next(iter(store._queries.values()))
    trace = store.get_answer_trace_for_query(
        persisted_query.query_id, community_id=persisted_query.community_id
    )
    assert trace is not None
    assert trace.fallback_mode is FallbackMode.NONE
    assert trace.prompt_version == "v1"
    assert trace.model_name == "mock"
    assert trace.latency_ms == 0
    assert trace.token_counts.keys() == {"prompt", "completion"}
    assert tuple(trace.context_chunk_ids) == tuple(
        c.chunk_id
        for c in result.context.ordered_chunks  # type: ignore[union-attr]
    )
    assert trace.answer_text  # non-empty mock answer
    # AnswerResult carries the LLM-produced text alongside the existing evidence.
    assert result.answer_text == trace.answer_text


def test_no_evidence_persists_answer_trace_with_empty_context() -> None:
    """Slice 4.3a: no-evidence persists a trace with no chat call."""
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nMorning routine")
    query = _wire(store)

    result = query.answer(_ask("snowstorm"))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert result.answer_text is None
    assert store.len_answer_traces() == 1
    persisted_query = next(iter(store._queries.values()))
    trace = store.get_answer_trace_for_query(
        persisted_query.query_id, community_id=persisted_query.community_id
    )
    assert trace is not None
    assert trace.fallback_mode is FallbackMode.NO_EVIDENCE
    assert trace.context_chunk_ids == ()
    assert trace.answer_text == ""
    assert trace.token_counts == {}
    assert trace.latency_ms == 0
    assert trace.model_name == "mock"


def test_empty_query_persists_answer_trace_with_empty_context() -> None:
    """Slice 4.3a: empty-query persists a trace with no chat call."""
    store = MockDomainStore()
    query = _wire(store)

    result = query.answer(_ask("   "))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert result.answer_text is None
    assert store.len_answer_traces() == 1
    persisted_query = next(iter(store._queries.values()))
    trace = store.get_answer_trace_for_query(
        persisted_query.query_id, community_id=persisted_query.community_id
    )
    assert trace is not None
    assert trace.fallback_mode is FallbackMode.NO_EVIDENCE
    assert trace.context_chunk_ids == ()
    assert trace.answer_text == ""
    assert trace.token_counts == {}
    assert trace.latency_ms == 0


# --- Slice 3.4: date-range retrieval filter (D-040) --------------------------


def test_answer_honors_date_range() -> None:
    """A per-call ``date_range`` narrows both legs to in-range chunks."""
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nRead a book in May", msg_id="100")
    _ingest(store, "2026-06-15\nRead a book in June", msg_id="101")
    query = _wire(store)

    result = query.answer(_ask("book"), date_range=DateRange(start=date(2026, 6, 1)))

    assert result.fallback is FallbackMode.NONE
    assert [e.chunk_text for e in result.evidence] == ["Read a book in June"]


def test_answer_without_date_range_is_unchanged() -> None:
    """Omitting ``date_range`` retrieves across all dates (pre-3.4 shape)."""
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nRead a book in May", msg_id="100")
    _ingest(store, "2026-06-15\nRead a book in June", msg_id="101")
    query = _wire(store)

    result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.NONE
    assert {e.chunk_text for e in result.evidence} == {
        "Read a book in May",
        "Read a book in June",
    }


# --- H-3: optional subject retrieval filter (D-107) ---------------------------


def test_answer_honors_subject_scope() -> None:
    """A per-call ``subject_scope`` narrows both legs to same-subject chunks
    (strict match — community-wide chunks excluded) and is recorded on the
    persisted ``Query`` row."""
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nRead a book about subject one", msg_id="100", subject_id="subj-1")
    _ingest(store, "2026-05-09\nRead a book about subject two", msg_id="101", subject_id="subj-2")
    _ingest(store, "2026-05-09\nRead a book community wide", msg_id="102", subject_id=None)
    query = _wire(store)

    result = query.answer(_ask("book"), subject_scope="subj-1")

    assert result.fallback is FallbackMode.NONE
    assert [e.chunk_text for e in result.evidence] == ["Read a book about subject one"]
    persisted = next(iter(store._queries.values()))
    assert persisted.subject_scope == "subj-1"


def test_answer_without_subject_scope_is_unchanged() -> None:
    """Omitting ``subject_scope`` retrieves across all subjects (the current
    no-filter shape) and persists ``subject_scope=None``."""
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nRead a book about subject one", msg_id="100", subject_id="subj-1")
    _ingest(store, "2026-05-09\nRead a book community wide", msg_id="102", subject_id=None)
    query = _wire(store)

    result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.NONE
    assert {e.chunk_text for e in result.evidence} == {
        "Read a book about subject one",
        "Read a book community wide",
    }
    persisted = next(iter(store._queries.values()))
    assert persisted.subject_scope is None


def test_subject_scope_over_community_wide_corpus_is_no_evidence() -> None:
    """Under the default single-subject mapping every chunk is community-wide,
    so a non-None scope fails closed to NO_EVIDENCE — and the persisted
    ``Query`` row still records the requested scope (fallback contour)."""
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nRead a book community wide", msg_id="100", subject_id=None)
    query = _wire(store)

    result = query.answer(_ask("book"), subject_scope="subj-1")

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert result.evidence == []
    persisted = next(iter(store._queries.values()))
    assert persisted.fallback is FallbackMode.NO_EVIDENCE
    assert persisted.subject_scope == "subj-1"


def test_answer_composes_subject_scope_with_date_range() -> None:
    """Both per-call filters apply together as a conjunction."""
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nRead a book in May", msg_id="100", subject_id="subj-1")
    _ingest(store, "2026-06-15\nRead a book in June", msg_id="101", subject_id="subj-1")
    _ingest(store, "2026-06-15\nRead a book in June too", msg_id="102", subject_id=None)
    query = _wire(store)

    result = query.answer(
        _ask("book"),
        date_range=DateRange(start=date(2026, 6, 1)),
        subject_scope="subj-1",
    )

    assert result.fallback is FallbackMode.NONE
    assert [e.chunk_text for e in result.evidence] == ["Read a book in June"]


# --- Slice 4.3b: stub chat clients for the four new contours -----------------


class _MarkerChatClient:
    """Stub chat client that emits a configured ``UncertaintyMarker``.

    Used to drive ``QueryService`` through the weak-evidence, ambiguous,
    and LLM-marker no_evidence contours without relying on a real
    provider. ``model_name`` carries the marker so the trace assertion
    cannot be confused with the production ``MockChatClient``.
    """

    def __init__(
        self,
        marker: str,
        *,
        cite_all: bool = True,
        cited_subset_size: int | None = None,
        answer_text: str = "stub answer",
    ) -> None:
        self._marker = marker
        self._cite_all = cite_all
        self._cited_subset_size = cited_subset_size
        self._answer_text = answer_text

    @property
    def model_name(self) -> str:
        return f"stub-{self._marker}"

    def complete(self, prompt: AnswerPrompt) -> ChatResponse:
        # ``cited_subset_size`` (test-only) cites a strict prefix of the
        # context so the seam can be characterized carrying the LLM's
        # actual subset rather than the full retrieved set.
        if self._cited_subset_size is not None:
            citations = list(prompt.cited_chunk_ids)[: self._cited_subset_size]
        else:
            citations = list(prompt.cited_chunk_ids) if self._cite_all else []
        raw = json.dumps(
            {
                "answer_text": self._answer_text,
                "cited_chunk_ids": citations,
                "uncertainty": self._marker,
            }
        )
        return ChatResponse(
            raw_text=raw,
            model_name=self.model_name,
            token_counts={"prompt": 7, "completion": 11},
            latency_ms=42,
        )


class _UnavailableChatClient:
    @property
    def model_name(self) -> str:
        return "stub-unavailable"

    def complete(self, prompt: AnswerPrompt) -> ChatResponse:
        raise ChatProviderUnavailableError("test: provider down")


class _MalformedChatClient:
    @property
    def model_name(self) -> str:
        return "stub-malformed"

    def complete(self, prompt: AnswerPrompt) -> ChatResponse:
        return ChatResponse(
            raw_text="this is not JSON {",
            model_name=self.model_name,
            token_counts={"prompt": 5, "completion": 0},
            latency_ms=33,
        )


def _wire_with_chat(store: MockDomainStore, chat: object, *, top_k: int = 5) -> QueryService:
    return QueryService(
        store,
        store,
        MockEmbeddingClient(),
        chat,  # type: ignore[arg-type]
        top_k=top_k,
    )


def test_weak_evidence_marker_grades_query_and_trace(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``uncertainty="uncertain"`` → ``FallbackMode.WEAK_EVIDENCE`` on Query + trace."""
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nMorning routine\nTried a new book")
    query = _wire_with_chat(store, _MarkerChatClient("uncertain"))

    with caplog.at_level("INFO"):
        result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.WEAK_EVIDENCE
    assert result.evidence  # retrieval still succeeded
    assert result.answer_text == "stub answer"

    persisted = next(iter(store._queries.values()))
    assert persisted.fallback is FallbackMode.WEAK_EVIDENCE
    trace = store.get_answer_trace_for_query(
        persisted.query_id, community_id=persisted.community_id
    )
    assert trace is not None
    assert trace.fallback_mode is FallbackMode.WEAK_EVIDENCE
    assert trace.answer_text == "stub answer"
    assert trace.model_name == "stub-uncertain"
    assert trace.latency_ms == 42
    assert trace.token_counts == {"prompt": 7, "completion": 11}
    assert tuple(trace.context_chunk_ids) == tuple(e.chunk_id for e in result.evidence)
    assert "fallback=weak_evidence" in caplog.text


def test_ambiguous_marker_grades_query_and_trace() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nMorning routine\nTried a new book")
    query = _wire_with_chat(store, _MarkerChatClient("ambiguous"))

    result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.AMBIGUOUS
    assert result.evidence
    assert result.answer_text == "stub answer"

    persisted = next(iter(store._queries.values()))
    assert persisted.fallback is FallbackMode.AMBIGUOUS
    trace = store.get_answer_trace_for_query(
        persisted.query_id, community_id=persisted.community_id
    )
    assert trace is not None
    assert trace.fallback_mode is FallbackMode.AMBIGUOUS
    assert trace.answer_text == "stub answer"
    assert trace.model_name == "stub-ambiguous"
    assert trace.latency_ms == 42


def test_llm_no_evidence_marker_preserves_llm_text_and_context_ids() -> None:
    """LLM-marker NO_EVIDENCE: retrieval found chunks; model judged them not-evidence.

    Distinct from empty-retrieval NO_EVIDENCE: the trace records the
    LLM's answer text and the retrieved ``context_chunk_ids``; the
    ``AnswerResult.evidence`` list stays non-empty so the Dispatcher
    can disambiguate at the reply surface (Decision 8, D-035).
    """
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nMorning routine\nTried a new book")
    query = _wire_with_chat(
        store,
        _MarkerChatClient("no_evidence", cite_all=False, answer_text="not evidence"),
    )

    result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert result.evidence  # retrieval found chunks
    assert result.answer_text == "not evidence"

    persisted = next(iter(store._queries.values()))
    assert persisted.fallback is FallbackMode.NO_EVIDENCE
    trace = store.get_answer_trace_for_query(
        persisted.query_id, community_id=persisted.community_id
    )
    assert trace is not None
    assert trace.fallback_mode is FallbackMode.NO_EVIDENCE
    assert trace.answer_text == "not evidence"
    assert tuple(trace.context_chunk_ids) == tuple(e.chunk_id for e in result.evidence)
    assert trace.latency_ms == 42
    assert trace.token_counts == {"prompt": 7, "completion": 11}


def test_provider_unavailable_grades_query_and_trace() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nMorning routine\nTried a new book")
    query = _wire_with_chat(store, _UnavailableChatClient())

    result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.PROVIDER_UNAVAILABLE
    assert result.evidence  # retrieval still produced candidates
    assert result.answer_text is None

    persisted = next(iter(store._queries.values()))
    assert persisted.fallback is FallbackMode.PROVIDER_UNAVAILABLE
    trace = store.get_answer_trace_for_query(
        persisted.query_id, community_id=persisted.community_id
    )
    assert trace is not None
    assert trace.fallback_mode is FallbackMode.PROVIDER_UNAVAILABLE
    assert trace.answer_text == ""
    assert trace.model_name == "stub-unavailable"
    assert trace.latency_ms == 0
    assert trace.token_counts == {}
    assert tuple(trace.context_chunk_ids) == tuple(e.chunk_id for e in result.evidence)


def test_parse_failure_grades_query_and_trace_with_raw_text() -> None:
    """PARSE_FAILURE preserves ``response.raw_text`` as trace.answer_text (forensics)."""
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nMorning routine\nTried a new book")
    query = _wire_with_chat(store, _MalformedChatClient())

    result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.PARSE_FAILURE
    assert result.evidence
    assert result.answer_text is None  # no usable structured answer

    persisted = next(iter(store._queries.values()))
    assert persisted.fallback is FallbackMode.PARSE_FAILURE
    trace = store.get_answer_trace_for_query(
        persisted.query_id, community_id=persisted.community_id
    )
    assert trace is not None
    assert trace.fallback_mode is FallbackMode.PARSE_FAILURE
    assert trace.answer_text == "this is not JSON {"
    assert trace.model_name == "stub-malformed"
    assert trace.latency_ms == 33
    assert trace.token_counts == {"prompt": 5, "completion": 0}
    assert tuple(trace.context_chunk_ids) == tuple(e.chunk_id for e in result.evidence)


# --- Packet 1 (D-098): cited_chunk_ids seam characterization -------------------


def test_cited_chunk_ids_empty_on_empty_store_no_evidence() -> None:
    store = MockDomainStore()
    query = _wire(store)

    result = query.answer(_ask("anything"))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert result.cited_chunk_ids == ()


def test_cited_chunk_ids_empty_on_blank_query() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nMorning routine")
    query = _wire(store)

    result = query.answer(_ask("   "))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert result.cited_chunk_ids == ()


def test_cited_chunk_ids_empty_on_unrelated_query_no_evidence() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nMorning routine")
    query = _wire(store)

    result = query.answer(_ask("snowstorm"))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert result.cited_chunk_ids == ()


def test_cited_chunk_ids_empty_on_provider_unavailable() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nMorning routine\nTried a new book")
    query = _wire_with_chat(store, _UnavailableChatClient())

    result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.PROVIDER_UNAVAILABLE
    assert result.evidence  # retrieval succeeded — but no trustworthy cited set
    assert result.cited_chunk_ids == ()


def test_cited_chunk_ids_empty_on_parse_failure() -> None:
    """PARSE_FAILURE never derives a cited set from raw_text (I-9 unvalidated)."""
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nMorning routine\nTried a new book")
    query = _wire_with_chat(store, _MalformedChatClient())

    result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.PARSE_FAILURE
    assert result.evidence
    assert result.cited_chunk_ids == ()


def test_cited_chunk_ids_empty_on_llm_no_evidence_marker() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nMorning routine\nTried a new book")
    query = _wire_with_chat(
        store, _MarkerChatClient("no_evidence", cite_all=False, answer_text="not evidence")
    )

    result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.NO_EVIDENCE
    assert result.cited_chunk_ids == ()


def test_cited_chunk_ids_mirror_full_context_when_model_cites_all() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nMorning routine\nTried a new book\nAnother book chapter")
    query = _wire(store)  # production MockChatClient cites the whole context

    result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.NONE
    assert list(result.cited_chunk_ids) == result.context_chunk_ids
    assert set(result.cited_chunk_ids).issubset(set(result.context_chunk_ids))


def test_cited_chunk_ids_carry_llm_subset_not_full_retrieved() -> None:
    """The milestone core: the seam carries the LLM's actual subset, not all retrieved."""
    store = MockDomainStore()
    # Two retrieved chunks require two notes (one /note is one chunk — I-5 / D-106).
    _ingest(store, "2026-05-09\nTried a new book", msg_id="100")
    _ingest(store, "2026-05-09\nAnother book chapter", msg_id="101")
    query = _wire_with_chat(store, _MarkerChatClient("confident", cited_subset_size=1))

    result = query.answer(_ask("book"))

    assert result.fallback is FallbackMode.NONE
    assert len(result.context_chunk_ids) >= 2  # >1 chunk retrieved
    assert len(result.cited_chunk_ids) == 1  # but the model cited only one
    assert set(result.cited_chunk_ids) < set(result.context_chunk_ids)  # strict subset


# ---------------------------------------------------------------------------
# Pure retrieval seam (RC-3): QueryService.retrieve
# ---------------------------------------------------------------------------


def test_retrieve_is_pure_and_returns_candidates() -> None:
    """``retrieve`` writes no rows — persistence stays with the caller so
    ``Query.fallback`` remains a single post-generation decision (D-035)."""
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nTried a new book")
    query = _wire(store)

    candidates = query.retrieve("42", "book")

    assert candidates.merged != []
    assert candidates.embedding_model_name == MockEmbeddingClient().model_name
    assert store.len_queries() == 0
    assert store.len_retrieval_hits() == 0


def test_retrieve_forwards_kwargs_to_both_legs() -> None:
    store = MockDomainStore()
    _ingest(store, "2026-05-09\nTried a new book", msg_id="100", subject_id="kid-1")
    _ingest(store, "2026-05-20\nAnother book chapter", msg_id="101", subject_id="kid-1")
    query = _wire(store)

    scoped = query.retrieve(
        "42",
        "book",
        date_range=DateRange(start=date(2026, 5, 1), end=date(2026, 5, 10)),
        subject_scope="kid-1",
    )
    texts = {h.chunk.chunk_text for h in scoped.merged}
    assert texts == {"Tried a new book"}

    # Strict subject match: a different scope excludes everything.
    other = query.retrieve("42", "book", subject_scope="kid-2")
    assert other.merged == []


def test_retrieve_requires_community_id() -> None:
    store = MockDomainStore()
    query = _wire(store)
    with pytest.raises(ValueError, match="community_id"):
        query.retrieve("", "book")
