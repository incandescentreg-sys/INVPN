"""SSH transport: host key pinning, command safety, error scrubbing.

The pinning tests matter most: an async `validate_host_public_key` returns a
truthy coroutine, which would silently accept *any* host key and defeat the
whole control. These tests fail loudly if that ever regresses.
"""

from __future__ import annotations

import pytest

from app.config import SshSettings
from app.utils.exceptions import VpnError
from app.vpn.ssh import (
    CommandResult,
    _PinnedHostKeyClient,
    batched,
    safe_error,
    shlex_quote,
)

# A syntactically valid OpenSSH ed25519 public key.
PUBLIC_KEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl example"
)


class FakeKey:
    def __init__(self, fingerprint: str) -> None:
        self._fingerprint = fingerprint

    def get_fingerprint(self, algorithm: str) -> str:
        return f"{algorithm}:{self._fingerprint}"


PINNED = "AbCdEf1234567890abcdefghijklmnopqrstuvwxyzAB"


def settings(**overrides: object) -> SshSettings:
    base = {
        "host": "10.0.0.1",
        "port": 22,
        "user": "root",
        "key": "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----",
        "host_key_sha256": f"SHA256:{PINNED}",
    }
    base.update(overrides)
    return SshSettings(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Host key pinning
# --------------------------------------------------------------------------- #
def test_matching_fingerprint_is_accepted() -> None:
    client = _PinnedHostKeyClient(expected=f"SHA256:{PINNED}", allow_unverified=False)
    assert client.validate_host_public_key("10.0.0.1", "10.0.0.1", 22, FakeKey(PINNED)) is True


def test_mismatched_fingerprint_is_refused() -> None:
    client = _PinnedHostKeyClient(expected=f"SHA256:{PINNED}", allow_unverified=False)
    with pytest.raises(VpnError, match="подмена"):
        client.validate_host_public_key("10.0.0.1", "10.0.0.1", 22, FakeKey("somethingElse"))


def test_missing_pin_refuses_connection() -> None:
    client = _PinnedHostKeyClient(expected=None, allow_unverified=False)
    with pytest.raises(VpnError, match="не закреплён"):
        client.validate_host_public_key("10.0.0.1", "10.0.0.1", 22, FakeKey(PINNED))


def test_bootstrap_mode_allows_unverified() -> None:
    client = _PinnedHostKeyClient(expected=None, allow_unverified=True)
    assert client.validate_host_public_key("10.0.0.1", "10.0.0.1", 22, FakeKey("any")) is True


def test_validate_host_public_key_is_synchronous() -> None:
    """asyncssh checks the return value directly — a coroutine would always pass."""
    import inspect

    assert not inspect.iscoroutinefunction(_PinnedHostKeyClient.validate_host_public_key)
    result = _PinnedHostKeyClient(
        expected=f"SHA256:{PINNED}", allow_unverified=False
    ).validate_host_public_key("h", "h", 22, FakeKey(PINNED))
    assert result is True, "must return a real bool, not a coroutine"


def test_ssh_settings_require_key_with_host() -> None:
    with pytest.raises(ValueError, match="SERVER_SSH_KEY"):
        SshSettings(host="10.0.0.1", key="")
    assert SshSettings(host="", key="").configured is False


def test_ssh_settings_from_env_secret() -> None:
    s = settings()
    assert s.configured is True
    assert s.key.get_secret_value().startswith("-----BEGIN")


# --------------------------------------------------------------------------- #
# Command safety
# --------------------------------------------------------------------------- #
def test_shlex_quote_neutralises_injection() -> None:
    import shlex

    hostile = "/etc/xray/config.json; rm -rf /"
    quoted = shlex_quote(hostile)
    # The whole value must survive as ONE argument, so the shell cannot split it.
    assert shlex.split(quoted) == [hostile]
    assert quoted.startswith("'") and quoted.endswith("'")


def test_error_text_is_scrubbed() -> None:
    pem = "-----BEGIN OPENSSH PRIVATE KEY-----\nSUPERSECRETKEY\n-----END OPENSSH PRIVATE KEY-----"
    message = safe_error(ValueError(f"Invalid argument: {pem}"))
    assert "SUPERSECRETKEY" not in message
    assert "REDACTED" in message


def test_error_text_scrubs_passwords() -> None:
    assert "hunter2" not in safe_error(Exception("connect failed password=hunter2"))


def test_error_text_is_length_limited() -> None:
    assert len(safe_error(Exception("x" * 5000))) <= 300


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def test_command_result_helpers() -> None:
    ok = CommandResult(command="ls", stdout=" a\n", stderr="", exit_status=0)
    assert ok.ok and ok.output == "a"
    bad = CommandResult(command="ls", stdout="", stderr="nope", exit_status=1)
    assert not bad.ok


def test_batched() -> None:
    assert batched([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
    assert batched([], 2) == []


@pytest.mark.asyncio
async def test_session_requires_configuration() -> None:
    from app.utils.exceptions import VpnUnavailableError
    from app.vpn.ssh import ssh_session

    with pytest.raises(VpnUnavailableError, match="SSH не настроен"):
        async with ssh_session(SshSettings(host="", key="")) as _:
            pass
