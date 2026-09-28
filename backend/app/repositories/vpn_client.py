"""VPN client data access."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ClientStatus
from app.models.vpn_client import VpnClient
from app.utils.time import now


class VpnClientRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, client_id: uuid.UUID) -> VpnClient | None:
        return await self._session.get(VpnClient, client_id)

    async def get_by_email(self, email: str) -> VpnClient | None:
        return await self._session.scalar(select(VpnClient).where(VpnClient.email == email))

    async def get_by_uuid(self, client_uuid: uuid.UUID) -> VpnClient | None:
        return await self._session.scalar(select(VpnClient).where(VpnClient.uuid == client_uuid))

    async def list_by_subscription(
        self, subscription_id: uuid.UUID, *, only_active: bool = False
    ) -> Sequence[VpnClient]:
        stmt = select(VpnClient).where(VpnClient.subscription_id == subscription_id)
        if only_active:
            stmt = stmt.where(VpnClient.status == ClientStatus.ACTIVE)
        stmt = stmt.order_by(VpnClient.is_primary.desc(), VpnClient.created_at)
        return (await self._session.scalars(stmt)).all()

    async def list_by_server(self, server_id: uuid.UUID) -> Sequence[VpnClient]:
        stmt = select(VpnClient).where(VpnClient.server_id == server_id)
        return (await self._session.scalars(stmt)).all()

    async def list_active_by_server(self, server_id: uuid.UUID) -> Sequence[VpnClient]:
        stmt = select(VpnClient).where(
            VpnClient.server_id == server_id, VpnClient.status == ClientStatus.ACTIVE
        )
        return (await self._session.scalars(stmt)).all()

    async def list_by_user(self, user_id: uuid.UUID) -> Sequence[VpnClient]:
        stmt = select(VpnClient).where(VpnClient.user_id == user_id)
        return (await self._session.scalars(stmt)).all()

    async def list_out_of_sync(self, *, limit: int = 500) -> Sequence[VpnClient]:
        """Clients whose DB state disagrees with the desired Xray state."""
        stmt = (
            select(VpnClient)
            .where(VpnClient.status.in_([ClientStatus.PENDING, ClientStatus.ERROR]))
            .limit(limit)
        )
        return (await self._session.scalars(stmt)).all()

    async def create(self, **fields: object) -> VpnClient:
        client = VpnClient(**fields)  # type: ignore[arg-type]
        self._session.add(client)
        await self._session.flush()
        return client

    async def set_status(
        self,
        client: VpnClient,
        status: ClientStatus,
        *,
        error: str | None = None,
    ) -> VpnClient:
        client.status = status
        client.last_error = error
        client.last_synced_at = now()
        if status == ClientStatus.DISABLED:
            client.disabled_at = now()
        elif status == ClientStatus.ACTIVE:
            client.disabled_at = None
            client.disabled_reason = None
        await self._session.flush()
        return client

    async def set_disabled_reason(self, client: VpnClient, reason: str) -> None:
        client.disabled_reason = reason
        await self._session.flush()

    async def delete(self, client_id: uuid.UUID) -> bool:
        client = await self.get(client_id)
        if client is None:
            return False
        await self._session.delete(client)
        await self._session.flush()
        return True

    async def delete_by_subscription(self, subscription_id: uuid.UUID) -> int:
        result = await self._session.execute(
            delete(VpnClient).where(VpnClient.subscription_id == subscription_id)
        )
        await self._session.flush()
        return int(getattr(result, "rowcount", 0) or 0)

    async def count_for_subscription(self, subscription_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(VpnClient)
            .where(
                VpnClient.subscription_id == subscription_id,
                VpnClient.status != ClientStatus.DISABLED,
            )
        )
        return int(await self._session.scalar(stmt) or 0)

    async def set_primary(self, subscription_id: uuid.UUID, client_id: uuid.UUID) -> None:
        await self._session.execute(
            update(VpnClient)
            .where(VpnClient.subscription_id == subscription_id)
            .values(is_primary=False)
        )
        await self._session.execute(
            update(VpnClient).where(VpnClient.id == client_id).values(is_primary=True)
        )
        await self._session.flush()

    async def touch_seen(self, client_id: uuid.UUID, seen_at: dt.datetime | None = None) -> None:
        await self._session.execute(
            update(VpnClient).where(VpnClient.id == client_id).values(last_seen_at=seen_at or now())
        )
