"""Chat-provider adapters.

Concrete implementations of :class:`diary_rag.core.answers.ChatClient`.
Adapter selection is driven by ``Settings.chat_backend`` (``mock`` or
``openai``); domain code remains SDK-free (Invariant I-11).

``build_chat_client`` is the single factory used by both the app boot
gate and the webhook dispatcher so the two paths cannot disagree on
which backend / model they expect.
"""

from diary_rag.adapters.answers.factory import build_chat_client
from diary_rag.adapters.answers.mock import MockChatClient
from diary_rag.adapters.answers.openai_client import OpenAIChatClient

__all__ = ["MockChatClient", "OpenAIChatClient", "build_chat_client"]
