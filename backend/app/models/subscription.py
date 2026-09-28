"""Subscription = paid access window for a user on a specific server."""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import SubscriptionStatus
from app.models.base import GUID, Base, TimestampMixin, TZDateTime, UUIDPrimaryKeyMixin, enum_column

if TYPE_CHECKING:
    from app.models.payment import Payment
    from app.models.plan import Plan
    from app.models.server import VpnServer
    from app.models.user import User
    from app.models.vpn_client import VpnClient


class Subscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "plan_id", "status", name="uq_subscription_user_plan_status"),)

    user_id: Mapped[uuid_lib.UUID] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[uuid_lib.UUID] = mapped_column(
        GUID(), ForeignKey("plans.id", ondelete="RESTRICT"), index=True
    )
    server_id: Mapped[uuid_lib.UUID | None] = mapped_column(
        GUID(), ForeignKey("vpn_servers.id", ondelete="SET NULL"), index=True
    )

    status: Mapped[SubscriptionStatus] = mapped_column(
        enum_column(SubscriptionStatus), default=SubscriptionStatus.PENDING, nullable=False, index=True
    )

    started_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime())
    expires_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime(), index=True)
    ended_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime())

    price_paid_kopeks: Mapped[int | None] = mapped_column(Integer)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cancelled_by_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 0 = без лимита устройств
    device_limit: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255))

    user: Mapped[User] = relationship(back_populates="subscriptions", lazy="selectin")
    plan: Mapped[Plan] = relationship(back_populates="subscriptions", lazy="selectin")
    server: Mapped[VpnServer | None] = relationship(back_populates="subscriptions", lazy="selectin")
    clients: Mapped[list[VpnClient]] = relationship(
        back_populates="subscription", cascade="all, delete-orphan", lazy="selectin"
    )
    payments: Mapped[list[Payment]] = relationship(back_populates="subscription", lazy="noload")

    # ------------------------------------------------------------------
    @property
    def is_expired(self) -> bool:
        return bool(self.expires_at and self.expires_at <= dt.datetime.now(dt.UTC))

    @property
    def is_usable(self) -> bool:
        return self.status == SubscriptionStatus.ACTIVE and not self.is_expired

    @property
    def days_left(self) -> int:
        if not self.expires_at:
            return 0
        return max(0, (self.expires_at - dt.datetime.now(dt.UTC)).days)

    @property
    def total_days(self) -> int:
        if not (self.started_at and self.expires_at):
            return 0
        return max(1, (self.expires_at - self.started_at).days)

    @property
    def progress_percent(self) -> int:
        """0..100 — how much of the paid period is left (UI progress ring)."""
        if not (self.started_at and self.expires_at):
            return 0
        total = (self.expires_at - self.started_at).total_seconds()
        if total <= 0:
            return 0
        left = (self.expires_at - dt.datetime.now(dt.UTC)).total_seconds()
        return int(max(0, min(100, left / total * 100)))

    def can_add_device(self, current: int) -> bool:
        return self.device_limit <= 0 or current < self.device_limit

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Subscription {self.id} user={self.user_id} {self.status}>"


class SubscriptionEvent(Base):
    """Audit trail: every state change of a subscription."""

    __tablename__ = "subscription_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    subscription_id: Mapped[uuid_lib.UUID] = mapped_column(
        GUID(), ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor: Mapped[str] = mapped_column(String(32), default="system", nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), server_default=func.now(), nullable=False, index=True
    )
