"""Telegram user account."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import PaymentStatus, SubscriptionStatus
from app.models.base import Base, TimestampMixin, TZDateTime, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.payment import Payment
    from app.models.subscription import Subscription
    from app.models.vpn_client import VpnClient


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    language_code: Mapped[str | None] = mapped_column(String(8))
    photo_url: Mapped[str | None] = mapped_column(String(512))
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # moderation
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    ban_reason: Mapped[str | None] = mapped_column(String(255))
    banned_at: Mapped[datetime | None] = mapped_column(TZDateTime())

    last_seen_at: Mapped[datetime | None] = mapped_column(TZDateTime(), index=True)
    marketing_opt_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    payments: Mapped[list[Payment]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="noload"
    )
    vpn_clients: Mapped[list[VpnClient]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="noload"
    )

    @property
    def display_name(self) -> str:
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) or (f"@{self.username}" if self.username else f"user-{self.telegram_id}")

    def active_subscription(self) -> Subscription | None:
        active = [
            s
            for s in self.subscriptions
            if s.status == SubscriptionStatus.ACTIVE and not s.is_expired
        ]
        if not active:
            return None
        return max(active, key=lambda s: s.expires_at or s.created_at)

    def latest_subscription(self) -> Subscription | None:
        if not self.subscriptions:
            return None
        return max(self.subscriptions, key=lambda s: s.created_at)

    def successful_payments_total(self) -> int:
        return sum(
            p.amount_kopeks - p.refunded_kopeks
            for p in self.payments
            if p.status in (PaymentStatus.SUCCEEDED, PaymentStatus.PARTIALLY_REFUNDED)
        )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.telegram_id} {self.username!r}>"
