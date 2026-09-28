"""Xray management over SSH.

One connection per operation: on serverless (Vercel) every invocation is billed
and time-limited, so `apply_sync()` performs read → merge → validate → atomic
write → restart inside a *single* SSH session.
"""

from __future__ import annotations

import contextlib
import datetime as dt
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.config import SshSettings, ssh_settings, vpn_public_settings, xray_settings
from app.enums import HealthStatus
from app.logging_config import get_logger
from app.utils.crypto import decrypt
from app.utils.exceptions import VpnError, VpnUnavailableError
from app.vpn.config import (
    ClientSpec,
    XrayConfigError,
    apply_clients,
    dump_config,
    ensure_inbound,
    get_clients,
    list_client_ids,
    load_config,
    public_view,
    set_reality,
)
from app.vpn.link import DEEP_LINKS, LinkParams, build_vless_link
from app.vpn.reality import generate_keypair, generate_short_id, public_key_from_private
from app.vpn.ssh import shlex_quote, ssh_session

log = get_logger(__name__)


@dataclass(slots=True)
class ServerEndpoint:
    """Everything needed to manage one Xray host (from env or from the DB)."""

    name: str
    host: str
    ssh_port: int = 22
    ssh_user: str = "root"
    ssh_key: str = ""
    ssh_passphrase: str = ""
    ssh_host_key_sha256: str = ""

    xray_config_path: str = "/usr/local/etc/xray/config.json"
    xray_service_name: str = "xray"
    xray_inbound_tag: str = "inbound-vless"
    xray_binary: str = "xray"
    reload_mode: str = "restart"
    listen: str = "0.0.0.0"

    public_host: str = ""
    public_port: int = 443

    reality_private_key: str = ""
    reality_public_key: str = ""
    reality_short_id: str = ""
    reality_target: str = "www.microsoft.com:443"
    reality_server_names: list[str] = field(default_factory=lambda: ["www.microsoft.com"])
    reality_fingerprint: str = "chrome"

    def ssh_settings(self) -> SshSettings:
        return SshSettings(
            host=self.host,
            port=self.ssh_port,
            user=self.ssh_user,
            key=self.ssh_key,
            passphrase=self.ssh_passphrase,
            host_key_sha256=self.ssh_host_key_sha256,
        )

    @property
    def server_name(self) -> str:
        return self.reality_server_names[0] if self.reality_server_names else self.sni_from_host()

    def sni_from_host(self) -> str:
        """When the public domain is used as SNI it must resolve to the VPS."""
        return self.public_host or "www.microsoft.com"

    def is_configured(self) -> bool:
        return bool(self.host and self.ssh_key)

    @classmethod
    def from_env(cls) -> ServerEndpoint:
        return cls(
            name="default",
            host=ssh_settings.host,
            ssh_port=ssh_settings.port,
            ssh_user=ssh_settings.user,
            ssh_key=ssh_settings.key.get_secret_value(),
            ssh_passphrase=ssh_settings.passphrase.get_secret_value(),
            ssh_host_key_sha256=ssh_settings.host_key_sha256,
            xray_config_path=xray_settings.config_path,
            xray_service_name=xray_settings.service_name,
            xray_inbound_tag=xray_settings.inbound_tag,
            xray_binary=xray_settings.binary,
            reload_mode=xray_settings.reload_mode,
            listen=xray_settings.listen,
            public_host=vpn_public_settings.domain,
            public_port=vpn_public_settings.port,
            reality_target=xray_settings.reality_target,
            reality_server_names=list(xray_settings.reality_server_names),
            reality_fingerprint=xray_settings.reality_fingerprint,
            reality_short_id=xray_settings.reality_short_ids[0] if xray_settings.reality_short_ids else "",
        )

    @classmethod
    def from_model(cls, server: Any) -> ServerEndpoint:
        """Build an endpoint from a `VpnServer` row, decrypting stored secrets."""
        private_key = decrypt(server.reality_private_key_encrypted) or ""
        public_key = server.reality_public_key or ""
        if private_key and not public_key:
            with contextlib.suppress(Exception):
                public_key = public_key_from_private(private_key)
        names = server.server_names
        return cls(
            name=server.name,
            host=server.host,
            ssh_port=server.ssh_port,
            ssh_user=server.ssh_user,
            ssh_key=decrypt(server.ssh_key_encrypted) or "",
            ssh_passphrase=decrypt(server.ssh_key_passphrase_encrypted) or "",
            ssh_host_key_sha256=server.ssh_host_key_sha256 or "",
            xray_config_path=server.xray_config_path,
            xray_service_name=server.xray_service_name,
            xray_inbound_tag=server.xray_inbound_tag,
            xray_binary=server.xray_binary,
            reload_mode=server.reload_mode,
            public_host=server.public_host,
            public_port=server.public_port,
            reality_private_key=private_key,
            reality_public_key=public_key,
            reality_short_id=server.reality_short_id,
            reality_target=server.reality_target,
            reality_server_names=names,
            reality_fingerprint=server.reality_fingerprint,
        )


