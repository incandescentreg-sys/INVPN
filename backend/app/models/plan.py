"""Tariff / plan catalogue. Prices live in the DB, never in code."""

from __future__ import annotations

import uuid as uuid_lib
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import GUID, JSON, Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.payment import Payment
    from app.models.subscription import Subscription


class Plan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "plans"
    __table_args__ = (CheckConstraint("price_kopeks >= 0", name="price_kopeks_non_negative"),)

    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    price_kopeks: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="RUB", nullable=False)

    # presentation
    features: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    badge: Mapped[str | None] = mapped_column(String(32))
    is_popular: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    # Optional: pin this tariff to a specific node. NULL = auto-select.
    server_id: Mapped[uuid_lib.UUID | None] = mapped_column(
        GUID(), ForeignKey("vpn_servers.id", ondelete="SET NULL")
    )

    subscriptions: Mapped[list[Subscription]] = relationship(back_populates="plan", lazy="noload")
    payments: Mapped[list[Payment]] = relationship(back_populates="plan", lazy="noload")

    @property
    def price_rub(self) -> float:
        return self.price_kopeks / 100

    @property
    def price_per_day_kopeks(self) -> int:
        return round(self.price_kopeks / self.days) if self.days else 0

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Plan {self.code} {self.days}d {self.price_kopeks}k>"


def plan_payload(
    *,
    code: str,
    title: str,
    days: int,
    price_kopeks: int,
    currency: str = "RUB",
    description: str | None = None,
    features: list[str] | None = None,
    badge: str | None = None,
    is_popular: bool = False,
    sort_order: int = 0,
) -> dict[str, Any]:
    """Helper for seeding plans from .env values."""
    return {
        "code": code,
        "title": title,
        "days": days,
        "price_kopeks": price_kopeks,
        "currency": currency,
        "description": description,
        "features": features or [],
        "badge": badge,
        "is_popular": is_popular,
        "sort_order": sort_order,
    }
