"""REALITY helpers: X25519 keypairs, shortId generation, target parsing.

Keys are generated **locally** with `cryptography` so the control plane does not
need the `xray` binary. Xray encodes x25519 keys as base64url *without* padding
(43 chars), which is what we produce here.

The remote `xray x25519` command is still supported as a fallback — its output
labels have changed between releases (`Public key:` -> `Password:`), so the
parser accepts every label we have ever seen.
"""

from __future__ import annotations

import base64
import re
import secrets
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

_X25519_LEN = 32

_PRIVATE_LABELS = ("privatekey", "private key", "private_key", "private-key")
_PUBLIC_LABELS = ("password", "publickey", "public key", "public_key", "public-key")


@dataclass(frozen=True, slots=True)
class RealityKeypair:
    private_key: str
    public_key: str


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def generate_keypair() -> RealityKeypair:
    """Fresh X25519 pair for REALITY (Xray-compatible encoding)."""
    private = X25519PrivateKey.generate()
    private_raw = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return RealityKeypair(private_key=_b64(private_raw), public_key=_b64(public_raw))


def public_key_from_private(private_key: str) -> str:
    """Derive the REALITY public key from the private one."""
    key = X25519PrivateKey.from_private_bytes(_unb64(private_key))
    return _b64(key.public_key().public_bytes(encoding=serialization.Encoding.Raw,
                                              format=serialization.PublicFormat.Raw))


def is_valid_key(value: str) -> bool:
    try:
        return len(_unb64(value)) == _X25519_LEN
    except Exception:
        return False


def generate_short_id(length_bytes: int = 8) -> str:
    """shortId: even-length hex string, 0..8 bytes. We use 8 bytes by default."""
    length_bytes = max(1, min(8, length_bytes))
    return secrets.token_hex(length_bytes)


def is_valid_short_id(value: str) -> bool:
    return bool(value) and len(value) % 2 == 0 and len(value) <= 16 and re.fullmatch(r"[0-9a-fA-F]+", value) is not None


def split_target(target: str) -> tuple[str, int]:
    """'www.microsoft.com:443' -> ('www.microsoft.com', 443)."""
    host, _, port = target.rpartition(":")
    if not host:
        return target, 443
    return host, int(port) if port.isdigit() else 443


def parse_xray_x25519_output(output: str) -> RealityKeypair:
    """Parse `xray x25519` stdout across Xray releases."""
    private: str | None = None
    public: str | None = None

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        label, _, value = line.partition(":")
        value = value.strip()
        key = label.strip().lower()
        if private is None and key in _PRIVATE_LABELS and is_valid_key(value):
            private = value
        elif public is None and key in _PUBLIC_LABELS and is_valid_key(value):
            public = value

    if private is None:
        raise ValueError(f"Не удалось разобрать приватный ключ из вывода xray: {output!r}")

    return RealityKeypair(private_key=private, public_key=public or public_key_from_private(private))
