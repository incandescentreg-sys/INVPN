"""Notifications: in-app feed + Telegram delivery, with de-duplication.

Reminder rows in `expiry_reminders` guarantee a user is told about a given
expiry threshold exactly once, no matter how often the cron job runs.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import worker_settings
from app.enums import NotificationChannel, NotificationKind, SubscriptionStatus
from app.logging_config import get_logger
from app.models.notification import ExpiryReminder, Notification
from app.models.subscription import Subscription
from app.models.user import User
from app.utils.money import format_money
from app.utils.time import now

log = get_logger(__name__)


class NotificationService:
    def __init__(self, session: AsyncSession, *, bot: Any | None = None) -> None:
        self._session = session
        self._bot = bot

    # -- feed ------------------------------------------------------------ #
    async def create(
        self,
        user: User,
        kind: NotificationKind,
        title: str,
        body: str,
        *,
        payload: dict[str, Any] | None = None,
        channel: NotificationChannel = NotificationChannel.WEBAPP,
        send_telegram: bool = False,
    ) -> Notification:
        notification = Notification(
            user_id=user.id,
            kind=kind,
            channel=NotificationChannel.TELEGRAM if send_telegram else channel,
            title=title,
            body=body,
            payload=payload,
        )
        self._session.add(notification)
        await self._session.flush()

        if send_telegram and self._bot is not None and not user.is_banned:
            ok, error = await self._send_telegram(user, title, body)
            notification.sent_at = now() if ok else None
            notification.error = None if ok else (error or "")[:512]
        return notification

    async def _send_telegram(self, user: User, title: str, body: str) -> tuple[bool, str | None]:
        if self._bot is None:
            return False, "Бот не инициализирован"
        try:
            await self._bot.send_message(user.telegram_id, f"🔔 <b>{title}</b>\n\n{body}", parse_mode="HTML")
            return True, None
        except Exception as exc:
            log.warning("notification.telegram_failed", telegram_id=user.telegram_id, error=str(exc)[:200])
            return False, str(exc)

    async def list_for_user(self, user_id: uuid.UUID, *, limit: int = 30) -> list[Notification]:
        stmt = (
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.scalars(stmt)).all())

    async def unread_count(self, user_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id, Notification.is_read.is_(False)
        )
        return int(await self._session.scalar(stmt) or 0)

    async def mark_read(self, user_id: uuid.UUID, notification_id: uuid.UUID) -> None:
        notification = await self._session.get(Notification, notification_id)
        if notification is not None and notification.user_id == user_id:
            notification.is_read = True
            notification.read_at = now()
            await self._session.flush()

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        stmt = (
            select(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
        )
        rows = (await self._session.scalars(stmt)).all()
        for row in rows:
            row.is_read = True
            row.read_at = now()
        await self._session.flush()
        return len(rows)

    # -- lifecycle messages ---------------------------------------------- #
    async def welcome(self, user: User) -> None:
        await self.create(
            user,
            NotificationKind.WELCOME,
            "Добро пожаловать!",
            "Выберите тариф в приложении, оплатите его и получите конфигурацию автоматически.",
            send_telegram=True,
        )

    async def payment_success(self, user: User, *, plan_title: str, amount_kopeks: int) -> None:
        await self.create(
            user,
            NotificationKind.PAYMENT_SUCCESS,
            "Оплата получена",
            f"Тариф «{plan_title}» активирован. Конфигурация уже доступна в разделе «Мой VPN».",
            payload={"amount_kopeks": amount_kopeks},
            send_telegram=True,
        )

    async def subscription_renewed(self, user: User, *, expires_at: dt.datetime) -> None:
        await self.create(
            user,
            NotificationKind.SUBSCRIPTION_RENEWED,
            "Подписка продлена",
            f"Новый срок действия до {expires_at:%d.%m.%Y}.",
            payload={"expires_at": expires_at.isoformat()},
            send_telegram=True,
        )

    async def expiring_soon(self, user: User, subscription: Subscription, days_left: int) -> None:
        await self.create(
            user,
            NotificationKind.SUBSCRIPTION_EXPIRING,
            f"Подписка истекает через {days_left} дн.",
            f"Тариф «{subscription.plan.title}» закончится {subscription.expires_at:%d.%m.%Y}. "
            "Продлите подписку, чтобы не потерять доступ.",
            payload={"subscription_id": str(subscription.id), "days_left": days_left},
            send_telegram=True,
        )

    async def expired(self, user: User, subscription: Subscription) -> None:
        await self.create(
            user,
            NotificationKind.SUBSCRIPTION_EXPIRED,
            "Подписка истекла",
            f"Доступ по тарифу «{subscription.plan.title}» отключён. Продлите подписку в приложении.",
            payload={"subscription_id": str(subscription.id)},
            send_telegram=True,
        )

    async def device_added(self, user: User, label: str) -> None:
        await self.create(
            user,
            NotificationKind.NEW_DEVICE,
            "Новое подключение",
            f"Добавлено устройство «{label}».",
            send_telegram=True,
        )

    async def device_revoked(self, user: User, label: str) -> None:
        await self.create(
            user,
            NotificationKind.DEVICE_REVOKED,
            "Подключение отключено",
            f"Устройство «{label}» больше не может подключаться.",
            send_telegram=True,
        )

    # -- reminders ------------------------------------------------------- #
    async def _claim_reminder(self, subscription: Subscription, days_left: int) -> bool:
        """Insert a reminder row; False if it already exists (already notified)."""
        self._session.add(
            ExpiryReminder(
                subscription_id=subscription.id,
                user_id=subscription.user_id,
                days_left=days_left,
            )
        )
        try:
            await self._session.flush()
            return True
        except IntegrityError:
            await self._session.rollback()
            return False

    async def send_expiry_reminders(self, *, limit: int = 200) -> dict[str, int]:
        thresholds = sorted(set(worker_settings.expiry_notify_days), reverse=True)
        if not thresholds:
            return {"sent": 0, "skipped": 0}

        sent = 0
        skipped = 0
        horizon = max(thresholds)
        candidates = await self._session.scalars(
            select(Subscription)
            .where(
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.expires_at.is_not(None),
                Subscription.expires_at > now(),
                Subscription.expires_at <= now() + dt.timedelta(days=horizon),
            )
            .limit(limit)
        )

        for subscription in candidates.unique().all():
            days_left = (subscription.expires_at - now()).days  # type: ignore[operator]
            matched = next((t for t in thresholds if days_left <= t), None)
            if matched is None:
                continue
            if not await self._claim_reminder(subscription, matched):
                skipped += 1
                continue
            if subscription.user.is_banned:
                continue
            await self.expiring_soon(subscription.user, subscription, matched)
            sent += 1

        if sent or skipped:
            log.info("notifications.reminders", sent=sent, skipped=skipped)
        return {"sent": sent, "skipped": skipped}

    async def notify_expired(self, subscriptions: list[Subscription]) -> int:
        count = 0
        for subscription in subscriptions:
            if subscription.user.is_banned:
                continue
            if not await self._claim_reminder(subscription, -1):
                continue
            await self.expired(subscription.user, subscription)
            count += 1
        return count

    def format_amount(self, kopeks: int, currency: str = "RUB") -> str:
        return format_money(kopeks, currency)
