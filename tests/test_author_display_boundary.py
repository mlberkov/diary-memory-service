"""Boundary guards for the author display-input seam (D-084).

The adapter-owned ``AuthorDisplayInputStore`` port must stay distinct from the
core ``DomainRepository``, and the captured snapshot must never leak into a core
type or core repository signature (D-026 / D-041; D-082 / D-083; I-1, I-6).
"""

from __future__ import annotations

import inspect
from dataclasses import fields

from memory_rag.adapters.telegram.author_display import AuthorDisplayInputStore
from memory_rag.core.domain.models import SourceMessage
from memory_rag.core.routing import InboundMessage
from memory_rag.storage.repository import DomainRepository

_PORT_METHODS = ("save_author_display_input", "get_author_display_input")
_DISPLAY_FIELDS = ("username", "first_name")


def test_domain_repository_has_no_display_input_methods() -> None:
    for name in _PORT_METHODS:
        assert not hasattr(
            DomainRepository, name
        ), f"{name} must not be on the core DomainRepository (D-083)"


def test_port_and_repository_are_distinct() -> None:
    # The adapter-owned port declares the display-input methods...
    for name in _PORT_METHODS:
        assert hasattr(AuthorDisplayInputStore, name)
    # ...and declares none of the core repository surface, so neither Protocol
    # is a structural subtype of the other.
    assert not hasattr(AuthorDisplayInputStore, "save_source_message")
    assert not hasattr(AuthorDisplayInputStore, "get_or_create_source_message")


def test_core_types_carry_no_display_fields() -> None:
    for model in (InboundMessage, SourceMessage):
        names = {f.name for f in fields(model)}
        for display_field in _DISPLAY_FIELDS:
            assert (
                display_field not in names
            ), f"{display_field} must not appear on core type {model.__name__}"


def test_get_or_create_source_message_signature_unchanged() -> None:
    params = list(inspect.signature(DomainRepository.get_or_create_source_message).parameters)
    assert params == ["self", "source"]
