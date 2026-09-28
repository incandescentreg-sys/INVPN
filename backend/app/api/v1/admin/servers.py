"""Admin: VPN servers, Xray sync and health."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import AdminUser, ServerSvc, VpnSvc
from app.logging_config import get_logger
from app.schemas.common import Message
from app.schemas.vpn import (
    HealthRead,
    ServerCreate,
    ServerRead,
    ServerUpdate,
    ServerWithStats,
    SyncResponse,
)
from app.utils.exceptions import VpnError
from app.utils.ids import to_uuid
from app.vpn.manager import ServerEndpoint, XrayManager
from app.vpn.ssh import probe_host_key

log = get_logger(__name__)
router = APIRouter(prefix="/admin/servers", tags=["admin"])


@router.get("", response_model=list[ServerWithStats])
async def list_servers(admin: AdminUser, servers: ServerSvc) -> list[ServerWithStats]:
    result: list[ServerWithStats] = []
    for server in await servers.list_all():
        total = await servers.client_count(server.id)
        active = await servers.active_client_count(server.id)
        result.append(
            ServerWithStats(
                **ServerRead.model_validate(server).model_dump(),
                clients_total=total,
                clients_active=active,
            )
        )
    return result

@router.post("", response_model=ServerRead, status_code=201)
async def create_server(payload: ServerCreate, admin: AdminUser, servers: ServerSvc) -> ServerRead:
    try:
        server = await servers.create(**payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    return ServerRead.model_validate(server)

@router.patch("/{server_id}", response_model=ServerRead)
async def update_server(
    server_id: str, payload: ServerUpdate, admin: AdminUser, servers: ServerSvc
) -> ServerRead:
    data = payload.model_dump(exclude_none=True)
    if "reality_server_names" in data:
        data["reality_server_names"] = ",".join(data["reality_server_names"])
    server = await servers.update(to_uuid(server_id), **data)
    return ServerRead.model_validate(server)

@router.delete("/{server_id}", response_model=Message)
async def delete_server(server_id: str, admin: AdminUser, servers: ServerSvc) -> Message:
    ok = await servers.delete(to_uuid(server_id))
    return Message(detail="Сервер удалён" if ok else "Сервер не найден")

@router.post("/{server_id}/sync", response_model=dict)
async def sync_server(
    server_id: str, admin: AdminUser, servers: ServerSvc, vpn: VpnSvc, force: bool = Query(False)
) -> dict:
    server = await servers.get(to_uuid(server_id))
    return await vpn.sync_server(server, force=force)

@router.post("/sync", response_model=SyncResponse)
async def sync_all(admin: AdminUser, vpn: VpnSvc, force: bool = Query(False)) -> SyncResponse:
    results = await vpn.sync_all_servers(force=force)
    return SyncResponse(ok=all(r.get("ok") for r in results), results=results)

@router.get("/{server_id}/health", response_model=HealthRead)
async def server_health(
    server_id: str, admin: AdminUser, servers: ServerSvc, vpn: VpnSvc
) -> HealthRead:
    server = await servers.get(to_uuid(server_id))
    report = await vpn.check_server(server)
    return HealthRead(**report.as_dict())

@router.get("/health/all", response_model=list[dict])
async def all_health(admin: AdminUser, vpn: VpnSvc) -> list[dict]:
    return await vpn.check_all_servers()

@router.get("/{server_id}/config", response_model=dict)
async def server_config(
    server_id: str, admin: AdminUser, servers: ServerSvc
) -> dict:
    """Current Xray config with private keys and client UUIDs stripped."""
    server = await servers.get(to_uuid(server_id))
    manager = XrayManager(ServerEndpoint.from_model(server))
    return await manager.get_config_public()

@router.get("/{server_id}/host-key", response_model=dict)
async def server_host_key(
    server_id: str, admin: AdminUser, servers: ServerSvc
) -> dict:
    """Read the node's host key so it can be pinned in SERVER_SSH_HOST_KEY_SHA256."""
    server = await servers.get(to_uuid(server_id))
    endpoint = ServerEndpoint.from_model(server)
    try:
        fingerprint = await probe_host_key(endpoint.ssh_settings())
    except VpnError as exc:
        raise ValueError(str(exc)) from exc
    return {
        "fingerprint": fingerprint,
        "host": endpoint.host,
        "port": endpoint.ssh_port,
        "pinned": bool(endpoint.ssh_host_key_sha256),
    }