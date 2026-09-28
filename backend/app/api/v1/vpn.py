"""VPN endpoints: state, devices, links, sync and health."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from app.api.deps import ActiveUser, ServerSvc, SubscriptionSvc, VpnSvc
from app.config import telegram_settings
from app.enums import ClientStatus
from app.logging_config import get_logger
from app.schemas.common import Message
from app.schemas.vpn import (
    ClientLinksRead,
    ClientRead,
    ClientWithLinks,
    CreateClientRequest,
    DeviceLimitRead,
    VpnStateRead,
)
from app.utils.exceptions import ConflictError, NotFoundError
from app.utils.ids import to_uuid

if TYPE_CHECKING:
    from app.models.vpn_client import VpnClient
    from app.services.vpn import ClientLinks

log = get_logger(__name__)
router = APIRouter(prefix="/vpn", tags=["vpn"])


def _links_of(client: VpnClient, links: ClientLinks) -> ClientLinksRead:
    return ClientLinksRead(
        client_id=str(client.id),
        label=links.label,
        link=links.link,
        base64_link=links.base64_link,
        qr_payload=links.qr_payload,
        deep_links=links.deep_links,
        host=links.host,
        port=links.port,
        server_name=links.server_name,
    )


@router.get("/state", response_model=VpnStateRead)
async def vpn_state(
    user: ActiveUser, subscriptions: SubscriptionSvc, servers: ServerSvc, vpn: VpnSvc
) -> VpnStateRead:
    """Single call that fills the whole 'Мой VPN' screen."""
    subscription = await subscriptions.current(user.id)
    clients = list(subscription.clients) if subscription else []

    # A paid user must see their config even while the node is unreachable:
    # the client row exists and only the Xray push is pending. So the "primary"
    # config is any enabled device, preferring the one already pushed.
    enabled = [c for c in clients if c.status != ClientStatus.DISABLED]
    active = [c for c in enabled if c.status == ClientStatus.ACTIVE]
    limit = subscription.device_limit if subscription else 0

    primary = (
        next((c for c in enabled if c.is_primary), None)
        or (active[0] if active else (enabled[0] if enabled else None))
    )
    primary_with_links: ClientWithLinks | None = None
    if primary is not None:
        links = await vpn.build_links(primary)
        primary_with_links = ClientWithLinks(
            **ClientRead.model_validate(primary).model_dump(),
            links=_links_of(primary, links),
        )

    server_info = None
    if subscription is not None and subscription.server is not None:
        server = subscription.server
        server_info = {
            "id": str(server.id),
            "name": server.name,
            "host": server.public_host,
            "port": server.public_port,
            "healthy": server.is_healthy,
        }

    base = telegram_settings.webapp_url.rstrip("/")
    return VpnStateRead(
        has_access=bool(subscription and subscription.is_usable and primary_with_links),
        subscription=subscriptions.summary(subscription) if subscription else None,
        primary_client=primary_with_links,
        clients=[ClientRead.model_validate(c) for c in clients],
        device_limit=DeviceLimitRead(
            limit=limit, used=len(enabled), remaining=(limit - len(enabled)) if limit > 0 else None
        ),
        server=server_info,
        # True when a config exists but is not yet live on the node.
        sync_pending=any(c.status != ClientStatus.ACTIVE for c in enabled),
        instructions_url=f"{base}/instructions" if base else "/instructions",
    )


@router.get("/clients", response_model=list[ClientRead])
async def list_clients(user: ActiveUser, subscriptions: SubscriptionSvc) -> list[ClientRead]:
    subscription = await subscriptions.current(user.id)
    if subscription is None:
        return []
    return [ClientRead.model_validate(c) for c in subscription.clients]


@router.post("/clients", response_model=ClientWithLinks, status_code=201)
async def add_device(
    payload: CreateClientRequest,
    user: ActiveUser,
    subscriptions: SubscriptionSvc,
    servers: ServerSvc,
    vpn: VpnSvc,
) -> ClientWithLinks:
    """Issue an extra device config and push it to Xray immediately."""
    subscription = await subscriptions.current(user.id)
    if subscription is None:
        raise NotFoundError("Нет активной подписки")
    await subscriptions.require_active(subscription)

    server = subscription.server or await servers.pick()
    if server is None:
        raise ConflictError("Нет доступных VPN-серверов")

    client = await vpn.create_client(
        subscription=subscription,
        server=server,
        label=payload.label,
        make_primary=payload.make_primary,
    )
    report = await vpn.try_sync(server)
    log.info("vpn.device_added", client_id=str(client.id), synced=report is not None)

    refreshed = await vpn.get_client(client.id)
    return ClientWithLinks(
        **ClientRead.model_validate(refreshed).model_dump(),
        links=_links_of(refreshed, await vpn.build_links(refreshed)),
    )


@router.get("/clients/{client_id}/link", response_model=ClientLinksRead)
async def client_link(
    client_id: str, user: ActiveUser, subscriptions: SubscriptionSvc, vpn: VpnSvc
) -> ClientLinksRead:
    """Reveal a config link — the only place a VLESS UUID leaves the API."""
    client = await vpn.get_client(to_uuid(client_id))
    if client.user_id != user.id and not user.is_admin:
        raise NotFoundError("Подключение не найдено")
    return _links_of(client, await vpn.build_links(client))


@router.post("/clients/{client_id}/rotate", response_model=ClientLinksRead)
async def rotate_device(
    client_id: str, user: ActiveUser, subscriptions: SubscriptionSvc, vpn: VpnSvc
) -> ClientLinksRead:
    """Issue a fresh UUID — instantly invalidates a config that leaked."""
    cid = to_uuid(client_id)
    client = await vpn.get_client(cid)
    if client.user_id != user.id and not user.is_admin:
        raise NotFoundError("Подключение не найдено")

    await vpn.rotate_client(client)
    await vpn.try_sync(client.server)

    refreshed = await vpn.get_client(cid)
    return _links_of(refreshed, await vpn.build_links(refreshed))


@router.delete("/clients/{client_id}", response_model=Message)
async def remove_device(
    client_id: str, user: ActiveUser, subscriptions: SubscriptionSvc, vpn: VpnSvc
) -> Message:
    client = await vpn.get_client(to_uuid(client_id))
    if client.user_id != user.id and not user.is_admin:
        raise NotFoundError("Подключение не найдено")

    # The guard counts *enabled* devices, not only those already pushed to Xray:
    # while a node is unreachable every client is PENDING, and the user must
    # still be able to remove one.
    enabled = [c for c in client.subscription.clients if c.status != ClientStatus.DISABLED]
    if len(enabled) <= 1:
        raise ConflictError(
            "Это единственное активное устройство. Продлите подписку, чтобы выпустить новый конфиг."
        )

    await vpn.revoke_client(client, reason="user_request")
    await vpn.try_sync(client.server)
    return Message(detail="Подключение отключено")


@router.post("/sync", response_model=Message)
async def force_sync(user: ActiveUser, servers: ServerSvc, vpn: VpnSvc) -> Message:
    """Manual 'reconnect' button: re-pushes configs and restarts Xray."""
    results = await vpn.sync_all_servers(force=True)
    ok = sum(1 for r in results if r.get("ok"))
    return Message(detail=f"Синхронизировано серверов: {ok}/{len(results)}")


@router.get("/health", response_model=dict)
async def my_server_health(
    user: ActiveUser, subscriptions: SubscriptionSvc, servers: ServerSvc, vpn: VpnSvc
) -> dict:
    """Health of the node this user is assigned to (used by the status screen)."""
    subscription = await subscriptions.current(user.id)
    if subscription is None or subscription.server is None:
        return {"status": "unknown", "ok": False, "detail": "Нет активной подписки"}

    report = await vpn.check_server(subscription.server)
    return {
        **report.as_dict(),
        "server_name": subscription.server.name,
        "host": subscription.server.public_host,
        "port": subscription.server.public_port,
    }
