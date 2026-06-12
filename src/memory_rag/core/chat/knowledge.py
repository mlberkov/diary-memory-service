"""``KnowledgeSource`` Protocol and its failure contract (RC-4, D-108).

Every knowledge source — the deterministic test mock today, the hardened
Tavily adapter behind ``knowledge_backend="tavily"`` — exposes
``provider_name`` and a sync ``search(query) -> KnowledgeResult``. Core
code depends only on this Protocol, never on a provider SDK or HTTP
client (Invariant I-11).

The port is named for the knowledge-source seam, not welded to "web"
(D-108): ``KnowledgeExcerpt.ref`` is an opaque locator — a URL for the
Tavily adapter, but a curated domain-knowledge provider behind the same
port may use any stable reference string. The reply layer renders refs
verbatim as the web-plane citations (generalized I-9).

The two error classes split provider failure the same way the
classifier and rewriter seams do (D-035): ``KnowledgeSourceUnavailableError``
means no output existed (unreachable after bounded retries);
``KnowledgeSourceOutputError`` means output existed but was unusable,
and carries it verbatim so the trace plane preserves truthful
provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class KnowledgeExcerpt:
    """One retrieved knowledge excerpt.

    ``ref`` is the opaque locator the synthesis prompt offers for
    citation and the reply layer renders verbatim; ``title`` and
    ``text`` are the provider's display title and content snippet.
    """

    ref: str
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class KnowledgeResult:
    """One successful knowledge-source call's output.

    ``raw_output`` preserves the provider's verbatim response body for
    the trace plane. An empty ``excerpts`` tuple is a valid outcome —
    the provider answered and found nothing.
    """

    excerpts: tuple[KnowledgeExcerpt, ...]
    raw_output: str
    latency_ms: int


class KnowledgeSource(Protocol):
    """Sync knowledge-source seam used by ``RoutedChatService`` (RC-4)."""

    @property
    def provider_name(self) -> str: ...

    def search(self, query: str) -> KnowledgeResult: ...


class KnowledgeSourceError(RuntimeError):
    """Base class for knowledge-source call failures (RC-4)."""


class KnowledgeSourceUnavailableError(KnowledgeSourceError):
    """The knowledge provider is unreachable / unusable for this call.

    Raised by real adapters after bounded retries are exhausted.
    ``RoutedChatService`` catches it once and degrades within the route
    to an empty knowledge plane — no retry, no repair.
    """


class KnowledgeSourceOutputError(KnowledgeSourceError):
    """The knowledge provider produced output that is not a usable result.

    Covers a non-JSON body, a wrong-shape payload, or result entries
    missing their required fields. ``raw_output`` preserves the unusable
    output verbatim for the trace plane.
    """

    def __init__(self, message: str, *, raw_output: str) -> None:
        super().__init__(message)
        self.raw_output = raw_output
