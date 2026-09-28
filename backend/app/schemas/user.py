"""Auth + user schemas."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

if TYPE_CHECKING:
    from app.models.user import User


class TelegramAuthRequest(BaseModel):
    """Sent by the Mini App on every cold start."""

    init_data: str = Field(..., min_length=10, description="Подписанная строка initData от Telegram")
    device: str | None = Field(None, max_length=64, description="Метка устройства клиента")
    platform: str | None = Field(None, max_length=32)


class AccessToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserRead(ORMModel):
    id: UUID
    telegram_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    display_name: str
    is_admin: bool = False
    is_banned: bool = False
    created_at: dt.datetime

    @classmethod
    def from_model(cls, user: User) -> UserRead:
        return cls(
            id=user.id,
            telegram_id=user.telegram_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            display_name=user.display_name,
            is_admin=user.is_admin,
            is_banned=user.is_banned,
            created_at=user.created_at,
        )


class AuthResponse(BaseModel):
    user: UserRead
    token: AccessToken
    is_new: bool = False
    is_admin: bool = False


class ProfileUpdate(BaseModel):
    marketing_opt_in: bool | None = None


class TelegramUserPayload(BaseModel):
    """Bot → API handshake payload (trusted, comes from our own bot)."""

    telegram_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None
    is_premium: bool = False
    photo_url: str | None = None
