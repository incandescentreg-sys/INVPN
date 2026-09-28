"""Symmetric encryption for secrets stored in the DB (SSH private keys, etc.).

Key is derived from SECRET_KEY with scrypt, so rotating SECRET_KEY would make
old rows unreadable — plan a re-encryption script before rotating.
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import app_settings
from app.utils.exceptions import ConfigError

_SCRYPT_SALT = b"vpn-service-fernet-v1"


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    secret = app_settings.secret_key.get_secret_value().encode()
    if len(secret) < 16:
        raise ConfigError("SECRET_KEY слишком короткий")
    digest = hashlib.scrypt(secret, salt=_SCRYPT_SALT, n=2**14, r=8, p=1, dklen=32)
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:  # pragma: no cover
        raise ConfigError(
            "Не удалось расшифровать секрет: вероятно, изменён SECRET_KEY"
        ) from exc
