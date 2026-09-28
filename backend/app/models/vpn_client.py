"""A single Xray client (one VLESS UUID = one device)."""

from __future__ import annotations

import datetime as dt
import uuid as uuid_lib
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import ClientStatus
from app.models.base import GUID, Base, TimestampMixin, TZDateTime, UUIDPrimaryKeyMixin, enum_column

if TYPE_CHECKING:
    from app.models.server import VpnServer
    from app.models.subscription import Subscription
    from app.models.user import User


class VpnClient(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "vpn_clients"
    __table_args__ = (UniqueConstraint("server_id", "uuid", name="uq_client_server_uuid"),)

    user_id: Mapped[uuid_lib.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    subscription_id: Mapped[uuid_lib.UUID] = mapped_column(
        GUID(), ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True
    )
    server_id: Mapped[uuid_lib.UUID] = mapped_column(
        GUID(), ForeignKey("vpn_servers.id", ondelete="CASCADE"), index=True
    )

    # The VLESS UUID is the identity inside Xray — it must be unique per server.
    uuid: Mapped[uuid_lib.UUID] = mapped_column(GUID(), nullable=False, index=True)
    # Xray client "email" — the human readable label in xray logs
    email: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(64))
    flow: Mapped[str] = mapped_column(String(32), default="xtls-rprx-vision", nullable=False)

    status: Mapped[ClientStatus] = mapped_column(
        enum_column(ClientStatus), default=ClientStatus.PENDING, nullable=False, index=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(512))
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime())
    disabled_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime())
    disabled_reason: Mapped[str | None] = mapped_column(String(255))
    last_seen_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime())

    subscription: Mapped[Subscription] = relationship(back_populates="clients", lazy="selectin")
    user: Mapped[User] = relationship(back_populates="vpn_clients", lazy="selectin")
    server: Mapped[VpnServer] = relationship(back_populates="clients", lazy="selectin")

    @property
    def is_in_xray(self) -> bool:
        return self.status == ClientStatus.ACTIVE

    @property
    def needs_sync(self) -> bool:
        return self.status in (ClientStatus.PENDING, ClientStatus.ERROR)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<VpnClient {self.email} {self.status}>"
