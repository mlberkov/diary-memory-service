"""Minimal Telegram update schema.

Only the fields needed to drive command routing are modelled. Unknown
fields are ignored so real Telegram payloads (which carry many extra
keys) parse cleanly.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TelegramUser(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    id: int
    # Host-supplied, non-authoritative display inputs (D-084). Either may be
    # withheld. Captured behind the adapter-owned storage seam only; never
    # carried into a core type.
    username: str | None = None
    first_name: str | None = None


class TelegramChat(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    id: int


class TelegramMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    message_id: int
    date: int
    edit_date: int | None = None
    chat: TelegramChat
    from_: TelegramUser = Field(alias="from")
    text: str | None = None


class TelegramUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    update_id: int
    message: TelegramMessage | None = None