@dataclass(slots=True)
class SyncReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    inbound_created: bool = False
    reality_changed: bool = False
    restarted: bool = False
    validated: bool = False
    backup_path: str | None = None
    duration_ms: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.removed or self.inbound_created or self.reality_changed)

    def as_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "updated": self.updated,
            "removed": self.removed,
            "inbound_created": self.inbound_created,
            "reality_changed": self.reality_changed,
            "restarted": self.restarted,
            "validated": self.validated,
            "backup_path": self.backup_path,
            "duration_ms": self.duration_ms,
        }


@dataclass(slots=True)
class HealthReport:
    status: HealthStatus = HealthStatus.UNKNOWN
    checks: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    client_count: int = 0
    checked_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))

    @property
    def ok(self) -> bool:
        return self.status == HealthStatus.UP

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": str(self.status),
            "ok": self.ok,
            "error": self.error,
            "client_count": self.client_count,
            "checked_at": self.checked_at.isoformat(),
            "checks": self.checks,
        }


class XrayManager:
    """Manages the Xray instance on a single host."""

    def __init__(self, endpoint: ServerEndpoint) -> None:
        self.endpoint = endpoint

    # ------------------------------------------------------------------ #
    @contextlib.asynccontextmanager
    async def session(self, *, allow_unverified_host: bool = False) -> AsyncIterator[Any]:
        if not self.endpoint.is_configured():
            raise VpnUnavailableError(
                f"Сервер {self.endpoint.name!r} не настроен: нужны host и SSH-ключ"
            )
        async with ssh_session(
            self.endpoint.ssh_settings(), allow_unverified_host=allow_unverified_host
        ) as ssh:
            yield ssh

    # -- config IO ------------------------------------------------------ #
    async def read_config(self, ssh: Any) -> dict[str, Any]:
        raw = await ssh.read_file(self.endpoint.xray_config_path)
        return load_config(raw)

    async def write_config(self, ssh: Any, config: dict[str, Any]) -> None:
        await ssh.write_file(self.endpoint.xray_config_path, dump_config(config))

    async def backup_config(self, ssh: Any) -> str | None:
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d%H%M%S")
        backup = f"{self.endpoint.xray_config_path}.bak.{stamp}"
        cmd = (
            f"cp -p -- {shlex_quote(self.endpoint.xray_config_path)} "
            f"{shlex_quote(backup)} 2>/dev/null || true"
        )
        await ssh.run(cmd, check=False)
        return backup

    # -- keys ----------------------------------------------------------- #
    def ensure_local_reality_keys(self) -> tuple[str, str, str]:
        """Return (private, public, short_id), generating whatever is missing."""
        private = self.endpoint.reality_private_key
        public = self.endpoint.reality_public_key
        short_id = self.endpoint.reality_short_id

        if not private:
            pair = generate_keypair()
            private, public = pair.private_key, pair.public_key
        elif not public:
            public = public_key_from_private(private)
        if not short_id:
            short_id = generate_short_id()
        return private, public, short_id

    async def probe_server_keys(self, ssh: Any) -> tuple[str, str]:
        """Ask the remote xray for a keypair (used only when local gen fails)."""

        result = await ssh.run(f"{self.endpoint.xray_binary} x25519", check=True)
        return _keypair_from(result.output)  # type: ignore[return-value]

    # -- validation / service control ---------------------------------- #
    async def validate_config(self, ssh: Any) -> bool:
        """`xray run -test -c <path>` — refuses to start on a bad config."""
        path = shlex_quote(self.endpoint.xray_config_path)
        binary = shlex_quote(self.endpoint.xray_binary)
        for command in (f"{binary} run -test -c {path}", f"{binary} -test -config {path}"):
            result = await ssh.run(command, check=False)
            if result.ok:
                return True
            if "no such file" in result.stderr.lower() and command.startswith(f"{binary} run"):
                continue  # older binary: try the legacy flag form
        log.warning("xray.config_invalid", server=self.endpoint.name)
        return False

    async def restart_service(self, ssh: Any) -> bool:
        service = shlex_quote(self.endpoint.xray_service_name)
        if self.endpoint.reload_mode == "reload-sighup":
            result = await ssh.run(
                f"systemctl reload {service} 2>/dev/null || "
                f"pkill -HUP -x {self.endpoint.xray_service_name}",
                check=False,
            )
        else:
            result = await ssh.run(f"systemctl restart {service}", check=False)
        if not result.ok:
            log.error("xray.restart_failed", server=self.endpoint.name, stderr=result.stderr[-300:])
        return result.ok

    async def service_status(self, ssh: Any) -> dict[str, Any]:
        service = shlex_quote(self.endpoint.xray_service_name)
        result = await ssh.run(
            f"systemctl is-active {service} 2>/dev/null || true", check=False
        )
        active = result.output.strip()
        enabled = await ssh.run(f"systemctl is-enabled {service} 2>/dev/null || true", check=False)
        version = await ssh.run(f"{shlex_quote(self.endpoint.xray_binary)} version 2>/dev/null | head -1", check=False)
        return {
            "active": active,
            "enabled": enabled.output.strip(),
            "version": version.output.strip(),
        }

    # -- main operations ------------------------------------------------ #
    async def apply_sync(self, desired: Sequence[ClientSpec], *, force: bool = False) -> SyncReport:
        """Make the Xray client list match `desired` exactly. Single SSH session."""
        started = dt.datetime.now(dt.UTC)
        report = SyncReport()
        private, _public, short_id = self.ensure_local_reality_keys()

        async with self.session() as ssh:
            config = await self.read_config(ssh)

            config, created = ensure_inbound(
                config,
                tag=self.endpoint.xray_inbound_tag,
                port=self.endpoint.public_port,
                listen=self.endpoint.listen,
                private_key=private,
                target=self.endpoint.reality_target,
                server_names=self.endpoint.reality_server_names,
                short_ids=[short_id],
            )
            report.inbound_created = created

            config, reality_changed = set_reality(
                config,
                self.endpoint.xray_inbound_tag,
                private_key=private,
                target=self.endpoint.reality_target,
                server_names=self.endpoint.reality_server_names,
                short_ids=[short_id],
            )
            report.reality_changed = reality_changed

            try:
                config, delta = apply_clients(config, self.endpoint.xray_inbound_tag, list(desired))
            except XrayConfigError:
                raise
            report.added = delta["added"]
            report.updated = delta["updated"]
            report.removed = delta["removed"]

            if not report.changed and not force:
                log.debug("xray.sync_noop", server=self.endpoint.name)
            else:
                report.backup_path = await self.backup_config(ssh)
                await self.write_config(ssh, config)
                if not await self.validate_config(ssh):
                    if report.backup_path:
                        await ssh.run(
                            f"cp -pf -- {shlex_quote(report.backup_path)} "
                            f"{shlex_quote(self.endpoint.xray_config_path)} && "
                            f"systemctl restart {shlex_quote(self.endpoint.xray_service_name)}",
                            check=False,
                        )
                    raise VpnError(
                        "Xray отклонил конфигурацию; изменения откачены. Проверьте логи на сервере."
                    )
                report.validated = True
                report.restarted = await self.restart_service(ssh)

        report.duration_ms = int((dt.datetime.now(dt.UTC) - started).total_seconds() * 1000)
        log.info("xray.sync_done", server=self.endpoint.name, **report.as_dict())
        return report

    async def list_clients(self) -> list[dict[str, Any]]:
        async with self.session() as ssh:
            config = await self.read_config(ssh)
        return get_clients(config, self.endpoint.xray_inbound_tag)

    async def client_ids(self) -> list[str]:
        async with self.session() as ssh:
            config = await self.read_config(ssh)
        return list_client_ids(config, self.endpoint.xray_inbound_tag)

    async def get_client(self, email: str) -> dict[str, Any] | None:
        for client in await self.list_clients():
            if client.get("email") == email:
                return client
        return None

    async def get_config_public(self) -> dict[str, Any]:
        async with self.session() as ssh:
            config = await self.read_config(ssh)
        return public_view(config, self.endpoint.xray_inbound_tag)

    async def health(self) -> HealthReport:
        report = HealthReport()
        try:
            async with self.session() as ssh:
                status = await self.service_status(ssh)
                report.checks["service"] = status
                report.checks["config_valid"] = await self.validate_config(ssh)
                listening = await ssh.run(
                    f"ss -Hlnt 2>/dev/null | grep -c ':{self.endpoint.public_port} ' || true",
                    check=False,
                )
                port_open = listening.output.strip() not in ("", "0")
                report.checks["port_listening"] = port_open
                config = await self.read_config(ssh)
                report.client_count = len(get_clients(config, self.endpoint.xray_inbound_tag))
        except Exception as exc:
            report.status = HealthStatus.DOWN
            report.error = str(exc)[:500]
            log.warning("xray.health_failed", server=self.endpoint.name, error=str(exc)[:200])
            return report

        ok = (
            report.checks["service"]["active"] == "active"
            and bool(report.checks["config_valid"])
            and bool(report.checks["port_listening"])
        )
        if ok:
            report.status = HealthStatus.UP
        elif report.checks["config_valid"]:
            report.status = HealthStatus.DEGRADED
        else:
            report.status = HealthStatus.DOWN
        return report

    # -- links ---------------------------------------------------------- #
    def build_link(self, client_uuid: str, label: str = "VPN") -> str:
        _, public, short_id = self.ensure_local_reality_keys()
        params = LinkParams(
            client_uuid=client_uuid,
            host=self.endpoint.public_host or self.endpoint.host,
            port=self.endpoint.public_port,
            public_key=public,
            server_name=self.endpoint.server_name,
            short_id=short_id,
            fingerprint=self.endpoint.reality_fingerprint,
            label=label,
        )
        return build_vless_link(params)

    def build_deep_links(self, client_uuid: str, label: str = "VPN") -> dict[str, str]:
        link = self.build_link(client_uuid, label)
        return {name: builder(link) for name, builder in DEEP_LINKS.items()}


def _keypair_from(output: str) -> tuple[str, str]:
    from app.vpn.reality import parse_xray_x25519_output

    pair = parse_xray_x25519_output(output)
    return pair.private_key, pair.public_key


def build_manager(server_model: Any | None = None) -> XrayManager:
    """Factory: prefer the DB row, fall back to env configuration."""
    if server_model is not None:
        return XrayManager(ServerEndpoint.from_model(server_model))
    return XrayManager(ServerEndpoint.from_env())


__all__ = [
    "ClientSpec",
    "HealthReport",
    "ServerEndpoint",
    "SyncReport",
    "XrayManager",
    "build_manager",
]
