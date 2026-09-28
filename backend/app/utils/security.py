"""Authentication helpers.

Two flows:

1. Telegram Mini App — the client sends `initData` (a signed query string).
   We verify the HMAC exactly as Telegram documents it, then mint our own
   short-lived JWT so the rest of the API does not depend on Telegram payloads.

2. Internal / admin — same initData, plus a check against ADMIN_TELEGRAM_IDS.
   Service-to-service calls (Vercel Cron) use a separate shared secret.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl

import jwt

from app.config import app_settings, telegram_settings
from app.logging_config import get_logger
from app.utils.exceptions import AuthError
from app.utils.time import now

log = get_logger(__name__)

JWT_ALGORITHM = "HS256"


@dataclass(frozen=True, slots=True)
class TelegramUser:
    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    photo_url: str | None = None
    is_premium: bool = False
    allows_write_to_pm: bool | None = None
    auth_date: int | None = None

    @property
    def display_name(self) -> str:
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) or (f"@{self.username}" if self.username else str(self.id))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "username": self.username,
            "language_code": self.language_code,
            "photo_url": self.photo_url,
            "is_premium": self.is_premium,
        }


# --------------------------------------------------------------------------- #
# initData verification
# --------------------------------------------------------------------------- #
def verify_init_data(init_data: str, *, max_age: int | None = None) -> TelegramUser:
    """Validate Telegram Mini App `initData`.

    Reference: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    if not init_data:
        raise AuthError("initData пуст")

    token = telegram_settings.bot_token.get_secret_value()
    if not token:
        raise AuthError("BOT_TOKEN не настроен", code="bot_not_configured")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise AuthError("В initData отсутствует hash")

    # data_check_string: sorted "key=value" joined by \n (user excluded)
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))

    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        log.warning("telegram.init_data.invalid_hash")
        raise AuthError("Подпись initData неверна", code="invalid_init_data")

    raw_user = pairs.get("user")
    if not raw_user:
        raise AuthError("В initData нет пользователя")
    try:
        data: dict[str, Any] = json.loads(raw_user)
    except json.JSONDecodeError as exc:
        raise AuthError("user в initData повреждён") from exc

    auth_date = int(pairs["auth_date"]) if pairs.get("auth_date", "").isdigit() else None
    limit = max_age if max_age is not None else telegram_settings.init_data_max_age
    if limit and auth_date is not None:
        age = now().timestamp() - auth_date
        if age > limit:
            raise AuthError("Данные авторизации устарели, обновите приложение", code="init_data_expired")

    return TelegramUser(
        id=int(data["id"]),
        first_name=data.get("first_name"),
        last_name=data.get("last_name"),
        username=data.get("username"),
        language_code=data.get("language_code"),
        photo_url=data.get("photo_url"),
        is_premium=bool(data.get("is_premium", False)),
        allows_write_to_pm=data.get("allows_write_to_pm"),
        auth_date=auth_date,
    )


# --------------------------------------------------------------------------- #
# Our own API tokens
# --------------------------------------------------------------------------- #
def create_access_token(*, subject: str, telegram_id: int | None = None, is_admin: bool = False) -> str:
    issued = now()
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(issued.timestamp()),
        "exp": int((issued + dt.timedelta(minutes=app_settings.access_token_ttl_minutes)).timestamp()),
        "jti": secrets.token_urlsafe(8),
    }
    if telegram_id is not None:
        payload["tid"] = telegram_id
    if is_admin:
        payload["adm"] = True
    return jwt.encode(payload, app_settings.secret_key.get_secret_value(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            app_settings.secret_key.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Сессия истекла, войдите заново", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthError("Некорректный токен") from exc


# --------------------------------------------------------------------------- #
# Service-to-service (Vercel Cron, internal tooling)
# --------------------------------------------------------------------------- #
def verify_cron_secret(presented: str | None, expected: str | None) -> None:
    """Vercel sends ``Authorization: Bearer $CRON_SECRET`` on cron invocations."""
    if not expected:
        return  # protection disabled by configuration
    if not presented or not hmac.compare_digest(presented.strip(), expected.strip()):
        log.warning("cron.bad_secret")
        raise AuthError("Некорректный CRON_SECRET", code="bad_cron_secret")
