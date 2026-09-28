"""Aggregated statistics for the admin dashboard."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ClientStatus, PaymentStatus, SubscriptionStatus
from app.models.payment import Payment
from app.models.subscription import Subscription
from app.models.user import User
from app.models.vpn_client import VpnClient
from app.repositories.payment import PaymentRepository
from app.repositories.server import ServerRepository
from app.utils.time import now


class StatsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._payments = PaymentRepository(session)
        self._servers = ServerRepository(session)

    async def dashboard(self) -> dict[str, Any]:
        users_total = int(await self._count(User) or 0)
        users_new_24h = int(
            await self._count(User, since=now() - dt.timedelta(hours=24)) or 0
        )
        users_new_7d = int(await self._count(User, since=now() - dt.timedelta(days=7)) or 0)

        active_subs = int(
            await self._count(Subscription, where=Subscription.status == SubscriptionStatus.ACTIVE) or 0
        )
        expired_subs = int(
            await self._count(Subscription, where=Subscription.status == SubscriptionStatus.EXPIRED) or 0
        )
        expiring_soon = int(
            await self._count(
                Subscription,
                where=(
                    (Subscription.status == SubscriptionStatus.ACTIVE)
                    & Subscription.expires_at.is_not(None)
                    & (Subscription.expires_at > now())
                    & (Subscription.expires_at <= now() + dt.timedelta(days=3))
                ),
            )
            or 0
        )

        revenue = await self._payments.revenue_total()
        revenue_30d = await self._payments.revenue_total(since=now() - dt.timedelta(days=30))
        clients_active = int(
            await self._count(VpnClient, where=VpnClient.status == ClientStatus.ACTIVE) or 0
        )
        clients_total = int(await self._count(VpnClient) or 0)
        pending = int(
            await self._count(Payment, where=Payment.status == PaymentStatus.PENDING) or 0
        )

        servers = await self._servers.list_all()

        return {
            "users": {
                "total": users_total,
                "new_24h": users_new_24h,
                "new_7d": users_new_7d,
            },
            "subscriptions": {
                "active": active_subs,
                "expired": expired_subs,
                "expiring_soon": expiring_soon,
            },
            "payments": {
                "revenue_kopeks": revenue["total_kopeks"],
                "successful": revenue["count"],
                "revenue_30d_kopeks": revenue_30d["total_kopeks"],
                "successful_30d": revenue_30d["count"],
                "pending": pending,
                "by_day": await self._payments.revenue_by_day(days=14),
            },
            "vpn": {
                "clients_active": clients_active,
                "clients_total": clients_total,
                "servers": [
                    {
                        "id": str(server.id),
                        "name": server.name,
                        "active": server.is_active,
                        "health": server.last_check_status,
                        "last_error": server.last_check_error,
                        "last_checked_at": server.last_checked_at.isoformat()
                        if server.last_checked_at
                        else None,
                    }
                    for server in servers
                ],
            },
        }

    async def _count(self, model: Any, *, where: Any = None, since: dt.datetime | None = None) -> int:
        stmt = select(func.count()).select_from(model)
        if where is not None:
            stmt = stmt.where(where)
        if since is not None:
            stmt = stmt.where(model.created_at >= since)
        return int(await self._session.scalar(stmt) or 0)
