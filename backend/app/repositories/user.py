"""User data access."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.utils.security import TelegramUser


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        stmt = select(User).where(User.telegram_id == telegram_id)
        return await self._session.scalar(stmt)

    async def upsert_from_telegram(self, tg: TelegramUser) -> tuple[User, bool]:
        """Create the user on first /start, refresh their profile afterwards."""
        user = await self.get_by_telegram_id(tg.id)
        created = user is None
        if user is None:
            user = User(telegram_id=tg.id)
            self._session.add(user)

        user.username = tg.username
        user.first_name = tg.first_name
        user.last_name = tg.last_name
        user.language_code = tg.language_code
        user.photo_url = tg.photo_url
        user.is_premium = tg.is_premium
        await self._session.flush()
        return user, created

    async def touch_last_seen(self, user_id: uuid.UUID) -> None:
        from app.utils.time import now

        user = await self.get(user_id)
        if user is not None:
            user.last_seen_at = now()

    # -- listing --------------------------------------------------------- #
    def _base_query(self) -> Select[tuple[User]]:
        return select(User).options(selectinload(User.subscriptions))

    async def list(
        self,
        *,
        search: str | None = None,
        is_banned: bool | None = None,
        is_admin: bool | None = None,
        has_active_subscription: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[User]:
        stmt = self._base_query()
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    User.username.ilike(pattern),
                    User.first_name.ilike(pattern),
                    User.last_name.ilike(pattern),
                    User.telegram_id == _int_or_none(search),
                )
            )
        if is_banned is not None:
            stmt = stmt.where(User.is_banned.is_(is_banned))
        if is_admin is not None:
            stmt = stmt.where(User.is_admin.is_(is_admin))
        stmt = stmt.order_by(User.created_at.desc()).limit(limit).offset(offset)
        return (await self._session.scalars(stmt)).all()

    async def count(self, **filters: object) -> int:
        stmt = select(func.count()).select_from(User)
        search = filters.get("search")
        if isinstance(search, str) and search.strip():
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    User.username.ilike(pattern),
                    User.first_name.ilike(pattern),
                    User.last_name.ilike(pattern),
                    User.telegram_id == _int_or_none(search),
                )
            )
        for key in ("is_banned", "is_admin"):
            value = filters.get(key)
            if value is not None:
                stmt = stmt.where(getattr(User, key).is_(bool(value)))
        return int(await self._session.scalar(stmt) or 0)

    async def set_ban(self, user_id: uuid.UUID, banned: bool, reason: str | None = None) -> User | None:
        from app.utils.time import now

        user = await self.get(user_id)
        if user is None:
            return None
        user.is_banned = banned
        user.ban_reason = reason if banned else None
        user.banned_at = now() if banned else None
        await self._session.flush()
        return user

    async def set_admin(self, user_id: uuid.UUID, is_admin: bool) -> User | None:
        user = await self.get(user_id)
        if user is None:
            return None
        user.is_admin = is_admin
        await self._session.flush()
        return user

    async def sync_admin_flag(self, user: User, admin_ids: set[int]) -> None:
        """ADMIN_TELEGRAM_IDS from .env is the source of truth for the flag."""
        should_be_admin = user.telegram_id in admin_ids
        if user.is_admin != should_be_admin:
            user.is_admin = should_be_admin
            await self._session.flush()


def _int_or_none(value: str) -> int | None:
    return int(value) if value.strip().lstrip("-").isdigit() else -1
