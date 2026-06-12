"""``QueryRewriter`` Protocol and its failure contract (RC-3, D-108).

Every query rewriter — the deterministic test mock today, the OpenAI
function-calling adapter behind ``classifier_backend="openai"`` — exposes
``model_name`` and a sync ``rewrite(question, *, today) -> QueryRewrite``.
Core code depends only on this Protocol, never on a provider SDK
(Invariant I-11).

The rewrite maps a natural-language question onto the already-landed
retrieval kwargs at the service seam — ``date_range`` and
``subject_scope`` (D-108: rewriting reuses landed capabilities). The
``subject_scope`` slot is seam-ready but no adapter emits it in this
packet: subject ids are opaque past the adapter edge and no
subject-name vocabulary exists to map mentions onto (see
``docs/assumptions.md``). ``today`` is supplied by the caller so the
contract stays deterministic given inputs — relative date expressions
("last month") need an anchor the rewriter cannot honestly invent.

The two error classes split provider failure the same way the
classifier seam does (D-035): ``QueryRewriterUnavailableError`` means no
output existed (unreachable after bounded retries);
``QueryRewriteOutputError`` means output existed but was unusable, and
carries it verbatim so the trace plane preserves truthful provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from memory_rag.core.domain.models import DateRange


@dataclass(frozen=True, slots=True)
class QueryRewrite:
    """One successful rewriter call's output.

    ``retrieval_query`` is the text the retrieval legs should search
    for; non-empty by contract (adapters treat an empty rewrite as
    unusable output). ``raw_output`` preserves the provider's verbatim
    output (the function-call arguments JSON for the OpenAI adapter)
    for the trace plane.
    """

    retrieval_query: str
    date_range: DateRange | None
    subject_scope: str | None
    raw_output: str
    model_name: str
    latency_ms: int


class QueryRewriter(Protocol):
    """Sync query-rewriter seam used by ``RoutedChatService`` (RC-3)."""

    @property
    def model_name(self) -> str: ...

    def rewrite(self, question: str, *, today: date) -> QueryRewrite: ...


class QueryRewriterError(RuntimeError):
    """Base class for rewriter-call failures (RC-3)."""


class QueryRewriterUnavailableError(QueryRewriterError):
    """The rewriter provider is unreachable / unusable for this call.

    Raised by real adapters after bounded retries are exhausted.
    ``RoutedChatService`` catches it once and degrades to retrieval on
    the original question with no date constraint — no retry, no repair.
    """


class QueryRewriteOutputError(QueryRewriterError):
    """The rewriter produced output that is not a usable rewrite.

    Covers a missing function call, malformed arguments JSON, an empty
    ``retrieval_query``, unparseable date bounds, or a contradictory
    date range. ``raw_output`` preserves the unusable output verbatim
    for the trace plane.
    """

    def __init__(self, message: str, *, raw_output: str) -> None:
        super().__init__(message)
        self.raw_output = raw_output
