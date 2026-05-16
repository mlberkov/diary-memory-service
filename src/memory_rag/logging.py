"""Logging bootstrap.

Stdlib-only on purpose at Slice 1.1. Structured logging is a later concern;
the contract here is "one configure call before app boot, idempotent".
"""

from __future__ import annotations

import logging

_CONFIGURED = False
_DEFAULT_FORMAT = "%(asctime)s %(levelname)s %(name)s :: %(message)s"


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging once. Safe to call repeatedly."""
    global _CONFIGURED
    if _CONFIGURED:
        logging.getLogger().setLevel(level.upper())
        return

    logging.basicConfig(
        level=level.upper(),
        format=_DEFAULT_FORMAT,
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Mirrors `logging.getLogger` for one import surface."""
    return logging.getLogger(name)
