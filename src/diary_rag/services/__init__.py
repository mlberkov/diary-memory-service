"""Application services.

Thin orchestration layer that composes core domain logic with adapters
and storage.
"""

from diary_rag.services.dispatcher import Dispatcher

__all__ = ["Dispatcher"]
