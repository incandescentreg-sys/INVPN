"""Application configuration.

Everything comes from environment / .env — nothing is hardcoded.

Every field declares aliases so that BOTH naming styles work:
  * flat, as required by the spec:  DATABASE_URL, BOT_TOKEN, SERVER_HOST, ...
  * nested, for grouped overrides:   DB__URL,     TELEGRAM__BOT_TOKEN, ...

`env_aliases("DATABASE_URL", "DB__URL")` builds the AliasChoices pair.
Nested groups stay available via `settings.db`, `settings.telegram`, ... so
call-sites read nicely while the .env file stays flat and greppable.
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
ENV_FILES = (PROJECT_DIR / ".env", BACKEND_DIR / ".env")

AppEnv = Literal["local", "staging", "production"]
XrayReloadMode = Literal["restart", "reload-sighup"]
ThemeMode = Literal["auto", "light", "dark"]


def env_aliases(*names: str) -> AliasChoices:
    """Accept a field under any of the given env var names (first is canonical)."""
    return AliasChoices(*names)


class BaseEnv(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )


def _csv(value: object) -> object:
    """Parse a comma separated string into a list, pass lists through."""
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


class AppSettings(BaseEnv):
    name: str = Field("VPN Service", validation_alias=env_aliases("APP_NAME"))
    env: AppEnv = Field("local", validation_alias=env_aliases("APP_ENV"))
    debug: bool = Field(False, validation_alias=env_aliases("DEBUG"))
    api_base_path: str = Field("/api/v1", validation_alias=env_aliases("API_BASE_PATH"))
    secret_key: SecretStr = Field(
        SecretStr("CHANGE_ME_random_32_chars_min"), validation_alias=env_aliases("SECRET_KEY")
    )
    access_token_ttl_minutes: int = Field(720, validation_alias=env_aliases("ACCESS_TOKEN_TTL_MINUTES"))
    log_level: str = Field("INFO", validation_alias=env_aliases("LOG_LEVEL"))
    log_json: bool = Field(True, validation_alias=env_aliases("LOG_JSON"))
    sentry_dsn: str = Field("", validation_alias=env_aliases("SENTRY_DSN"))
    # Vercel sets this automatically and sends it as `Authorization: Bearer <CRON_SECRET>`
    # on every cron invocation. Empty = cron endpoints stay unauthenticated.
    cron_secret: SecretStr = Field(SecretStr(""), validation_alias=env_aliases("CRON_SECRET"))
    api_title: str = Field("VPN Service API", validation_alias=env_aliases("API_TITLE"))
    api_version: str = Field("1.0.0", validation_alias=env_aliases("API_VERSION"))
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list, validation_alias=env_aliases("CORS_ORIGINS"))
    rate_limit_per_minute: int = Field(120, validation_alias=env_aliases("RATE_LIMIT_PER_MINUTE"))

    _csv_validator = field_validator("cors_origins", mode="before")(_csv)

    @model_validator(mode="after")
    def _guard_secrets(self) -> AppSettings:
        if self.env == "production" and self.secret_key.get_secret_value().startswith("CHANGE_ME"):
            raise ValueError("SECRET_KEY must be set to a random value in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.env == "production"


class DatabaseSettings(BaseEnv):
    url: str = Field(
        "postgresql+asyncpg://vpn:vpn@localhost:5432/vpn",
        validation_alias=env_aliases("DATABASE_URL", "DB__URL"),
    )
    echo: bool = Field(False, validation_alias=env_aliases("DB_ECHO", "DB__ECHO"))
    pool_size: int = Field(10, validation_alias=env_aliases("DB_POOL_SIZE", "DB__POOL_SIZE"))
    max_overflow: int = Field(20, validation_alias=env_aliases("DB_MAX_OVERFLOW", "DB__MAX_OVERFLOW"))
    pool_pre_ping: bool = Field(True, validation_alias=env_aliases("DB_POOL_PRE_PING", "DB__POOL_PRE_PING"))
    pool_recycle: int = Field(1800, validation_alias=env_aliases("DB_POOL_RECYCLE", "DB__POOL_RECYCLE"))

    @property
    def sync_url(self) -> str:
        """Synchronous DSN — required by Alembic."""
        return self.url.replace("+asyncpg", "").replace("+aiosqlite", "")


class RedisSettings(BaseEnv):
    url: str = Field("", validation_alias=env_aliases("REDIS_URL", "REDIS__URL"))

    @property
    def enabled(self) -> bool:
        return bool(self.url)


class SshSettings(BaseEnv):
    """SSH access to the VPN host running Xray (H1Cloud VPS)."""

    host: str = Field("", validation_alias=env_aliases("SERVER_HOST", "SERVER__HOST", "SSH__HOST"))
    port: int = Field(22, validation_alias=env_aliases("SERVER_PORT", "SERVER__PORT", "SSH__PORT"))
    user: str = Field("root", validation_alias=env_aliases("SERVER_USER", "SERVER__USER", "SSH__USER"))
    key: SecretStr = Field(SecretStr(""), validation_alias=env_aliases("SERVER_SSH_KEY", "SERVER__SSH_KEY", "SSH__KEY"))
    passphrase: SecretStr = Field(
        SecretStr(""), validation_alias=env_aliases("SERVER_SSH_PASSPHRASE", "SERVER__SSH_PASSPHRASE")
    )
    # Pinning the host key prevents MITM even if DNS is hijacked.
    host_key_sha256: str = Field(
        "", validation_alias=env_aliases("SERVER_SSH_HOST_KEY_SHA256", "SERVER__SSH_HOST_KEY_SHA256")
    )
    known_hosts: str = Field("", validation_alias=env_aliases("SERVER_SSH_KNOWN_HOSTS"))
    timeout: int = Field(20, validation_alias=env_aliases("SERVER_SSH_TIMEOUT", "SSH__TIMEOUT"))
    connect_retries: int = Field(3, validation_alias=env_aliases("SSH__CONNECT_RETRIES"))

    @model_validator(mode="after")
    def _require_credentials(self) -> SshSettings:
        if self.host and not self.key.get_secret_value().strip():
            raise ValueError("SERVER_SSH_KEY is required when SERVER_HOST is set")
        return self

    @property
    def configured(self) -> bool:
        return bool(self.host and self.key.get_secret_value().strip())


class XraySettings(BaseEnv):
    config_path: str = Field(
        "/usr/local/etc/xray/config.json", validation_alias=env_aliases("XRAY_CONFIG_PATH", "XRAY__CONFIG_PATH")
    )
    service_name: str = Field("xray", validation_alias=env_aliases("XRAY_SERVICE_NAME", "XRAY__SERVICE_NAME"))
    reload_mode: XrayReloadMode = Field(
        "restart", validation_alias=env_aliases("XRAY_RELOAD_MODE", "XRAY__RELOAD_MODE")
    )
    binary: str = Field("xray", validation_alias=env_aliases("XRAY_BINARY", "XRAY__BINARY"))
    inbound_tag: str = Field("inbound-vless", validation_alias=env_aliases("XRAY_INBOUND_TAG"))
    listen: str = Field("0.0.0.0", validation_alias=env_aliases("XRAY_LISTEN"))
    work_dir: str = Field("/usr/local/share/xray", validation_alias=env_aliases("XRAY_WORK_DIR"))

    # REALITY
    reality_target: str = Field(
        "www.microsoft.com:443", validation_alias=env_aliases("REALITY_TARGET", "XRAY__REALITY_TARGET")
    )
    reality_server_names: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["www.microsoft.com"],
        validation_alias=env_aliases("REALITY_SERVER_NAMES", "XRAY__REALITY_SERVER_NAMES"),
    )
    reality_short_ids: Annotated[list[str], NoDecode] = Field(
        default_factory=list, validation_alias=env_aliases("REALITY_SHORT_IDS", "XRAY__REALITY_SHORT_IDS")
    )
    reality_fingerprint: str = Field("chrome", validation_alias=env_aliases("REALITY_FINGERPRINT"))
    reality_sni_strict: bool = Field(False, validation_alias=env_aliases("REALITY_SNI_STRICT"))

    _csv_validator = field_validator("reality_server_names", "reality_short_ids", mode="before")(_csv)

    @property
    def server_name(self) -> str:
        return self.reality_server_names[0] if self.reality_server_names else "www.microsoft.com"


class VpnPublicSettings(BaseEnv):
    """Values that end up in the client link — must be public."""

    domain: str = Field("", validation_alias=env_aliases("VPN_DOMAIN", "VPN_PUBLIC__DOMAIN"))
    port: int = Field(443, validation_alias=env_aliases("VPN_PORT", "VPN_PUBLIC__PORT"))


class TelegramSettings(BaseEnv):
    bot_token: SecretStr = Field(SecretStr(""), validation_alias=env_aliases("BOT_TOKEN", "TELEGRAM__BOT_TOKEN"))
    webapp_url: str = Field("", validation_alias=env_aliases("WEBAPP_URL", "TELEGRAM__WEBAPP_URL"))
    webapp_short_name: str = Field("app", validation_alias=env_aliases("WEBAPP_SHORT_NAME"))
    admin_telegram_ids: Annotated[list[int], NoDecode] = Field(
        default_factory=list, validation_alias=env_aliases("ADMIN_TELEGRAM_IDS", "TELEGRAM__ADMIN_TELEGRAM_IDS")
    )
    support_username: str = Field("", validation_alias=env_aliases("SUPPORT_USERNAME"))
    bot_name: str = Field("VPN Bot", validation_alias=env_aliases("BOT_NAME"))
    theme_default: ThemeMode = Field("auto", validation_alias=env_aliases("WEBAPP_THEME_DEFAULT"))
    init_data_max_age: int = Field(86400, validation_alias=env_aliases("INIT_DATA_MAX_AGE"))

    @field_validator("admin_telegram_ids", mode="before")
    @classmethod
    def _parse_ids(cls, v: object) -> object:
        parsed = _csv(v)
        if isinstance(parsed, list):
            return [int(i) for i in parsed if str(i).lstrip("-").isdigit()]
        return parsed

    @property
    def admin_set(self) -> set[int]:
        return set(self.admin_telegram_ids)

    @property
    def configured(self) -> bool:
        return bool(self.bot_token.get_secret_value().strip())


class PaymentSettings(BaseEnv):
    provider: str = Field("mock", validation_alias=env_aliases("PAYMENT_PROVIDER"))
    token: SecretStr = Field(SecretStr(""), validation_alias=env_aliases("PAYMENT_TOKEN"))
    currency: str = Field("RUB", validation_alias=env_aliases("CURRENCY"))
    return_url: str = Field("", validation_alias=env_aliases("PAYMENT_RETURN_URL"))
    http_timeout: int = Field(20, validation_alias=env_aliases("PAYMENT_HTTP_TIMEOUT"))

    # -- mock (локальная разработка / тесты) --
    mock_auto_confirm: bool = Field(False, validation_alias=env_aliases("MOCK_PAYMENT_AUTO_CONFIRM"))
    mock_return_url: str = Field("", validation_alias=env_aliases("MOCK_PAYMENT_RETURN_URL"))

    # -- Rollypay --
    # Пути вынесены в .env: в документации Rollypay они могут отличаться,
    # а домен api.rollypay.com недоступен из некоторых сетей. Проверьте значения
    # в разделе 9 и при необходимости скорректируйте тут.
    rollypay_api_url: str = Field("https://api.rollypay.com/v1", validation_alias=env_aliases("ROLLYPAY_API_URL"))
    rollypay_create_path: str = Field("/goods/create", validation_alias=env_aliases("ROLLYPAY_CREATE_PATH"))
    rollypay_status_path: str = Field("/goods/info", validation_alias=env_aliases("ROLLYPAY_STATUS_PATH"))
    rollypay_refund_path: str = Field("/goods/refund", validation_alias=env_aliases("ROLLYPAY_REFUND_PATH"))
    rollypay_webhook_path: str = Field("/hook/rollypay", validation_alias=env_aliases("ROLLYPAY_WEBHOOK_PATH"))
    rollypay_shop_id: str = Field("", validation_alias=env_aliases("ROLLYPAY_SHOP_ID"))
    rollypay_signature_header: str = Field("signature", validation_alias=env_aliases("ROLLYPAY_SIGNATURE_HEADER"))

    @model_validator(mode="after")
    def _check(self) -> PaymentSettings:
        allowed = {"mock", "rollypay"}
        if self.provider not in allowed:
            raise ValueError(f"PAYMENT_PROVIDER must be one of {sorted(allowed)}, got {self.provider!r}")
        if self.provider == "rollypay" and not self.token.get_secret_value().strip():
            raise ValueError("PAYMENT_TOKEN is required for PAYMENT_PROVIDER=rollypay")
        return self

    @property
    def webhook_path(self) -> str:
        return {
            "rollypay": self.rollypay_webhook_path,
            "mock": "/hook/mock",
        }.get(self.provider, "/hook/unknown")

    @property
    def provider_display(self) -> str:
        return {"mock": "Mock (тестовый)", "rollypay": "Rollypay"}.get(self.provider, self.provider)


class PlanSeedSettings(BaseEnv):
    seed_on_startup: bool = Field(True, validation_alias=env_aliases("SEED_PLANS_ON_STARTUP"))
    plan_30d_title: str = Field("VPN 30 дней", validation_alias=env_aliases("SEED_PLAN_30D_TITLE"))
    plan_30d_days: int = Field(30, validation_alias=env_aliases("SEED_PLAN_30D_DAYS"))
    plan_30d_price: int = Field(29900, validation_alias=env_aliases("SEED_PLAN_30D_PRICE"))


class WorkerSettings(BaseEnv):
    expiry_check_interval: int = Field(300, validation_alias=env_aliases("WORKER_EXPIRY_CHECK_INTERVAL"))
    xray_sync_interval: int = Field(120, validation_alias=env_aliases("WORKER_XRAY_SYNC_INTERVAL"))
    notify_interval: int = Field(3600, validation_alias=env_aliases("WORKER_NOTIFY_INTERVAL"))
    payment_reconcile_interval: int = Field(120, validation_alias=env_aliases("WORKER_PAYMENT_RECONCILE_INTERVAL"))
    health_check_interval: int = Field(300, validation_alias=env_aliases("WORKER_HEALTH_CHECK_INTERVAL"))
    expiry_notify_days: Annotated[list[int], NoDecode] = Field(
        default_factory=lambda: [3, 1, 0], validation_alias=env_aliases("EXPIRY_NOTIFY_DAYS")
    )
    stale_grace_minutes: int = Field(10, validation_alias=env_aliases("XRAY_STALE_GRACE_MINUTES"))

    _csv_validator = field_validator("expiry_notify_days", mode="before")(_csv)


class Settings(BaseEnv):
    """Top level container. Groups are also reachable as flat attributes."""

    app: AppSettings = Field(default_factory=AppSettings)
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    ssh: SshSettings = Field(default_factory=SshSettings)
    xray: XraySettings = Field(default_factory=XraySettings)
    vpn_public: VpnPublicSettings = Field(default_factory=VpnPublicSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    payment: PaymentSettings = Field(default_factory=PaymentSettings)
    plan_seed: PlanSeedSettings = Field(default_factory=PlanSeedSettings)
    workers: WorkerSettings = Field(default_factory=WorkerSettings)

    model_config = SettingsConfigDict(env_nested_delimiter="__", extra="ignore", populate_by_name=True)


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# Flat aliases — the common import used across the codebase.
app_settings = settings.app
db_settings = settings.db
redis_settings = settings.redis
ssh_settings = settings.ssh
xray_settings = settings.xray
vpn_public_settings = settings.vpn_public
telegram_settings = settings.telegram
payment_settings = settings.payment
plan_seed_settings = settings.plan_seed
worker_settings = settings.workers
