"""Payment record: created before redirect, confirmed by webhook or polling."""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import PaymentStatus
from app.models.base import GUID, JSON, Base, TimestampMixin, TZDateTime, UUIDPrimaryKeyMixin, enum_column

if TYPE_CHECKING:
    from app.models.plan import Plan
    from app.models.subscription import Subscription
    from app.models.user import User


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        # Guards against double-crediting when a webhook is retried.
        UniqueConstraint("provider", "provider_payment_id", name="uq_payment_provider_external_id"),
        # Lets a user pay once per order, even with a double-tap.
        UniqueConstraint("user_id", "idempotency_key", name="uq_payment_user_idempotency"),
        Index("ix_payment_status_created", "status", "created_at"),
    )

    user_id: Mapped[uuid_lib.UUID] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[uuid_lib.UUID | None] = mapped_column(GUID(), ForeignKey("plans.id", ondelete="SET NULL"))
    # Filled in once the payment is confirmed and a subscription exists.
    subscription_id: Mapped[uuid_lib.UUID | None] = mapped_column(
        GUID(), ForeignKey("subscriptions.id", ondelete="SET NULL"), index=True
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(128), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)

    amount_kopeks: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="RUB", nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[PaymentStatus] = mapped_column(
        enum_column(PaymentStatus), default=PaymentStatus.PENDING, nullable=False, index=True
    )

    confirmation_url: Mapped[str | None] = mapped_column(String(1024))
    paid_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime())
    failed_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime())
    refunded_kopeks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    provider_status: Mapped[str | None] = mapped_column(String(64))
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(String(512))

    user: Mapped[User] = relationship(back_populates="payments", lazy="selectin")
    plan: Mapped[Plan | None] = relationship(back_populates="payments", lazy="selectin")
    subscription: Mapped[Subscription | None] = relationship(back_populates="payments", lazy="noload")

    @property
    def amount_rub(self) -> float:
        return self.amount_kopeks / 100

    @property
    def is_paid(self) -> bool:
        return self.status == PaymentStatus.SUCCEEDED

    @property
    def is_final(self) -> bool:
        return self.status in {
            PaymentStatus.SUCCEEDED,
            PaymentStatus.FAILED,
            PaymentStatus.CANCELLED,
            PaymentStatus.REFUNDED,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Payment {self.id} {self.status} {self.amount_kopeks}k>"


class PaymentEvent(Base):
    """Raw provider events, kept for reconciliation and debugging."""

    __tablename__ = "payment_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    external_id: Mapped[str | None] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    signature_ok: Mapped[bool | None] = mapped_column()
    processed: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), server_default=func.now(), nullable=False, index=True
    )
