"""Subscription data access."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.enums import ClientStatus, SubscriptionStatus
from app.models.subscription import Subscription, SubscriptionEvent
from app.utils.time import now


class SubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _query(self) -> Select[tuple[Subscription]]:
        return select(Subscription).options(
            selectinload(Subscription.plan),
            selectinload(Subscription.server),
            selectinload(Subscription.clients),
        )

    async def get(self, subscription_id: uuid.UUID) -> Subscription | None:
        return await self._session.scalar(self._query().where(Subscription.id == subscription_id))

    async def get_for_update(self, subscription_id: uuid.UUID) -> Subscription | None:
        return await self._session.scalar(
            self._query().where(Subscription.id == subscription_id).with_for_update()
        )

    async def list_by_user(self, user_id: uuid.UUID, *, limit: int = 50) -> Sequence[Subscription]:
        stmt = (
            self._query()
            .where(Subscription.user_id == user_id)
            .order_by(Subscription.created_at.desc())
            .limit(limit)
        )
        return (await self._session.scalars(stmt)).unique().all()

    async def active_for_user(self, user_id: uuid.UUID) -> Subscription | None:
        stmt = (
            self._query()
            .where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
            .order_by(Subscription.expires_at.desc().nullslast())
            .limit(1)
        )
        return await self._session.scalar(stmt)

    async def pending_for_user_plan(
        self, user_id: uuid.UUID, plan_id: uuid.UUID
    ) -> Subscription | None:
        """A PENDING row for the same order must be reused, not duplicated."""
        stmt = self._query().where(
            Subscription.user_id == user_id,
            Subscription.plan_id == plan_id,
            Subscription.status == SubscriptionStatus.PENDING,
        )
        return await self._session.scalar(stmt)

    async def list_due_to_expire(self, *, before: dt.datetime | None = None, limit: int = 200) -> Sequence[Subscription]:
        """ACTIVE subscriptions that already passed `expires_at`."""
        cutoff = before or now()
        stmt = (
            self._query()
            .where(
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.expires_at.is_not(None),
                Subscription.expires_at <= cutoff,
            )
            .order_by(Subscription.expires_at)
            .limit(limit)
        )
        return (await self._session.scalars(stmt)).unique().all()

    async def list_expiring_soon(
        self, *, within_days: int, limit: int = 200
    ) -> Sequence[Subscription]:
        horizon = now() + dt.timedelta(days=within_days)
        stmt = (
            self._query()
            .where(
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.expires_at.is_not(None),
                Subscription.expires_at > now(),
                Subscription.expires_at <= horizon,
            )
            .limit(limit)
        )
        return (await self._session.scalars(stmt)).unique().all()

    async def list_all(
        self,
        *,
        user_id: uuid.UUID | None = None,
        status: SubscriptionStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Subscription]:
        stmt = self._query()
        if user_id:
            stmt = stmt.where(Subscription.user_id == user_id)
        if status:
            stmt = stmt.where(Subscription.status == status)
        stmt = stmt.order_by(Subscription.created_at.desc()).limit(limit).offset(offset)
        return (await self._session.scalars(stmt)).unique().all()

    async def count(self, *, status: SubscriptionStatus | None = None) -> int:
        stmt = select(func.count()).select_from(Subscription)
        if status:
            stmt = stmt.where(Subscription.status == status)
        return int(await self._session.scalar(stmt) or 0)

    # -- mutations ------------------------------------------------------- #
    async def create(self, **fields: object) -> Subscription:
        subscription = Subscription(**fields)  # type: ignore[arg-type]
        self._session.add(subscription)
        await self._session.flush()
        return subscription

    async def set_status(
        self,
        subscription: Subscription,
        new_status: SubscriptionStatus,
        *,
        actor: str = "system",
        reason: str | None = None,
    ) -> Subscription:
        old = subscription.status
        subscription.status = new_status
        if new_status in (SubscriptionStatus.EXPIRED, SubscriptionStatus.CANCELLED, SubscriptionStatus.SUSPENDED):
            subscription.ended_at = now()
        await self._session.flush()

        self._session.add(
            SubscriptionEvent(
                subscription_id=subscription.id,
                from_status=str(old),
                to_status=str(new_status),
                actor=actor,
                reason=reason,
            )
        )
        return subscription

    async def extend(self, subscription: Subscription, days: int) -> Subscription:
        """Renew from the current expiry date, or from now if already expired."""
        base = subscription.expires_at or now()
        if base <= now():
            base = now()
        subscription.expires_at = base + dt.timedelta(days=days)
        if subscription.status in (SubscriptionStatus.EXPIRED, SubscriptionStatus.CANCELLED):
            subscription.status = SubscriptionStatus.ACTIVE
            subscription.ended_at = None
        await self._session.flush()
        return subscription

    async def count_active_clients(self, subscription_id: uuid.UUID) -> int:
        from app.models.vpn_client import VpnClient

        stmt = (
            select(func.count())
            .select_from(VpnClient)
            .where(
                VpnClient.subscription_id == subscription_id,
                VpnClient.status != ClientStatus.DISABLED,
            )
        )
        return int(await self._session.scalar(stmt) or 0)
