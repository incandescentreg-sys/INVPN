"""Notification + support schemas."""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.enums import NotificationKind
from app.schemas.common import ORMModel


class NotificationRead(ORMModel):
    id: UUID
    kind: NotificationKind
    title: str
    body: str
    payload: dict[str, Any] | None = None
    is_read: bool = False
    created_at: dt.datetime


class SupportMessageCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    context: dict[str, Any] | None = None


class SupportInfoRead(BaseModel):
    username: str | None = None
    url: str | None = None
    message: str = "Если что-то не работает — напишите в поддержку, поможем быстро."


class ClientAppRead(BaseModel):
    id: UUID
    name: str
    platforms: list[str]
    store_url: str | None = None
    howto: list[str]


class InstructionsRead(BaseModel):
    apps: list[ClientAppRead]
    notes: list[str]
    faq: list[dict[str, str]]
