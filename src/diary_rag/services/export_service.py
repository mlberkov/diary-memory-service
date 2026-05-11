"""Channel-neutral raw-export service (D-029).

Reads the requester's full ``SourceMessage`` set for a scope through
``DiaryRepository.list_source_messages`` and renders it as bytes via the
configured serializer. Synchronous and single-shot — no streaming, no
async, no audit row.

Family scoping is mandatory (I-7); the family argument matches what
``DiaryService.ingest`` uses as the per-chat surrogate (the inbound
``external_chat_id``).
"""

from __future__ import annotations

from datetime import UTC, datetime

from diary_rag.core.export.models import ExportFormat, ExportPayload
from diary_rag.core.export.serializers import serialize_json, serialize_txt
from diary_rag.logging import get_logger
from diary_rag.storage.repository import DiaryRepository

log = get_logger(__name__)


def _filename(family_id: str, generated_at: datetime, extension: str) -> str:
    stamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    return f"raw_export_{family_id}_{stamp}.{extension}"


class ExportService:
    """Render the raw ``SourceMessage`` set for a scope as bytes."""

    def __init__(self, store: DiaryRepository) -> None:
        self._store = store

    def export(
        self,
        *,
        family_id: str,
        requester_user_id: str,
        format: ExportFormat,
    ) -> ExportPayload:
        if not family_id:
            raise ValueError("family_id is required (Runtime invariant R-3)")
        generated_at = datetime.now(tz=UTC)
        messages = self._store.list_source_messages(family_id)

        if format is ExportFormat.JSON:
            content = serialize_json(
                messages,
                family_id=family_id,
                requester_user_id=requester_user_id,
                generated_at=generated_at,
            )
            media_type = "application/json"
            extension = "json"
        else:
            content = serialize_txt(
                messages,
                family_id=family_id,
                requester_user_id=requester_user_id,
                generated_at=generated_at,
            )
            media_type = "text/plain; charset=utf-8"
            extension = "txt"

        payload = ExportPayload(
            content=content,
            filename=_filename(family_id, generated_at, extension),
            media_type=media_type,
            format=format,
            record_count=len(messages),
            generated_at=generated_at,
            family_id=family_id,
            requester_user_id=requester_user_id,
        )
        log.info(
            "export.ok family_id=%s format=%s count=%d bytes=%d",
            family_id,
            format.value,
            payload.record_count,
            len(content),
        )
        return payload
