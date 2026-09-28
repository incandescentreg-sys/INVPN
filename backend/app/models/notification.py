"""Outgoing notifications and a dedup table for expiry reminders."""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.enums import NotificationChannel, NotificationKind
from app.models.base import GUID, JSON, Base, TimestampMixin, TZDateTime, UUIDPrimaryKeyMixin, enum_column


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[uuid_lib.UUID] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[NotificationKind] = mapped_column(
        enum_column(NotificationKind), nullable=False, index=True
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        enum_column(NotificationChannel), default=NotificationChannel.WEBAPP, nullable=False
    )
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sent_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime())
    read_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime())
    error: Mapped[str | None] = mapped_column(String(512))


class ExpiryReminder(Base):
    """Ensures we notify a user about a given subscription only once per threshold."""

    __tablename__ = "expiry_reminders"
    __table_args__ = (UniqueConstraint("subscription_id", "days_left", name="uq_reminder_sub_days"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    subscription_id: Mapped[uuid_lib.UUID] = mapped_column(
        GUID(), ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid_lib.UUID] = mapped_column(GUID(), ForeignKey("users.id", ondelete="CASCADE"))
    days_left: Mapped[int] = mapped_column(Integer, nullable=False)
    sent_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), server_default=func.now(), nullable=False
    )
