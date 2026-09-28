"""Domain enums, shared by models, schemas and services."""

from __future__ import annotations

from enum import StrEnum


class SubscriptionStatus(StrEnum):
    PENDING = "pending"      # оплата получена, клиент ещё не выдан
    ACTIVE = "active"
    EXPIRED = "expired"
    SUSPENDED = "suspended"  # вручную отключён админом
    CANCELLED = "cancelled"


class ClientStatus(StrEnum):
    PENDING = "pending"      # записан в БД, ещё не применён к Xray
    ACTIVE = "active"        # есть в конфиге Xray
    DISABLED = "disabled"    # удалён из конфига Xray
    ERROR = "error"          # последняя синхронизация провалилась


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class PaymentProviderName(StrEnum):
    MOCK = "mock"
    ROLLYPAY = "rollypay"


class NotificationKind(StrEnum):
    SUBSCRIPTION_EXPIRING = "subscription_expiring"
    SUBSCRIPTION_EXPIRED = "subscription_expired"
    SUBSCRIPTION_RENEWED = "subscription_renewed"
    PAYMENT_SUCCESS = "payment_success"
    PAYMENT_FAILED = "payment_failed"
    NEW_DEVICE = "new_device"
    DEVICE_REVOKED = "device_revoked"
    WELCOME = "welcome"


class NotificationChannel(StrEnum):
    TELEGRAM = "telegram"
    WEBAPP = "webapp"


class HealthStatus(StrEnum):
    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"
