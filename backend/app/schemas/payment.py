"""Payment schemas."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, Field

from app.enums import PaymentStatus
from app.schemas.common import ORMModel

if TYPE_CHECKING:
    from app.models.payment import Payment


class PaymentRead(ORMModel):
    id: UUID
    provider: str
    provider_payment_id: str | None = None
    amount_kopeks: int
    currency: str
    description: str | None = None
    status: PaymentStatus
    confirmation_url: str | None = None
    paid_at: dt.datetime | None = None
    refunded_kopeks: int = 0
    subscription_id: UUID | None = None
    plan_id: UUID | None = None
    created_at: dt.datetime

    @property
    def is_paid(self) -> bool:
        return self.status == PaymentStatus.SUCCEEDED

    @classmethod
    def from_model(cls, payment: Payment) -> PaymentRead:
        return cls(
            id=payment.id,
            provider=payment.provider,
            provider_payment_id=payment.provider_payment_id,
            amount_kopeks=payment.amount_kopeks,
            currency=payment.currency,
            description=payment.description,
            status=payment.status,
            confirmation_url=payment.confirmation_url,
            paid_at=payment.paid_at,
            refunded_kopeks=payment.refunded_kopeks,
            subscription_id=payment.subscription_id,
            plan_id=payment.plan_id,
            created_at=payment.created_at,
        )


class CreatePaymentRequest(BaseModel):
    plan_id: UUID | None
    # Reuse of an in-flight order; generated server-side when omitted.
    idempotency_key: str | None = Field(None, max_length=64)


class CreatePaymentResponse(BaseModel):
    payment: PaymentRead
    confirmation_url: str | None = None
    # Where the user must go next (gateway checkout page).
    redirect_url: str | None = None
    already_paid: bool = False


class PaymentStatusResponse(BaseModel):
    payment: PaymentRead
    subscription_activated: bool = False
    message: str | None = None


class RefundRequest(BaseModel):
    amount_kopeks: int | None = Field(None, ge=1, description="None = полный возврат")
    reason: str | None = Field(None, max_length=255)
