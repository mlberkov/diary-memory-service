"""``OutwardQueryRewriter`` Protocol and its failure contract (RC-4, D-108).

The outward rewrite is the D-108 enrichment-pattern step "retrieve
personal context first, rewrite the outward query using it": the
retrieved note chunks condition how the user's question is phrased for
the external knowledge source, without the personal context itself
leaving as-is. Every outward rewriter — the deterministic test mock
today, the OpenAI function-calling adapter behind
``classifier_backend="openai"`` — exposes ``model_name`` and a sync
``rewrite_outward(question, *, notes_context) -> OutwardRewrite``. Core
code depends only on this Protocol, never on a provider SDK
(Invariant I-11).

There is deliberately no ``today`` parameter: nothing date-relative
resolves at this seam (the retrieval-side rewrite owns date mapping,
RC-3), and the contract stays deterministic given inputs.

The two error classes split provider failure the same way the
classifier and retrieval-rewriter seams do (D-035):
``OutwardRewriterUnavailableError`` means no output existed (unreachable
after bounded retries); ``OutwardRewriteOutputError`` means output
existed but was unusable, and carries it verbatim so the trace plane
preserves truthful provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class OutwardRewrite:
    """One successful outward-rewriter call's output.

    ``search_query`` is the text the knowledge source should search
    for; non-empty by contract (adapters treat an empty rewrite as
    unusable output). ``raw_output`` preserves the provider's verbatim
    output (the function-call arguments JSON for the OpenAI adapter)
    for the trace plane.
    """

    search_query: str
    raw_output: str
    model_name: str
    latency_ms: int


class OutwardQueryRewriter(Protocol):
    """Sync outward-rewriter seam used by ``RoutedChatService`` (RC-4)."""

    @property
    def model_name(self) -> str: ...

    def rewrite_outward(
        self, question: str, *, notes_context: tuple[str, ...]
    ) -> OutwardRewrite: ...


class OutwardRewriterError(RuntimeError):
    """Base class for outward-rewriter call failures (RC-4)."""


class OutwardRewriterUnavailableError(OutwardRewriterError):
    """The outward-rewriter provider is unreachable / unusable for this call.

    Raised by real adapters after bounded retries are exhausted.
    ``RoutedChatService`` catches it once and degrades to searching with
    the original question — no retry, no repair.
    """


class OutwardRewriteOutputError(OutwardRewriterError):
    """The outward rewriter produced output that is not a usable rewrite.

    Covers a missing function call, malformed arguments JSON, or an
    empty ``search_query``. ``raw_output`` preserves the unusable output
    verbatim for the trace plane.
    """

    def __init__(self, message: str, *, raw_output: str) -> None:
        super().__init__(message)
        self.raw_output = raw_output
