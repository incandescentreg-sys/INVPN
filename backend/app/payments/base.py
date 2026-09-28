"""Payment provider abstraction.

Business logic depends only on this interface, so swapping or adding a gateway
touches nothing outside `app/payments/` and `PAYMENT_PROVIDER`.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.enums import PaymentStatus


@dataclass(frozen=True, slots=True)
class PaymentIntent:
    """What the user must do next (usually: open `confirmation_url`)."""

    provider: str
    provider_payment_id: str
    amount_kopeks: int
    currency: str
    status: PaymentStatus = PaymentStatus.PENDING
    confirmation_url: str | None = None
    expires_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_paid(self) -> bool:
        return self.status == PaymentStatus.SUCCEEDED


@dataclass(frozen=True, slots=True)
class RefundResult:
    provider: str
    provider_refund_id: str | None
    amount_kopeks: int
    status: PaymentStatus
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in (PaymentStatus.REFUNDED, PaymentStatus.PARTIALLY_REFUNDED)


@dataclass(frozen=True, slots=True)
class WebhookEvent:
    """A normalised gateway callback."""

    provider: str
    provider_payment_id: str
    status: PaymentStatus
    event_type: str
    amount_kopeks: int | None = None
    signature_valid: bool = True
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CreatePaymentRequest:
    amount_kopeks: int
    currency: str
    description: str
    # Internal order id — used as the gateway's idempotency key.
    idempotency_key: str
    return_url: str
    metadata: Mapping[str, str] = field(default_factory=dict)
    email: str | None = None
    # Optional: how long the gateway should keep the payment open.
    expires_in_seconds: int = 1800


class PaymentProvider(abc.ABC):
    """Gateway contract: create / check / refund (+ webhook parsing)."""

    name: ClassVar[str] = "base"
    display_name: ClassVar[str] = "Base"

    @abc.abstractmethod
    async def create_payment(self, request: CreatePaymentRequest) -> PaymentIntent:
        """Create a payment and return the URL the user must open."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_status(self, provider_payment_id: str) -> PaymentIntent:
        """Poll the gateway for the current state of a payment."""
        raise NotImplementedError

    @abc.abstractmethod
    async def refund(self, provider_payment_id: str, amount_kopeks: int | None = None) -> RefundResult:
        """Refund a payment fully (`amount_kopeks=None`) or partially."""
        raise NotImplementedError

    async def verify_webhook(
        self, payload: bytes, headers: Mapping[str, str]
    ) -> WebhookEvent:
        """Verify and normalise an incoming callback."""
        raise NotImplementedError(f"{self.name} does not support webhooks")

    async def health(self) -> bool:
        """Cheap reachability check used by /health."""
        return True

    def supports_webhooks(self) -> bool:
        return type(self).verify_webhook is not PaymentProvider.verify_webhook


def normalize_status(value: str | None) -> PaymentStatus:
    """Map a gateway-specific status string onto our enum.

    Gateways disagree wildly here, so every provider funnels through this.
    """
    if not value:
        return PaymentStatus.PENDING
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")

    if normalized in {"succeeded", "success", "paid", "complete", "completed", "confirmed", "ok", "done"}:
        return PaymentStatus.SUCCEEDED
    if normalized in {"pending", "waiting", "new", "created", "processing", "in_progress", "authorized"}:
        return PaymentStatus.PENDING
    if normalized in {"failed", "error", "declined", "rejected", "cancel", "cancelled", "canceled", "expired"}:
        if normalized in {"cancel", "cancelled", "canceled"}:
            return PaymentStatus.CANCELLED
        if normalized == "expired":
            return PaymentStatus.CANCELLED
        return PaymentStatus.FAILED
    if normalized in {"refunded", "refund"}:
        return PaymentStatus.REFUNDED
    if normalized in {"partially_refunded", "partial_refund"}:
        return PaymentStatus.PARTIALLY_REFUNDED
    return PaymentStatus.PENDING


def to_kopeks(value: Any) -> int | None:
    """Normalise a gateway amount to kopeks.

    Gateways are inconsistent, so the rule is explicit:
      * ``str`` / ``float``  -> major units (rubles): ``"299.00"`` and ``"299"``
        both mean 299 ₽ = 29900 kopeks;
      * ``int``              -> already minor units, returned unchanged.

    Anything unparseable yields ``None`` and the caller treats the amount as
    unknown rather than guessing.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value * 100)
    text = str(value).strip().replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        return round(float(text) * 100)
    except ValueError:
        return None
