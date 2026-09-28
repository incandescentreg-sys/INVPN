"""Bot middleware: one DB session per update + automatic user registration.

Registration on every update means a user who only taps a button is created in
the database too, not just those who typed /start.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from aiogram import BaseMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import session_scope
from app.logging_config import get_logger
from app.services.notification import NotificationService
from app.services.user import UserService
from app.utils.security import TelegramUser

if TYPE_CHECKING:
    from app.services.payment import PaymentService
    from app.services.subscription import SubscriptionService
    from app.services.vpn import VpnService

log = get_logger(__name__)


def to_telegram_user(event: Any) -> TelegramUser | None:
    tg_user = getattr(event, "from_user", None)
    if tg_user is None:
        return None
    return TelegramUser(
        id=tg_user.id,
        first_name=tg_user.first_name,
        last_name=tg_user.last_name,
        username=tg_user.username,
        language_code=tg_user.language_code,
        is_premium=bool(getattr(tg_user, "is_premium", False)),
    )


class DatabaseMiddleware(BaseMiddleware):
    """Injects `session`, `current_user` and `services` into every handler."""

    def __init__(self, bot: Any) -> None:
        super().__init__()
        self.bot = bot

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        tg = to_telegram_user(event)
        if tg is None:
            return await handler(event, data)

        async with session_scope() as session:
            user, created = await UserService(session).register(tg)
            data["session"] = session
            data["db_session"] = session
            data["current_user"] = user
            data["users"] = UserService(session)
            data["subscriptions"] = _subscriptions(session)
            data["vpn"] = _vpn(session)
            data["payments"] = _payments(session)
            data["notifications"] = NotificationService(session, bot=self.bot)
            data["is_new_user"] = created
            try:
                return await handler(event, data)
            except Exception:
                await session.rollback()
                raise


def _subscriptions(session: AsyncSession) -> SubscriptionService:
    from app.services.subscription import SubscriptionService

    return SubscriptionService(session)


def _vpn(session: AsyncSession) -> VpnService:
    from app.services.vpn import VpnService

    return VpnService(session)


def _payments(session: AsyncSession) -> PaymentService:
    from app.services.payment import PaymentService

    return PaymentService(session)


class BanMiddleware(BaseMiddleware):
    """Silently ignores banned users."""

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("current_user")
        if user is not None and getattr(user, "is_banned", False):
            log.warning("bot.banned_user_blocked", telegram_id=user.telegram_id)
            return None
        return await handler(event, data)
