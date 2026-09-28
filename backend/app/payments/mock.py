"""In-process payment provider for local development and tests.

No network, no secrets. `MOCK_PAYMENT_AUTO_CONFIRM=true` settles a payment as
soon as it is created, which lets the full purchase flow be exercised end to end
without a real gateway.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from collections.abc import Mapping
from typing import Any

from app.config import payment_settings
from app.enums import PaymentStatus
from app.payments.base import (
    CreatePaymentRequest,
    PaymentIntent,
    PaymentProvider,
    RefundResult,
    WebhookEvent,
)

# Simulated gateway state. On serverless this resets between invocations, which
# is exactly why the mock is only used in local/dev/test environments.
_STORE: dict[str, dict[str, Any]] = {}


class MockPaymentProvider(PaymentProvider):
    name = "mock"
    display_name = "Mock (тестовый)"

    async def create_payment(self, request: CreatePaymentRequest) -> PaymentIntent:
        payment_id = f"mock_{uuid.uuid4().hex[:16]}"
        return_url = payment_settings.mock_return_url or request.return_url
        status = (
            PaymentStatus.SUCCEEDED if payment_settings.mock_auto_confirm else PaymentStatus.PENDING
        )
        record: dict[str, Any] = {
            "id": payment_id,
            "status": status,
            "amount": f"{request.amount_kopeks / 100:.2f}",
            "currency": request.currency,
            "description": request.description,
            "idempotency_key": request.idempotency_key,
        }
        _STORE[payment_id] = record

        if status == PaymentStatus.SUCCEEDED:
            # Real gateways redirect to a hosted page first; keep that shape so
            # the Web App flow is identical in both modes.
            confirmation_url = f"{return_url}?mock_status=succeeded&mock_id={payment_id}"
        else:
            confirmation_url = (
                f"{return_url}?mock_status=pending&mock_id={payment_id}"
                f"&confirm=1"
            )
        return PaymentIntent(
            provider=self.name,
            provider_payment_id=payment_id,
            amount_kopeks=request.amount_kopeks,
            currency=request.currency,
            status=status,
            confirmation_url=confirmation_url,
            raw=record,
        )

    async def get_status(self, provider_payment_id: str) -> PaymentIntent:
        record = _STORE.get(provider_payment_id)
        if record is None:
            return PaymentIntent(
                provider=self.name,
                provider_payment_id=provider_payment_id,
                amount_kopeks=0,
                currency="RUB",
                status=PaymentStatus.FAILED,
                raw={"error": "not_found"},
            )
        return PaymentIntent(
            provider=self.name,
            provider_payment_id=provider_payment_id,
            amount_kopeks=int(float(record["amount"]) * 100),
            currency=record["currency"],
            status=record["status"],
            raw=record,
        )

    async def confirm(self, provider_payment_id: str) -> PaymentIntent:
        """Test/demo helper: settle a pending payment."""
        record = _STORE.get(provider_payment_id)
        if record is None:
            raise KeyError(provider_payment_id)
        record["status"] = PaymentStatus.SUCCEEDED
        return await self.get_status(provider_payment_id)

    async def refund(
        self, provider_payment_id: str, amount_kopeks: int | None = None
    ) -> RefundResult:
        record = _STORE.get(provider_payment_id)
        if record is None:
            return RefundResult(
                provider=self.name,
                provider_refund_id=None,
                amount_kopeks=0,
                status=PaymentStatus.FAILED,
                raw={"error": "not_found"},
            )
        record["status"] = PaymentStatus.REFUNDED
        return RefundResult(
            provider=self.name,
            provider_refund_id=f"mockref_{secrets.token_hex(8)}",
            amount_kopeks=amount_kopeks or int(float(record["amount"]) * 100),
            status=PaymentStatus.REFUNDED,
            raw=record,
        )

    async def verify_webhook(self, payload: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        # The mock webhook is a plain JSON POST from the browser after redirect.
        data = json.loads(payload or b"{}")
        payment_id = str(data.get("mock_id") or data.get("payment_id") or "")
        status = normalize_mock_status(data.get("mock_status") or data.get("status"))
        if payment_id:
            record = _STORE.get(payment_id)
            if record is not None and status == PaymentStatus.SUCCEEDED:
                record["status"] = PaymentStatus.SUCCEEDED
        return WebhookEvent(
            provider=self.name,
            provider_payment_id=payment_id,
            status=status,
            event_type=f"payment.{status}",
            amount_kopeks=int(float(data["amount"]) * 100) if data.get("amount") else None,
            signature_valid=True,
            raw=data,
        )


def normalize_mock_status(value: Any) -> PaymentStatus:
    return PaymentStatus.SUCCEEDED if str(value) in {"succeeded", "success", "paid"} else PaymentStatus.PENDING


def mock_signature(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
