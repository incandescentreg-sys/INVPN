"""Node (VPN server) management + bootstrap from flat env variables.

The `default` node row is created/refreshed from SERVER_* / XRAY_* / REALITY_*
so operators can start with a single .env and later add more nodes from the
admin UI without changing code.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import (
    ssh_settings,
    vpn_public_settings,
    xray_settings,
)
from app.logging_config import get_logger
from app.models.server import VpnServer
from app.repositories.server import ServerRepository
from app.utils.crypto import encrypt
from app.vpn.reality import generate_keypair, generate_short_id, public_key_from_private

log = get_logger(__name__)

DEFAULT_SERVER_NAME = "default"


class ServerService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._servers = ServerRepository(session)

    async def list_all(self) -> list[VpnServer]:
        return await self._servers.list_all()

    async def list_active(self) -> list[VpnServer]:
        return await self._servers.list_active()

    async def get(self, server_id: uuid.UUID) -> VpnServer:
        server = await self._servers.get(server_id)
        if server is None:
            from app.utils.exceptions import NotFoundError

            raise NotFoundError("Сервер не найден")
        return server

    async def create(self, **fields: Any) -> VpnServer:
        name = str(fields.get("name", "")).strip()
        if not name:
            raise ValueError("Имя сервера обязательно")
        if await self._servers.get_by_name(name):
            raise ValueError(f"Сервер {name!r} уже существует")

        fields.setdefault("is_active", True)
        fields.setdefault("public_port", 443)
        fields.setdefault("max_clients", 0)

        # Secrets arrive in plaintext from the API and are stored encrypted.
        self._absorb_secrets(fields)

        private = fields.pop("reality_private_key", None) or generate_keypair().private_key
        fields["reality_private_key_encrypted"] = encrypt(private)
        fields["reality_public_key"] = public_key_from_private(private)
        fields.setdefault("reality_short_id", generate_short_id())
        if isinstance(fields.get("reality_server_names"), list):
            fields["reality_server_names"] = ",".join(fields["reality_server_names"])

        server = await self._servers.create(**fields)
        log.info("server.created", name=server.name, host=server.host)
        return server

    @staticmethod
    def _absorb_secrets(fields: dict[str, Any]) -> None:
        """Move `ssh_key` / `ssh_passphrase` into their encrypted columns."""
        key = fields.pop("ssh_key", None)
        if key:
            fields["ssh_key_encrypted"] = encrypt(str(key))
        passphrase = fields.pop("ssh_passphrase", None)
        if passphrase:
            fields["ssh_key_passphrase_encrypted"] = encrypt(str(passphrase))

    async def update(self, server_id: uuid.UUID, **fields: Any) -> VpnServer:
        self._absorb_secrets(fields)
        secret = fields.pop("reality_private_key", None)
        if secret:
            fields["reality_private_key_encrypted"] = encrypt(secret)
            fields["reality_public_key"] = public_key_from_private(secret)
        if isinstance(fields.get("reality_server_names"), list):
            fields["reality_server_names"] = ",".join(fields["reality_server_names"])
        server = await self._servers.update(server_id, **fields)
        if server is None:
            from app.utils.exceptions import NotFoundError

            raise NotFoundError("Сервер не найден")
        return server

    async def delete(self, server_id: uuid.UUID) -> bool:
        return await self._servers.delete(server_id)

    async def pick(self, plan_server_id: uuid.UUID | None = None) -> VpnServer | None:
        return await self._servers.pick_for_subscription(plan_server_id)

    async def client_count(self, server_id: uuid.UUID) -> int:
        return await self._servers.count_clients(server_id)

    async def active_client_count(self, server_id: uuid.UUID) -> int:
        return await self._servers.count_clients(server_id, only_active=True)

    # ------------------------------------------------------------------ #
    async def bootstrap_from_env(self) -> VpnServer | None:
        """Create/refresh the `default` node from the flat env configuration."""
        if not ssh_settings.host or not ssh_settings.key.get_secret_value().strip():
            log.info("server.bootstrap_skipped", reason="SERVER_HOST/SERVER_SSH_KEY not set")
            return None

        short_id = xray_settings.reality_short_ids[0] if xray_settings.reality_short_ids else generate_short_id()
        values: dict[str, object] = {
            "host": ssh_settings.host,
            "ssh_port": ssh_settings.port,
            "ssh_user": ssh_settings.user,
            "ssh_key_encrypted": encrypt(ssh_settings.key.get_secret_value()),
            "ssh_key_passphrase_encrypted": encrypt(
                ssh_settings.passphrase.get_secret_value() or None
            ),
            "ssh_host_key_sha256": ssh_settings.host_key_sha256 or None,
            "xray_config_path": xray_settings.config_path,
            "xray_service_name": xray_settings.service_name,
            "xray_inbound_tag": xray_settings.inbound_tag,
            "xray_binary": xray_settings.binary,
            "reload_mode": xray_settings.reload_mode,
            "public_host": vpn_public_settings.domain or ssh_settings.host,
            "public_port": vpn_public_settings.port,
            "reality_target": xray_settings.reality_target,
            "reality_server_names": ",".join(xray_settings.reality_server_names),
            "reality_short_id": short_id,
            "reality_fingerprint": xray_settings.reality_fingerprint,
        }

        server = await self._servers.get_by_name(DEFAULT_SERVER_NAME)
        if server is None:
            # A brand new node needs its own REALITY keypair.
            private_key = generate_keypair().private_key
            server = await self._servers.create(
                name=DEFAULT_SERVER_NAME,
                is_active=True,
                reality_private_key_encrypted=encrypt(private_key),
                reality_public_key=public_key_from_private(private_key),
                **values,
            )
            log.info("server.bootstrapped", name=server.name, host=server.host)
        else:
            # REALITY keys must stay stable: rotating them breaks every client
            # link, so only the connection parameters are refreshed.
            for key, value in values.items():
                setattr(server, key, value)
            await self._session.flush()
            log.info("server.bootstrap_refreshed", name=server.name)
        return server
