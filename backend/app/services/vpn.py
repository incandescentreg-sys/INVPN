"""VPN provisioning: issue/rotate/revoke clients and keep Xray in sync.

Xray is treated as the source of truth for *what is live*, the DB for *what
should be live*. `sync_server()` reconciles the difference in a single SSH
round-trip and then records the result, so it is safe to call from a webhook,
a user action, or the cron job.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ClientStatus, HealthStatus
from app.logging_config import get_logger
from app.models.server import VpnServer
from app.models.subscription import Subscription
from app.models.user import User
from app.models.vpn_client import VpnClient
from app.repositories.server import ServerRepository
from app.repositories.subscription import SubscriptionRepository
from app.repositories.vpn_client import VpnClientRepository
from app.utils.exceptions import ConflictError, NotFoundError
from app.vpn.config import ClientSpec
from app.vpn.manager import HealthReport, ServerEndpoint, XrayManager
from app.vpn.ssh import safe_error

log = get_logger(__name__)

SYNC_BATCH_LIMIT = 2000


@dataclass(slots=True)
class ClientLinks:
    uuid: str
    label: str
    link: str
    base64_link: str
    deep_links: dict[str, str]
    server_name: str
    host: str
    port: int
    qr_payload: str


def client_email(user: User, subscription_id: uuid.UUID) -> str:
    """Xray client `email` — unique and stable, so a link is never rotated by accident."""
    handle = user.username or str(user.telegram_id)
    return f"u{user.telegram_id}-{subscription_id.hex[:8]}-{handle}"


class VpnService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._clients = VpnClientRepository(session)
        self._servers = ServerRepository(session)
        self._subs = SubscriptionRepository(session)

    # ------------------------------------------------------------------ #
    def manager_for(self, server: VpnServer) -> XrayManager:
        return XrayManager(ServerEndpoint.from_model(server))

    async def get_server(self, server_id: Any) -> VpnServer | None:
        return await self._servers.get(server_id)

    # -- provisioning --------------------------------------------------- #
    async def create_client(
        self,
        *,
        subscription: Subscription,
        server: VpnServer,
        label: str | None = None,
        make_primary: bool = True,
    ) -> VpnClient:
        """Create a pending client row. The Xray sync happens in `sync_server`."""
        used = await self._clients.count_for_subscription(subscription.id)
        if not subscription.can_add_device(used):
            raise ConflictError(
                f"Достигнут лимит устройств для тарифа ({subscription.device_limit}). "
                "Отключите лишнее устройство или купите тариф с большим лимитом."
            )

        if not server.has_capacity(await self._servers.count_clients(server.id)):
            raise ConflictError("На выбранном сервере нет свободных мест, выберите другой")

        user = subscription.user
        while True:
            candidate = uuid.uuid4()
            if await self._clients.get_by_uuid(candidate) is None:
                break

        client = await self._clients.create(
            user_id=subscription.user_id,
            subscription_id=subscription.id,
            server_id=server.id,
            uuid=candidate,
            email=client_email(user, subscription.id),
            label=label or f"Устройство {used + 1}",
            flow="xtls-rprx-vision",
            status=ClientStatus.PENDING,
            is_primary=make_primary and used == 0,
        )
        log.info(
            "vpn.client_created", client_id=str(client.id), user_id=str(subscription.user_id)
        )
        return client

    async def revoke_client(self, client: VpnClient, *, reason: str = "user_request") -> bool:
        await self._clients.set_status(client, ClientStatus.DISABLED)
        await self._clients.set_disabled_reason(client, reason)
        log.info("vpn.client_revoked", client_id=str(client.id), reason=reason)
        return True

    async def delete_clients(self, subscription: Subscription) -> int:
        return await self._clients.delete_by_subscription(subscription.id)

    async def rotate_client(self, client: VpnClient, *, label: str | None = None) -> VpnClient:
        """New UUID for the same row — invalidates a leaked config instantly."""
        old = str(client.uuid)
        client.uuid = uuid.uuid4()
        client.status = ClientStatus.PENDING
        client.label = label or client.label
        await self._session.flush()
        log.info("vpn.client_rotated", client_id=str(client.id), old_uuid=old)
        return client

    # -- links ---------------------------------------------------------- #
    async def build_links(self, client: VpnClient) -> ClientLinks:
        server = await self._servers.get(client.server_id)
        if server is None:
            raise NotFoundError("Сервер клиента не найден")
        manager = self.manager_for(server)
        label = f"VPN · {client.label or client.email}"
        link = manager.build_link(str(client.uuid), label=label)
        from app.vpn.link import base64_link

        return ClientLinks(
            uuid=str(client.uuid),
            label=label,
            link=link,
            base64_link=base64_link(link),
            deep_links=manager.build_deep_links(str(client.uuid), label=label),
            server_name=manager.endpoint.server_name,
            host=manager.endpoint.public_host,
            port=manager.endpoint.public_port,
            qr_payload=link,
        )

    # -- synchronisation ------------------------------------------------ #
    def _desired_clients(self, server: VpnServer, clients: list[VpnClient]) -> list[ClientSpec]:
        return [
            ClientSpec(uuid=str(c.uuid), email=c.email, flow=c.flow)
            for c in clients
            if c.status in (ClientStatus.ACTIVE, ClientStatus.PENDING)
        ]

    async def sync_server(
        self, server: VpnServer, *, force: bool = False, push: bool = True
    ) -> dict[str, Any]:
        """Make Xray match the DB, then record the outcome.

        `push=False` performs a read-only comparison (used by the drift check).
        """
        manager = self.manager_for(server)
        clients = list((await self._clients.list_by_server(server.id))[:SYNC_BATCH_LIMIT])
        desired = self._desired_clients(server, clients)

        if not push:
            live = await manager.list_clients()
            live_emails = {str(c.get("email")) for c in live}
            want = {spec.email for spec in desired}
            return {
                "in_sync": live_emails == want,
                "missing": sorted(want - live_emails),
                "extra": sorted(live_emails - want),
                "live_count": len(live),
                "desired_count": len(want),
            }

        report = await manager.apply_sync(desired, force=force)

        # DB <- observed state
        for client in clients:
            if report.removed and client.email in report.removed:
                continue
            if report.added or report.updated or client.status in (ClientStatus.PENDING, ClientStatus.ERROR):
                await self._clients.set_status(client, ClientStatus.ACTIVE)
            elif report.changed:
                await self._clients.set_status(client, client.status)

        removed = set(report.removed)
        for client in clients:
            if client.email in removed and client.status != ClientStatus.DISABLED:
                await self._clients.set_status(client, ClientStatus.DISABLED)

        await self._servers.mark_synced(server.id)
        return report.as_dict()

    async def record_error(self, server: VpnServer, error: str) -> None:
        await self._servers.mark_health(server.id, status=str(HealthStatus.DOWN), error=error[:500])

    async def try_sync(self, server: VpnServer | None, *, force: bool = False) -> dict[str, Any] | None:
        """Sync without ever raising.

        A node hiccup must not roll back a user action: the client row stays
        PENDING and the next cron run activates it. Returns None on failure.
        """
        if server is None:
            return None
        try:
            return await self.sync_server(server, force=force)
        except Exception as exc:
            log.warning(
                "vpn.sync_deferred", server=server.name, error=safe_error(exc)[:200]
            )
            await self.record_error(server, safe_error(exc))
            return None

    async def sync_all_servers(self, *, force: bool = False) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for server in await self._servers.list_active():
            entry: dict[str, Any] = {"server_id": str(server.id), "name": server.name}
            try:
                entry.update(await self.sync_server(server, force=force))
                entry["ok"] = True
            except Exception as exc:
                entry.update({"ok": False, "error": str(exc)[:300]})
                log.warning("vpn.sync_failed", server=server.name, error=str(exc)[:200])
                await self.record_error(server, str(exc))
            results.append(entry)
        return results

    # -- health --------------------------------------------------------- #
    async def check_server(self, server: VpnServer) -> HealthReport:
        manager = self.manager_for(server)
        report = await manager.health()
        await self._servers.mark_health(
            server.id, status=str(report.status), error=report.error
        )
        return report

    async def check_all_servers(self) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        for server in await self._servers.list_all():
            try:
                report = await self.check_server(server)
            except Exception as exc:
                reports.append({"server_id": str(server.id), "name": server.name, "status": "down", "error": str(exc)[:300]})
                continue
            reports.append({"server_id": str(server.id), "name": server.name, **report.as_dict()})
        return reports

    # -- helpers -------------------------------------------------------- #
    async def active_clients(self, subscription: Subscription) -> list[VpnClient]:
        return list(await self._clients.list_by_subscription(subscription.id, only_active=True))

    async def get_client(self, client_id: uuid.UUID) -> VpnClient:
        client = await self._clients.get(client_id)
        if client is None:
            raise NotFoundError("Подключение не найдено")
        return client

    async def ensure_primary_client(self, subscription: Subscription, server: VpnServer) -> VpnClient:
        """Guarantee the subscription always has exactly one usable config."""
        active = await self.active_clients(subscription)
        if active:
            primary = next((c for c in active if c.is_primary), None)
            if primary is not None:
                return primary
            await self._clients.set_primary(subscription.id, active[0].id)
            return active[0]
        client = await self.create_client(subscription=subscription, server=server, make_primary=True)
        return client

    async def ensure_ready(self, subscription: Subscription, server: VpnServer) -> VpnClient:
        client = await self.ensure_primary_client(subscription, server)
        if client.status != ClientStatus.ACTIVE:
            await self.sync_server(server)
        return client
