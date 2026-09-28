"""Subscription lifecycle: activate after payment, renew, expire, revoke."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import SubscriptionStatus
from app.logging_config import get_logger
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User
from app.repositories.plan import PlanRepository
from app.repositories.server import ServerRepository
from app.repositories.subscription import SubscriptionRepository
from app.utils.exceptions import ConflictError, NotFoundError
from app.utils.time import add_days, now

log = get_logger(__name__)


class SubscriptionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._subs = SubscriptionRepository(session)
        self._plans = PlanRepository(session)
        self._servers = ServerRepository(session)

    # -- reads ---------------------------------------------------------- #
    async def get(self, subscription_id: uuid.UUID) -> Subscription:
        subscription = await self._subs.get(subscription_id)
        if subscription is None:
            raise NotFoundError("Подписка не найдена")
        return subscription

    async def list_for_user(self, user_id: uuid.UUID) -> list[Subscription]:
        return list(await self._subs.list_by_user(user_id))

    async def list_all(
        self,
        *,
        user_id: uuid.UUID | None = None,
        status: SubscriptionStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Subscription]:
        return list(await self._subs.list_all(user_id=user_id, status=status, limit=limit, offset=offset))

    async def count(self, *, status: SubscriptionStatus | None = None) -> int:
        return await self._subs.count(status=status)

    async def active_for_user(self, user_id: uuid.UUID) -> Subscription | None:
        return await self._subs.active_for_user(user_id)

    async def current(self, user_id: uuid.UUID) -> Subscription | None:
        """Active subscription, falling back to the most recent one for the UI."""
        active = await self.active_for_user(user_id)
        if active is not None:
            return active
        history = await self._subs.list_by_user(user_id, limit=1)
        return history[0] if history else None

    # -- writes --------------------------------------------------------- #
    async def create_pending(
        self, *, user: User, plan: Plan, amount_kopeks: int, server_id: uuid.UUID | None = None
    ) -> Subscription:
        """Allocate a PENDING subscription; reused if one already exists."""
        existing = await self._subs.pending_for_user_plan(user.id, plan.id)
        if existing is not None:
            if server_id and not existing.server_id:
                existing.server_id = server_id
                await self._session.flush()
            return existing

        return await self._subs.create(
            user_id=user.id,
            plan_id=plan.id,
            server_id=server_id or plan.server_id,
            status=SubscriptionStatus.PENDING,
            price_paid_kopeks=amount_kopeks,
            device_limit=0,  # unlimited devices by default
        )

    async def activate(self, subscription: Subscription, *, server_id: uuid.UUID | None = None) -> Subscription:
        """Start the paid period. Renewing an active subscription extends it."""
        now_dt = now()
        if server_id is not None and subscription.server_id != server_id:
            subscription.server_id = server_id

        if subscription.started_at is None:
            subscription.started_at = now_dt
            subscription.expires_at = add_days(now_dt, subscription.plan.days)
        else:
            subscription.expires_at = add_days(
                subscription.expires_at or now_dt, subscription.plan.days
            )

        await self._subs.set_status(
            subscription, SubscriptionStatus.ACTIVE, actor="payment", reason="payment_confirmed"
        )
        log.info(
            "subscription.activated",
            subscription_id=str(subscription.id),
            expires_at=subscription.expires_at.isoformat() if subscription.expires_at else None,
        )
        return subscription

    async def extend(self, subscription: Subscription, days: int | None = None) -> Subscription:
        await self._subs.extend(subscription, days or subscription.plan.days)
        return subscription

    async def grant(
        self, *, user: User, plan: Plan, days: int, amount_kopeks: int = 0, actor: str = "admin"
    ) -> Subscription:
        """Admin gift / compensation."""
        subscription = await self._subs.create(
            user_id=user.id,
            plan_id=plan.id,
            server_id=plan.server_id,
            status=SubscriptionStatus.ACTIVE,
            started_at=now(),
            expires_at=add_days(now(), days),
            price_paid_kopeks=amount_kopeks,
        )
        await self._subs.set_status(subscription, SubscriptionStatus.ACTIVE, actor=actor, reason="granted")
        log.info("subscription.granted", subscription_id=str(subscription.id), days=days)
        return subscription

    async def suspend(self, subscription: Subscription, *, actor: str = "admin", reason: str = "") -> Subscription:
        await self._subs.set_status(
            subscription, SubscriptionStatus.SUSPENDED, actor=actor, reason=reason or None
        )
        return subscription

    async def reactivate(self, subscription: Subscription, *, actor: str = "admin") -> Subscription:
        """Un-suspend without touching the expiry date."""
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.ended_at = None
        await self._session.flush()
        log.info("subscription.reactivated", subscription_id=str(subscription.id), actor=actor)
        return subscription

    async def cancel(self, subscription: Subscription, *, actor: str = "user") -> Subscription:
        subscription.cancelled_by_user = actor == "user"
        await self._subs.set_status(subscription, SubscriptionStatus.CANCELLED, actor=actor, reason="cancelled")
        return subscription

    async def extend_expiry(self, subscription: Subscription, *, days: int) -> Subscription:
        """Shift the expiry date (admin action, may be negative)."""
        base = subscription.expires_at or now()
        subscription.expires_at = base + dt.timedelta(days=days)
        if subscription.expires_at <= now() and subscription.status == SubscriptionStatus.ACTIVE:
            await self._subs.set_status(
                subscription, SubscriptionStatus.EXPIRED, actor="admin", reason="expiry_moved"
            )
        await self._session.flush()
        return subscription

    async def set_expiry(self, subscription: Subscription, *, expires_at: dt.datetime) -> Subscription:
        subscription.expires_at = expires_at
        if expires_at > now() and subscription.status == SubscriptionStatus.EXPIRED:
            subscription.status = SubscriptionStatus.ACTIVE
            subscription.ended_at = None
        await self._session.flush()
        return subscription

    # -- expiry sweep --------------------------------------------------- #
    async def expire_due(self, *, limit: int = 200) -> list[Subscription]:
        """Mark overdue subscriptions as expired. Xray cleanup runs separately."""
        due = await self._subs.list_due_to_expire(limit=limit)
        for subscription in due:
            await self._subs.set_status(
                subscription, SubscriptionStatus.EXPIRED, actor="system", reason="expiry_reached"
            )
        if due:
            log.info("subscription.expired", count=len(due))
        return list(due)

    async def expiring_soon(self, *, within_days: int) -> list[Subscription]:
        return list(await self._subs.list_expiring_soon(within_days=within_days))

    # -- assignment ----------------------------------------------------- #
    async def assign_server(self, subscription: Subscription, server_id: uuid.UUID | None) -> Subscription:
        if server_id is not None:
            server = await self._servers.get(server_id)
            if server is None:
                raise NotFoundError("Сервер не найден")
        subscription.server_id = server_id
        await self._session.flush()
        return subscription

    async def require_active(self, subscription: Subscription) -> Subscription:
        if not subscription.is_usable:
            raise ConflictError(
                "Подписка не активна или истекла. Продлите подписку, чтобы продолжить пользоваться VPN."
            )
        return subscription

    def summary(self, subscription: Subscription) -> dict[str, Any]:
        return {
            "id": str(subscription.id),
            "status": str(subscription.status),
            "plan_title": subscription.plan.title,
            "plan_days": subscription.plan.days,
            "price_kopeks": subscription.price_paid_kopeks,
            "started_at": subscription.started_at,
            "expires_at": subscription.expires_at,
            "days_left": subscription.days_left,
            "progress_percent": subscription.progress_percent,
            "is_expired": subscription.is_expired,
            "server_id": str(subscription.server_id) if subscription.server_id else None,
            "server_name": subscription.server.name if subscription.server else None,
        }
