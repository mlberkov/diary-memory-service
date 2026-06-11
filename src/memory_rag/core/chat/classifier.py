"""``ChatRouteClassifier`` Protocol and its failure contract (RC-2, D-108).

Every route classifier — the deterministic test mock today, the OpenAI
function-calling adapter behind ``classifier_backend="openai"`` — exposes
``model_name`` and a sync ``classify(question) -> RouteClassification``.
Core code depends only on this Protocol, never on a provider SDK
(Invariant I-11).

The two error classes split provider failure the same way the chat seam
does (D-035): ``ChatRouteClassifierUnavailableError`` means no output
existed (unreachable after bounded retries); ``ChatRouteOutputError``
means output existed but was unusable, and carries it verbatim so the
trace plane preserves truthful provenance.
"""

from __future__ import annotations

from typing import Protocol

from memory_rag.core.chat.models import RouteClassification


class ChatRouteClassifier(Protocol):
    """Sync route-classifier seam used by ``RoutedChatService.chat``."""

    @property
    def model_name(self) -> str: ...

    def classify(self, question: str) -> RouteClassification: ...


class ChatRouteClassifierError(RuntimeError):
    """Base class for classifier-call failures (RC-2)."""


class ChatRouteClassifierUnavailableError(ChatRouteClassifierError):
    """The classifier provider is unreachable / unusable for this call.

    Raised by real adapters after bounded retries are exhausted.
    ``RoutedChatService.chat`` catches it once and routes the question
    to the default ``notes_lookup`` route — no retry, no repair.
    """


class ChatRouteOutputError(ChatRouteClassifierError):
    """The classifier produced output that does not name a known route.

    Covers a missing function call, malformed arguments JSON, or a route
    value outside :class:`~memory_rag.core.chat.models.ChatRoute`.
    ``raw_output`` preserves the unusable output verbatim for the trace
    plane.
    """

    def __init__(self, message: str, *, raw_output: str) -> None:
        super().__init__(message)
        self.raw_output = raw_output
