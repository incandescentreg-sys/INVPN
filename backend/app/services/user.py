"""User registration and profile handling."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import telegram_settings
from app.logging_config import get_logger
from app.models.user import User
from app.repositories.user import UserRepository
from app.utils.security import TelegramUser

log = get_logger(__name__)


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)

    async def register(self, tg: TelegramUser) -> tuple[User, bool]:
        """Create the user on first contact, refresh the profile afterwards."""
        user, created = await self._users.upsert_from_telegram(tg)
        await self._users.sync_admin_flag(user, telegram_settings.admin_set)
        if created:
            log.info("user.registered", telegram_id=tg.id, username=tg.username)
        return user, created

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self._users.get(user_id)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        return await self._users.get_by_telegram_id(telegram_id)

    async def update_profile(self, user_id: uuid.UUID, **fields: object) -> User | None:
        user = await self._users.get(user_id)
        if user is None:
            return None
        for key, value in fields.items():
            if hasattr(user, key) and value is not None:
                setattr(user, key, value)
        await self._session.flush()
        return user

    async def touch(self, user_id: uuid.UUID) -> None:
        await self._users.touch_last_seen(user_id)
