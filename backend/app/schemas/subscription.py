"""Subscription schemas."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, Field

from app.enums import SubscriptionStatus
from app.schemas.common import ORMModel

if TYPE_CHECKING:
    from app.models.subscription import Subscription


class SubscriptionRead(ORMModel):
    id: UUID
    status: SubscriptionStatus
    plan_id: UUID | None
    plan_title: str
    plan_days: int
    days_left: int
    total_days: int
    progress_percent: int
    started_at: dt.datetime | None = None
    expires_at: dt.datetime | None = None
    price_paid_kopeks: int | None = None
    is_expired: bool = False
    server_id: UUID | None = None
    server_name: str | None = None
    device_limit: int = 0
    created_at: dt.datetime

    @classmethod
    def from_model(cls, subscription: Subscription) -> SubscriptionRead:
        plan = subscription.plan
        server = subscription.server
        return cls(
            id=subscription.id,
            status=subscription.status,
            plan_id=subscription.plan_id,
            plan_title=plan.title if plan else "",
            plan_days=plan.days if plan else 0,
            days_left=subscription.days_left,
            total_days=subscription.total_days,
            progress_percent=subscription.progress_percent,
            started_at=subscription.started_at,
            expires_at=subscription.expires_at,
            price_paid_kopeks=subscription.price_paid_kopeks,
            is_expired=subscription.is_expired,
            server_id=subscription.server_id,
            server_name=server.name if server else None,
            device_limit=subscription.device_limit,
            created_at=subscription.created_at,
        )


class SubscriptionListRead(BaseModel):
    current: SubscriptionRead | None = None
    history: list[SubscriptionRead] = Field(default_factory=list)


class ExtendDaysRequest(BaseModel):
    days: int = Field(..., ge=1, le=3650)


class SetExpiryRequest(BaseModel):
    expires_at: dt.datetime
