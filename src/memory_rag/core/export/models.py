"""Channel-neutral raw-export types.

``ExportPayload`` carries the bytes a host adapter needs to deliver the
file (Telegram ``sendDocument``, an HTTP download response, a host-app
screen, ...). The shape is transport-agnostic: no Telegram type, no
provider SDK, no host identifier (D-026).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ExportFormat(StrEnum):
    """User-facing export format (D-027 / D-029)."""

    JSON = "json"
    TXT = "txt"


@dataclass(frozen=True, slots=True)
class ExportPayload:
    """One synchronous raw-export result.

    ``content`` already includes the inline provenance envelope (JSON
    top-level ``export`` object, TXT ``#`` header lines).
    """

    content: bytes
    filename: str
    media_type: str
    format: ExportFormat
    record_count: int
    generated_at: datetime
    community_id: str
    requester_user_id: str
