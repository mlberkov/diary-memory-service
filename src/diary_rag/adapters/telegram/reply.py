"""Build a Telegram ``sendMessage`` payload.

Telegram supports answering inline via the webhook response body when the
JSON contains a ``method`` field. This avoids any outbound HTTP call.
"""

from __future__ import annotations


def build_send_message_payload(chat_id: str, text: str) -> dict[str, str | int]:
    return {
        "method": "sendMessage",
        "chat_id": int(chat_id),
        "text": text,
    }
