"""SSH transport to the VPN host.

Security posture:
  * private key auth only (no password, no keyboard-interactive, no agent);
  * host key verification is mandatory — either an OpenSSH `known_hosts` blob or
    a pinned ``SHA256:`` fingerprint. Connecting with no pin at all is refused
    unless the caller explicitly asks for it (bootstrap only);
  * only a small allowlist of commands can be executed, and each one is built by
    our own code, never from user input;
  * every remote path is quoted with ``shlex.quote``;
  * exception text is scrubbed so key material can never reach logs or clients.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

import asyncssh

from app.config import SshSettings
from app.logging_config import get_logger
from app.utils.exceptions import VpnError, VpnUnavailableError

log = get_logger(__name__)

DEFAULT_TIMEOUT = 20.0
HEREDOC_TAG = "__VPN_EOF__"
_REDACTED = "***REDACTED_KEY***"

_PEM_RE = re.compile(r"-----BEGIN[^-]*-----.*?-----END[^-]*-----", re.DOTALL)


def safe_error(exc: BaseException | str) -> str:
    """Exception text with key material removed.

    asyncssh embeds the offending value in messages like
    ``Invalid argument: '<value>'``, so an unusable key path would otherwise
    leak the private key into logs and API responses.
    """
    text = exc if isinstance(exc, str) else str(exc)
    text = _PEM_RE.sub(_REDACTED, text)
    text = re.sub(r"(?i)\b(passphrase|password|secret|key)\s*=\s*\S+", r"\1=***", text)
    return text[:300]


def _normalise_fingerprint(value: str) -> str:
    """`SHA256:abc` -> `abc`; tolerant of case and whitespace."""
    text = value.strip()
    if ":" in text:
        text = text.split(":", 1)[1]
    return text.strip()


class _PinnedHostKeyClient(asyncssh.SSHClient):
    """Validates the server host key against a pinned SHA256 fingerprint.

    asyncssh consults this callback only when ``known_hosts`` is not ``None``,
    so we pass an empty ``SSHKnownHosts()``: the trust list stays empty and every
    host key goes through this check.

    NOTE: the callback must be **synchronous**. asyncssh evaluates the result
    directly (``if not client.validate_host_public_key(...)``), so an ``async
    def`` would return a truthy coroutine and accept *any* host key.
    """

    def __init__(self, expected: str | None, allow_unverified: bool) -> None:
        self._expected = _normalise_fingerprint(expected) if expected else None
        self._allow_unverified = allow_unverified

    def validate_host_public_key(
        self, host: str, addr: str, port: int, key: asyncssh.SSHKey
    ) -> bool:
        fingerprint = _normalise_fingerprint(key.get_fingerprint("sha256"))

        if not self._expected:
            if not self._allow_unverified:
                raise VpnError(
                    f"Host key сервера {host} не закреплён. Задайте SERVER_SSH_HOST_KEY_SHA256 "
                    "(ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub) — соединение запрещено."
                )
            log.warning("ssh.host_key_unverified", host=host, fingerprint=fingerprint)
            return True

        if fingerprint == self._expected:
            return True

        log.error("ssh.host_key_mismatch", host=host, expected=self._expected, got=fingerprint)
        raise VpnError(f"Отпечаток host key не совпадает для {host} — возможна подмена сервера.")


@dataclass(slots=True)
class CommandResult:
    command: str
    stdout: str
    stderr: str
    exit_status: int

    @property
    def ok(self) -> bool:
        return self.exit_status == 0

    @property
    def output(self) -> str:
        return self.stdout.strip()


def shlex_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)


def _text(value: Any) -> str:
    """asyncssh returns str or bytes depending on the connection encoding."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


