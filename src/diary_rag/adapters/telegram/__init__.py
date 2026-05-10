"""Telegram channel adapter.

Mounts the webhook endpoint via :func:`register_telegram_webhook`. Per
Invariant I-1, Telegram-specific types do not leak past this package.
"""

from diary_rag.adapters.telegram.webhook import register_telegram_webhook

__all__ = ["register_telegram_webhook"]
