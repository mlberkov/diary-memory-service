"""Dispatcher ``/chat`` branch (RC-2/RC-3, D-108).

Reply-surface contract: an effective ``notes_lookup`` answer is
byte-identical to the ``/ask`` reply for the same store and question
(one formatting surface); a rerouted answer appends one cause-neutral
trailer; a successful ``model_only`` answer appends the explicit
model-knowledge trailer (generalized I-9); ``model_only`` failures reuse
the pinned provider/parse literals. RC-3: an effective
``notes_plus_model`` answer renders the segmented mixed shape — honest
degradation strictly before any model content, the model segment always
labeled, failures reusing the same pinned literals. The ``/sources``
cache stays an ``/ask``-only surface.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from memory_rag.adapters.answers import MockChatClient
from memory_rag.adapters.chat_routing import MockRouteClassifier
from memory_rag.adapters.embeddings import MockEmbeddingClient
from memory_rag.config import Settings
from memory_rag.core.chat import ChatRoute
from memory_rag.core.routing import InboundMessage, RouteKind
from memory_rag.services import (
    Dispatcher,
    DomainService,
    ExportService,
    QueryService,
    RoutedChatService,
)
from memory_rag.services.dispatcher import (
    _HEADER_CHAT_NO_NOTES,
    _HEADER_CHAT_WEAK_NOTES,
    _LABEL_CHAT_NOTES,
    _REPLY_CHAT_UNAVAILABLE,
    _REPLY_NO_MATCHES_TEMPLATE,
    _REPLY_PARSE_FAILURE,
    _REPLY_PROVIDER_UNAVAILABLE,
    _REPLY_SOURCES_NONE,
    _TRAILER_AMBIGUOUS,
    _TRAILER_CHAT_REROUTED,
    _TRAILER_MODEL_KNOWLEDGE,
    _TRAILER_WEAK_EVIDENCE,
)
from memory_rag.storage.mock import MockDomainStore
from tests.test_routed_chat_notes_plus_model import _SegmentedChatClient
from tests.test_routed_chat_service import _DownChatClient, _JunkChatClient


def _settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _inbound(
    route: RouteKind,
    payload: str,
    *,
    chat: str = "fam-A",
    msg_id: str = "1",
    route_source: Literal["command", "heuristic"] = "command",
) -> InboundMessage:
    return InboundMessage(
        external_message_id=msg_id,
        external_chat_id=chat,
        external_user_id="7",
        community_id=chat,
        text=f"/{route.value} {payload}",
        route=route,
        received_at=datetime.now(tz=UTC),
        route_source=route_source,
        payload=payload,
    )


def _dispatcher(
    store: MockDomainStore,
    *,
    classifier: MockRouteClassifier | None = None,
    chat_client: object | None = None,
    routed: bool = True,
) -> Dispatcher:
    embedding = MockEmbeddingClient()
    chat = chat_client if chat_client is not None else MockChatClient()
    query = QueryService(store, store, embedding, chat)  # type: ignore[arg-type]
    routed_chat = (
        RoutedChatService(
            classifier if classifier is not None else MockRouteClassifier(),
            query,
            chat,  # type: ignore[arg-type]
            store,
        )
        if routed
        else None
    )
    return Dispatcher(
        DomainService(store, embedding_client=embedding),
        query,
        ExportService(store),
        _settings(),
        routed_chat=routed_chat,
    )


def _seed(store: MockDomainStore, text: str = "Tried a new book", *, msg_id: str = "100") -> None:
    DomainService(store, embedding_client=MockEmbeddingClient()).ingest(
        _inbound(RouteKind.NOTE, f"2026-05-09\n{text}", msg_id=msg_id)
    )


def test_chat_notes_lookup_reply_byte_equals_the_ask_reply() -> None:
    store = MockDomainStore()
    _seed(store)
    dispatcher = _dispatcher(store)

    chat_reply = dispatcher.dispatch(_inbound(RouteKind.CHAT, "book", msg_id="2"))
    ask_reply = dispatcher.dispatch(_inbound(RouteKind.ASK, "book", msg_id="3"))

    assert chat_reply.route is RouteKind.CHAT
    assert chat_reply.reply_text == ask_reply.reply_text
    assert chat_reply.metadata["requested_route"] == "notes_lookup"
    assert chat_reply.metadata["effective_route"] == "notes_lookup"
    assert chat_reply.metadata["route_source"] == "command"


def test_chat_rerouted_reply_appends_the_exact_neutral_trailer() -> None:
    """One trailer for every funnel cause — the wording never names the
    cause (classifier failure vs undispatchable route vs empty question).
    RC-3 narrowed the funnel: ``notes_plus_knowledge`` is the remaining
    not-yet-dispatchable route until RC-4."""
    store = MockDomainStore()
    _seed(store)
    dispatcher = _dispatcher(
        store, classifier=MockRouteClassifier(default_route=ChatRoute.NOTES_PLUS_KNOWLEDGE)
    )

    chat_reply = dispatcher.dispatch(_inbound(RouteKind.CHAT, "book", msg_id="2"))
    ask_reply = dispatcher.dispatch(_inbound(RouteKind.ASK, "book", msg_id="3"))

    assert chat_reply.reply_text == f"{ask_reply.reply_text}\n\n{_TRAILER_CHAT_REROUTED}"
    assert _TRAILER_CHAT_REROUTED == "(answered from your saved notes)"
    assert chat_reply.metadata["requested_route"] == "notes_plus_knowledge"
    assert chat_reply.metadata["effective_route"] == "notes_lookup"
    for cause_word in ("classifier", "error", "failed", "unavailable"):
        assert cause_word not in chat_reply.reply_text


def test_chat_model_only_reply_carries_the_model_knowledge_trailer() -> None:
    store = MockDomainStore()
    dispatcher = _dispatcher(store)

    reply = dispatcher.dispatch(_inbound(RouteKind.CHAT, "what is model_only phonemic awareness"))

    assert reply.reply_text == (
        "Mock model-knowledge answer (no notes consulted)." f"\n\n{_TRAILER_MODEL_KNOWLEDGE}"
    )
    assert _TRAILER_MODEL_KNOWLEDGE == "(model knowledge — not from your saved notes)"
    assert reply.metadata["requested_route"] == "model_only"
    assert reply.metadata["effective_route"] == "model_only"


def test_chat_model_only_provider_unavailable_reuses_the_pinned_literal() -> None:
    store = MockDomainStore()
    dispatcher = _dispatcher(
        store,
        classifier=MockRouteClassifier(default_route=ChatRoute.MODEL_ONLY),
        chat_client=_DownChatClient(),
    )
    reply = dispatcher.dispatch(_inbound(RouteKind.CHAT, "anything"))
    assert reply.reply_text == _REPLY_PROVIDER_UNAVAILABLE


def test_chat_model_only_parse_failure_reuses_the_pinned_literal() -> None:
    store = MockDomainStore()
    dispatcher = _dispatcher(
        store,
        classifier=MockRouteClassifier(default_route=ChatRoute.MODEL_ONLY),
        chat_client=_JunkChatClient(),
    )
    reply = dispatcher.dispatch(_inbound(RouteKind.CHAT, "anything"))
    assert reply.reply_text == _REPLY_PARSE_FAILURE


def test_chat_without_a_routed_service_returns_the_unavailable_literal() -> None:
    store = MockDomainStore()
    dispatcher = _dispatcher(store, routed=False)
    reply = dispatcher.dispatch(_inbound(RouteKind.CHAT, "book"))
    assert reply.reply_text == _REPLY_CHAT_UNAVAILABLE
    assert reply.route is RouteKind.CHAT


def test_chat_notes_plus_model_success_reply_renders_both_labeled_segments() -> None:
    store = MockDomainStore()
    _seed(store)
    dispatcher = _dispatcher(
        store,
        classifier=MockRouteClassifier(default_route=ChatRoute.NOTES_PLUS_MODEL),
        chat_client=_SegmentedChatClient(),
    )

    reply = dispatcher.dispatch(_inbound(RouteKind.CHAT, "book"))

    assert reply.reply_text == (
        f"{_LABEL_CHAT_NOTES}\nNotes say he likes books."
        f"\n\n{_TRAILER_MODEL_KNOWLEDGE}\nGeneral guidance."
    )
    assert reply.metadata["requested_route"] == "notes_plus_model"
    assert reply.metadata["effective_route"] == "notes_plus_model"


def test_chat_notes_plus_model_weak_evidence_states_degradation_first() -> None:
    store = MockDomainStore()
    _seed(store)
    dispatcher = _dispatcher(
        store,
        classifier=MockRouteClassifier(default_route=ChatRoute.NOTES_PLUS_MODEL),
        chat_client=_SegmentedChatClient(uncertainty="uncertain"),
    )

    reply = dispatcher.dispatch(_inbound(RouteKind.CHAT, "book"))

    assert reply.reply_text == (
        f"{_HEADER_CHAT_WEAK_NOTES}"
        f"\n\n{_LABEL_CHAT_NOTES}\nNotes say he likes books."
        f"\n\n{_TRAILER_MODEL_KNOWLEDGE}\nGeneral guidance."
    )
    assert reply.reply_text.startswith(_HEADER_CHAT_WEAK_NOTES)


def test_chat_notes_plus_model_no_evidence_states_degradation_before_model_content() -> None:
    """D-108 honest degradation: empty diary evidence is stated explicitly
    before any general content."""
    store = MockDomainStore()  # nothing ingested
    dispatcher = _dispatcher(
        store, classifier=MockRouteClassifier(default_route=ChatRoute.NOTES_PLUS_MODEL)
    )

    reply = dispatcher.dispatch(_inbound(RouteKind.CHAT, "what games suit him"))

    assert reply.reply_text == (
        f"{_HEADER_CHAT_NO_NOTES}"
        f"\n\n{_TRAILER_MODEL_KNOWLEDGE}\nMock general-knowledge segment."
    )
    assert reply.reply_text.index(_HEADER_CHAT_NO_NOTES) < reply.reply_text.index(
        _TRAILER_MODEL_KNOWLEDGE
    )
    for cause_word in ("classifier", "rewrite", "error", "failed", "unavailable"):
        assert cause_word not in reply.reply_text


def test_chat_notes_plus_model_omits_an_empty_model_segment_entirely() -> None:
    """No orphan label: an empty model segment renders nothing at all."""
    store = MockDomainStore()
    _seed(store)
    dispatcher = _dispatcher(
        store,
        classifier=MockRouteClassifier(default_route=ChatRoute.NOTES_PLUS_MODEL),
        chat_client=_SegmentedChatClient(model_text=""),
    )

    reply = dispatcher.dispatch(_inbound(RouteKind.CHAT, "book"))

    assert reply.reply_text == f"{_LABEL_CHAT_NOTES}\nNotes say he likes books."
    assert _TRAILER_MODEL_KNOWLEDGE not in reply.reply_text


def test_chat_notes_plus_model_failures_reuse_the_pinned_literals() -> None:
    store = MockDomainStore()
    _seed(store)
    down = _dispatcher(
        store,
        classifier=MockRouteClassifier(default_route=ChatRoute.NOTES_PLUS_MODEL),
        chat_client=_DownChatClient(),
    )
    assert down.dispatch(_inbound(RouteKind.CHAT, "book")).reply_text == (
        _REPLY_PROVIDER_UNAVAILABLE
    )
    junk = _dispatcher(
        store,
        classifier=MockRouteClassifier(default_route=ChatRoute.NOTES_PLUS_MODEL),
        chat_client=_JunkChatClient(),
    )
    assert junk.dispatch(_inbound(RouteKind.CHAT, "book", msg_id="2")).reply_text == (
        _REPLY_PARSE_FAILURE
    )


def test_rc3_literals_are_byte_pinned_and_siblings_are_byte_identical() -> None:
    """The three new RC-3 literals are pinned; every pre-existing sibling
    literal of the answer/chat reply family is asserted byte-identical
    (no literal other than the new ones changed in this packet)."""
    assert _HEADER_CHAT_NO_NOTES == (
        "Nothing in your saved notes covers this — here's general information instead."
    )
    assert _HEADER_CHAT_WEAK_NOTES == "Your saved notes only weakly cover this."
    assert _LABEL_CHAT_NOTES == "From your saved notes:"
    # Sibling guards (RC-2 and earlier wording, byte-identical):
    assert _TRAILER_MODEL_KNOWLEDGE == "(model knowledge — not from your saved notes)"
    assert _TRAILER_CHAT_REROUTED == "(answered from your saved notes)"
    assert _REPLY_CHAT_UNAVAILABLE == (
        "Routed chat isn't available here — use /ask to query your saved notes."
    )
    assert _TRAILER_WEAK_EVIDENCE == "(weak evidence — model expressed uncertainty)"
    assert _TRAILER_AMBIGUOUS == "(ambiguous question — refine and ask again)"
    assert _REPLY_PROVIDER_UNAVAILABLE == (
        "Couldn't generate an answer — chat provider is unavailable. Try again later."
    )
    assert _REPLY_PARSE_FAILURE == (
        "Couldn't generate an answer — provider response was unparseable. Try again."
    )
    assert _REPLY_NO_MATCHES_TEMPLATE == (
        "Nothing in your saved notes matched '{query}'. "
        "Try rephrasing the question, or use words that appear in your notes."
    )


def test_chat_does_not_create_a_sources_cache_entry() -> None:
    store = MockDomainStore()
    _seed(store)
    dispatcher = _dispatcher(store)

    dispatcher.dispatch(_inbound(RouteKind.CHAT, "book", msg_id="2"))
    sources = dispatcher.dispatch(_inbound(RouteKind.SOURCES, "", msg_id="3"))

    assert sources.reply_text == _REPLY_SOURCES_NONE
    assert sources.source_chunks is None


def test_chat_does_not_overwrite_the_ask_sources_cache() -> None:
    store = MockDomainStore()
    _seed(store)
    dispatcher = _dispatcher(store)

    ask = dispatcher.dispatch(_inbound(RouteKind.ASK, "book", msg_id="2"))
    assert ask.metadata["fallback"] == "none"
    dispatcher.dispatch(_inbound(RouteKind.CHAT, "what is model_only awareness", msg_id="3"))
    sources = dispatcher.dispatch(_inbound(RouteKind.SOURCES, "", msg_id="4"))

    # /sources still serves the /ask citation set, untouched by /chat.
    assert sources.source_chunks is not None
    assert len(sources.source_chunks) > 0
