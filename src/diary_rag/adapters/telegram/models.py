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


class TelegramChat(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    id: int


class TelegramMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    message_id: int
    date: int
    chat: TelegramChat
    from_: TelegramUser = Field(alias="from")
    text: str | None = None


class TelegramUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    update_id: int
    message: TelegramMessage | None = None
