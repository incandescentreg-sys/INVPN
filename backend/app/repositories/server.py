"""VPN server (node) data access."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.server import VpnServer
from app.utils.time import now


class ServerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, server_id: uuid.UUID) -> VpnServer | None:
        return await self._session.get(VpnServer, server_id)

    async def get_by_name(self, name: str) -> VpnServer | None:
        return await self._session.scalar(select(VpnServer).where(VpnServer.name == name))

    async def list_all(self) -> list[VpnServer]:
        stmt = select(VpnServer).order_by(VpnServer.weight, VpnServer.created_at)
        return list((await self._session.scalars(stmt)).all())

    async def list_active(self) -> list[VpnServer]:
        stmt = (
            select(VpnServer)
            .where(VpnServer.is_active.is_(True))
            .order_by(VpnServer.weight, VpnServer.created_at)
        )
        return list((await self._session.scalars(stmt)).all())

    async def default(self) -> VpnServer | None:
        """The node created from the flat SERVER_* env vars."""
        return await self.get_by_name("default")

    async def create(self, **fields: object) -> VpnServer:
        server = VpnServer(**fields)  # type: ignore[arg-type]
        self._session.add(server)
        await self._session.flush()
        return server

    async def update(self, server_id: uuid.UUID, **fields: object) -> VpnServer | None:
        server = await self.get(server_id)
        if server is None:
            return None
        for key, value in fields.items():
            if hasattr(server, key):
                setattr(server, key, value)
        await self._session.flush()
        return server

    async def delete(self, server_id: uuid.UUID) -> bool:
        server = await self.get(server_id)
        if server is None:
            return False
        await self._session.delete(server)
        await self._session.flush()
        return True

    # -- capacity / health ----------------------------------------------- #
    async def count_clients(self, server_id: uuid.UUID, *, only_active: bool = True) -> int:
        from app.enums import ClientStatus
        from app.models.vpn_client import VpnClient

        stmt = select(func.count()).select_from(VpnClient).where(VpnClient.server_id == server_id)
        if only_active:
            stmt = stmt.where(VpnClient.status == ClientStatus.ACTIVE)
        return int(await self._session.scalar(stmt) or 0)

    async def pick_for_subscription(self, plan_server_id: uuid.UUID | None) -> VpnServer | None:
        """Plan-pinned node first, otherwise the least loaded healthy node."""
        if plan_server_id:
            pinned = await self.get(plan_server_id)
            if pinned and pinned.is_active:
                return pinned

        candidates = await self.list_active()
        healthy = [s for s in candidates if s.is_healthy] or candidates
        if not healthy:
            return None

        counts = await self.client_load({s.id for s in healthy})
        return sorted(
            healthy,
            key=lambda s: (counts.get(s.id, 0) / max(1, s.weight), counts.get(s.id, 0)),
        )[0]

    async def client_load(self, server_ids: set[uuid.UUID]) -> dict[uuid.UUID, int]:
        from app.enums import ClientStatus
        from app.models.vpn_client import VpnClient

        if not server_ids:
            return {}
        stmt = (
            select(VpnClient.server_id, func.count())
            .where(VpnClient.server_id.in_(server_ids), VpnClient.status == ClientStatus.ACTIVE)
            .group_by(VpnClient.server_id)
        )
        rows = (await self._session.execute(stmt)).all()
        return {row[0]: int(row[1]) for row in rows}

    async def mark_health(
        self,
        server_id: uuid.UUID,
        *,
        status: str,
        error: str | None = None,
        checked_at: datetime | None = None,
    ) -> None:
        server = await self.get(server_id)
        if server is None:
            return
        server.last_check_status = status
        server.last_check_error = error
        server.last_checked_at = checked_at or now()
        await self._session.flush()

    async def mark_synced(self, server_id: uuid.UUID) -> None:
        server = await self.get(server_id)
        if server is None:
            return
        server.xray_synced_at = now()
        await self._session.flush()
