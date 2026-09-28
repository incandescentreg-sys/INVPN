"""VPN node: SSH endpoint + Xray/REALITY parameters.

Several rows are supported so the service can be extended to more VPS servers.
Row #1 is normally seeded from the flat SERVER_* / XRAY_* / REALITY_* env vars.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.enums import HealthStatus
from app.models.base import Base, TimestampMixin, TZDateTime, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.subscription import Subscription
    from app.models.vpn_client import VpnClient


class VpnServer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "vpn_servers"

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    weight: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    # 0 = unlimited device slots; -1 = unlimited
    max_clients: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    # --- SSH ---
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    ssh_port: Mapped[int] = mapped_column(Integer, default=22, nullable=False)
    ssh_user: Mapped[str] = mapped_column(String(64), default="root", nullable=False)
    ssh_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    ssh_key_passphrase_encrypted: Mapped[str | None] = mapped_column(Text)
    ssh_host_key_sha256: Mapped[str | None] = mapped_column(String(128))

    # --- public endpoint (what goes into the client link) ---
    public_host: Mapped[str] = mapped_column(String(255), nullable=False)
    public_port: Mapped[int] = mapped_column(Integer, default=443, nullable=False)

    # --- Xray ---
    xray_config_path: Mapped[str] = mapped_column(
        String(512), default="/usr/local/etc/xray/config.json", nullable=False
    )
    xray_service_name: Mapped[str] = mapped_column(String(64), default="xray", nullable=False)
    xray_inbound_tag: Mapped[str] = mapped_column(String(64), default="inbound-vless", nullable=False)
    xray_binary: Mapped[str] = mapped_column(String(64), default="xray", nullable=False)
    reload_mode: Mapped[str] = mapped_column(String(16), default="restart", nullable=False)

    # --- REALITY ---
    reality_private_key_encrypted: Mapped[str | None] = mapped_column(Text)
    reality_public_key: Mapped[str | None] = mapped_column(String(128))
    reality_target: Mapped[str] = mapped_column(String(255), default="www.microsoft.com:443", nullable=False)
    reality_server_names: Mapped[str] = mapped_column(Text, default="www.microsoft.com", nullable=False)
    reality_short_id: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    reality_fingerprint: Mapped[str] = mapped_column(String(16), default="chrome", nullable=False)

    # --- health ---
    last_checked_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime(), nullable=True)
    last_check_status: Mapped[str] = mapped_column(String(16), default=HealthStatus.UNKNOWN, nullable=False)
    last_check_error: Mapped[str | None] = mapped_column(Text)
    xray_synced_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime(), nullable=True)

    subscriptions: Mapped[list[Subscription]] = relationship(back_populates="server", lazy="noload")
    clients: Mapped[list[VpnClient]] = relationship(
        back_populates="server", cascade="all, delete-orphan", lazy="noload"
    )

    # ------------------------------------------------------------------
    @property
    def server_names(self) -> list[str]:
        return [s.strip() for s in self.reality_server_names.split(",") if s.strip()]

    @property
    def is_healthy(self) -> bool:
        return self.last_check_status == HealthStatus.UP

    def has_capacity(self, current_clients: int) -> bool:
        return self.max_clients <= 0 or current_clients < self.max_clients

    def __repr__(self) -> str:  # pragma: no cover
        return f"<VpnServer {self.name} {self.host}:{self.ssh_port}>"