class SSHConnection:
    """A live SSH connection with the commands the manager is allowed to run."""

    __slots__ = ("_conn",)

    def __init__(self, conn: asyncssh.SSHClientConnection) -> None:
        self._conn = conn

    async def run(
        self, command: str, *, check: bool = True, timeout: float | None = None
    ) -> CommandResult:
        result = await self._conn.run(command, check=False, timeout=timeout or DEFAULT_TIMEOUT)
        cmd_result = CommandResult(
            command=command,
            stdout=_text(result.stdout),
            stderr=_text(result.stderr),
            exit_status=result.exit_status if result.exit_status is not None else -1,
        )
        if check and not cmd_result.ok:
            log.error(
                "ssh.command_failed",
                command=command,
                exit_status=cmd_result.exit_status,
                stderr=cmd_result.stderr[-300:],
            )
            raise VpnError(
                f"Команда завершилась с кодом {cmd_result.exit_status}: "
                f"{cmd_result.stderr.strip()[:300]}"
            )
        return cmd_result

    async def read_file(self, path: str) -> str:
        result = await self._conn.run(
            f"cat -- {shlex_quote(path)}", check=True, timeout=DEFAULT_TIMEOUT
        )
        return _text(result.stdout)

    async def write_file(self, path: str, content: str, *, mode: int = 0o640) -> None:
        """Write via a temp file + atomic rename so a crash never truncates config."""
        if HEREDOC_TAG in content:
            content = content.replace(HEREDOC_TAG, f"{HEREDOC_TAG}_ESCAPED")
        temporary = f"{path}.tmp"
        command = (
            f"umask 077 && cat > {shlex_quote(temporary)} <<'{HEREDOC_TAG}'\n"
            f"{content}\n{HEREDOC_TAG}\n"
            f"chmod {mode:o} {shlex_quote(temporary)} && "
            f"mv -f {shlex_quote(temporary)} {shlex_quote(path)}"
        )
        await self.run(command, timeout=DEFAULT_TIMEOUT)


@contextlib.asynccontextmanager
async def ssh_session(
    settings: SshSettings, *, allow_unverified_host: bool = False
) -> AsyncIterator[SSHConnection]:
    """Open a connection, yield a command runner, always close it."""
    if not settings.configured:
        raise VpnUnavailableError(
            "SSH не настроен: задайте SERVER_HOST и SERVER_SSH_KEY "
            "(или добавьте сервер через админку)"
        )

    # An empty SSHKnownHosts keeps the trust list empty, which forces every
    # host key through our own validate_host_public_key callback.
    known_hosts: Any = settings.known_hosts or asyncssh.SSHKnownHosts()
    key_pem = settings.key.get_secret_value().replace("\\n", "\n")
    passphrase = settings.passphrase.get_secret_value() or None

    conn: asyncssh.SSHClientConnection | None = None
    last_error: BaseException | None = None

    for attempt in range(1, max(1, settings.connect_retries) + 1):
        try:
            conn = await asyncssh.connect(
                host=settings.host,
                port=settings.port,
                username=settings.user,
                client_keys=[key_pem],
                passphrase=passphrase,
                known_hosts=known_hosts,
                client_factory=lambda: _PinnedHostKeyClient(
                    settings.host_key_sha256, allow_unverified_host
                ),
                login_timeout=settings.timeout,
                keepalive_interval=15,
                keepalive_count_max=3,
            )
            break
        except (OSError, asyncssh.Error, VpnError) as exc:
            last_error = exc
            log.warning(
                "ssh.connect_failed",
                host=settings.host,
                attempt=attempt,
                error=safe_error(exc),
            )
            if attempt < settings.connect_retries:
                await asyncio.sleep(min(2**attempt, 5))

    if conn is None:
        raise VpnUnavailableError(
            f"Не удалось подключиться к {settings.host}: {safe_error(last_error or Exception('unknown'))}"
        )

    try:
        yield SSHConnection(conn)
    finally:
        conn.close()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(conn.wait_closed(), timeout=5)


async def probe_host_key(settings: SshSettings) -> str:
    """Read the server fingerprint so it can be pinned in the env.

    This is the *only* place where an unverified host key is accepted, and it is
    never used for management operations.
    """
    conn = await asyncssh.connect(
        host=settings.host,
        port=settings.port,
        username=settings.user,
        client_keys=[settings.key.get_secret_value().replace("\\n", "\n")],
        passphrase=settings.passphrase.get_secret_value() or None,
        known_hosts=asyncssh.SSHKnownHosts(),
        client_factory=lambda: _PinnedHostKeyClient(expected=None, allow_unverified=True),
        login_timeout=settings.timeout,
    )
    try:
        host_key = conn.get_server_host_key()
        if host_key is None:  # pragma: no cover - defensive
            raise VpnError("Сервер не предъявил host key")
        return host_key.get_fingerprint("sha256")
    finally:
        conn.close()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(conn.wait_closed(), timeout=5)


def batched(items: Sequence[Any], size: int) -> list[list[Any]]:
    return [list(items[i : i + size]) for i in range(0, len(items), size)]
