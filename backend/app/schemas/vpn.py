"""VPN-related schemas: clients, links, servers, health."""

from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.enums import ClientStatus, HealthStatus
from app.schemas.common import ORMModel


class ClientRead(ORMModel):
    id: UUID
    uuid: UUID
    email: str
    label: str | None = None
    status: ClientStatus
    is_primary: bool = False
    server_id: UUID
    server_name: str | None = None
    created_at: dt.datetime
    last_synced_at: dt.datetime | None = None
    disabled_reason: str | None = None


class ClientLinksRead(BaseModel):
    client_id: str
    label: str
    link: str
    base64_link: str
    qr_payload: str
    deep_links: dict[str, str] = Field(default_factory=dict)
    host: str
    port: int
    server_name: str
    protocol: str = "vless-reality"
    flow: str = "xtls-rprx-vision"


class ClientWithLinks(ClientRead):
    links: ClientLinksRead | None = None


class CreateClientRequest(BaseModel):
    label: str | None = Field(None, max_length=64)
    make_primary: bool = False


class DeviceLimitRead(BaseModel):
    limit: int
    used: int
    remaining: int | None = None


class VpnStateRead(BaseModel):
    """Everything the 'My VPN' screen needs in a single request."""

    has_access: bool = False
    subscription: dict[str, Any] | None = None
    primary_client: ClientWithLinks | None = None
    clients: list[ClientRead] = Field(default_factory=list)
    device_limit: DeviceLimitRead
    server: dict[str, Any] | None = None
    # Config exists but is not live on the node yet — the UI shows "activating".
    sync_pending: bool = False
    instructions_url: str | None = None


class ServerRead(ORMModel):
    id: UUID
    name: str
    is_active: bool
    weight: int
    max_clients: int
    host: str
    ssh_port: int
    ssh_user: str
    public_host: str
    public_port: int
    xray_config_path: str
    xray_service_name: str
    reality_public_key: str | None = None
    reality_short_id: str | None = None
    reality_target: str
    reality_server_names: str
    reality_fingerprint: str
    last_check_status: HealthStatus
    last_check_error: str | None = None
    last_checked_at: dt.datetime | None = None
    xray_synced_at: dt.datetime | None = None
    note: str | None = None


class ServerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    host: str = Field(..., min_length=1, max_length=255)
    ssh_port: int = 22
    ssh_user: str = "root"
    ssh_key: str = Field(..., min_length=20, description="PEM private key")
    ssh_passphrase: str | None = None
    ssh_host_key_sha256: str | None = Field(None, max_length=128)
    public_host: str = Field(..., min_length=1, max_length=255)
    public_port: int = 443
    is_active: bool = True
    weight: int = 100
    max_clients: int = 0
    xray_config_path: str = "/usr/local/etc/xray/config.json"
    xray_service_name: str = "xray"
    xray_inbound_tag: str = "inbound-vless"
    reload_mode: str = "restart"
    reality_private_key: str | None = None
    reality_target: str = "www.microsoft.com:443"
    reality_server_names: list[str] = Field(default_factory=lambda: ["www.microsoft.com"])
    reality_short_id: str | None = None
    reality_fingerprint: str = "chrome"
    note: str | None = None


class ServerUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    weight: int | None = None
    max_clients: int | None = None
    host: str | None = None
    ssh_port: int | None = None
    ssh_user: str | None = None
    ssh_key: str | None = None
    ssh_passphrase: str | None = None
    ssh_host_key_sha256: str | None = None
    public_host: str | None = None
    public_port: int | None = None
    xray_config_path: str | None = None
    xray_service_name: str | None = None
    reload_mode: str | None = None
    reality_private_key: str | None = None
    reality_target: str | None = None
    reality_server_names: list[str] | None = None
    reality_short_id: str | None = None
    reality_fingerprint: str | None = None
    note: str | None = None


class ServerWithStats(ServerRead):
    clients_total: int = 0
    clients_active: int = 0


class HealthRead(BaseModel):
    status: HealthStatus
    ok: bool
    error: str | None = None
    client_count: int = 0
    checked_at: dt.datetime
    checks: dict[str, Any] = Field(default_factory=dict)


class SyncRequest(BaseModel):
    force: bool = False
    push: bool = True


class SyncResponse(BaseModel):
    ok: bool = True
    results: list[dict[str, Any]] = Field(default_factory=list)


class HostKeyProbe(BaseModel):
    server_id: UUID | None = None


class HostKeyRead(BaseModel):
    fingerprint: str
    host: str
    port: int
    pinned: bool
