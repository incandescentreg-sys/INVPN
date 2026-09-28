"""Payments: checkout, status polling, webhook receiver."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import ActiveUser, PaymentSvc, PlanSvc
from app.config import payment_settings
from app.enums import PaymentStatus, SubscriptionStatus
from app.logging_config import get_logger
from app.schemas.common import Message
from app.schemas.payment import (
    CreatePaymentRequest,
    CreatePaymentResponse,
    PaymentRead,
    PaymentStatusResponse,
)
from app.utils.exceptions import NotFoundError
from app.utils.ids import to_uuid

log = get_logger(__name__)
router = APIRouter(tags=["payments"])

@router.post("/payments", response_model=CreatePaymentResponse)
async def create_payment(
    payload: CreatePaymentRequest, user: ActiveUser, payments: PaymentSvc, plans: PlanSvc
) -> CreatePaymentResponse:
    """Create an order and return the gateway URL the Mini App should open."""
    try:
        plan = await plans.get(to_uuid(payload.plan_id))
    except ValueError as exc:
        raise NotFoundError("Тариф не найден") from exc

    if not plan.is_active:
        raise NotFoundError("Тариф недоступен")

    payment = await payments.create_payment(
        user=user, plan=plan, idempotency_key=payload.idempotency_key
    )
    return CreatePaymentResponse(
        payment=PaymentRead.from_model(payment),
        confirmation_url=payment.confirmation_url,
        redirect_url=payment.confirmation_url,
        already_paid=payment.status == PaymentStatus.SUCCEEDED,
    )

@router.get("/payments/{payment_id}", response_model=PaymentStatusResponse)
async def get_payment(
    payment_id: str, user: ActiveUser, payments: PaymentSvc
) -> PaymentStatusResponse:
    """Poll the gateway and activate access as soon as it reports success."""
    try:
        pid = to_uuid(payment_id)
    except ValueError as exc:
        raise NotFoundError("Платёж не найден") from exc

    payment = await payments.poll_status(pid)
    if payment.user_id != user.id and not user.is_admin:
        raise NotFoundError("Платёж не найден")

    activated = False
    if payment.status == PaymentStatus.SUCCEEDED and payment.subscription_id:
        subscription = await payments.get_subscription(payment)
        activated = bool(subscription and subscription.status == SubscriptionStatus.ACTIVE)

    messages = {
        PaymentStatus.PENDING: "Оплата ещё не получена",
        PaymentStatus.SUCCEEDED: "Оплата получена, VPN активен",
        PaymentStatus.FAILED: "Платёж не прошёл",
        PaymentStatus.CANCELLED: "Платёж отменён",
        PaymentStatus.REFUNDED: "Платёж возвращён",
        PaymentStatus.PARTIALLY_REFUNDED: "Платёж частично возвращён",
    }
    return PaymentStatusResponse(
        payment=PaymentRead.from_model(payment),
        subscription_activated=activated,
        message=messages.get(payment.status),
    )

@router.post("/payments/{payment_id}/check", response_model=PaymentStatusResponse)
async def check_payment(
    payment_id: str, user: ActiveUser, payments: PaymentSvc
) -> PaymentStatusResponse:
    """Explicit 'I returned from the gateway' hook (used by the Web App)."""
    return await get_payment(payment_id, user, payments)

@router.get("/payments", response_model=list[PaymentRead])
async def my_payments(user: ActiveUser, payments: PaymentSvc) -> list[PaymentRead]:
    rows = await payments.list_for_user(user.id)
    return [PaymentRead.from_model(p) for p in rows]

@router.post(
    "/webhooks/{provider}",
    include_in_schema=False,
)
async def payment_webhook(provider: str, request: Request, payments: PaymentSvc) -> Response:
    """Gateway callback.

    Always answers 200 for events we already processed or do not recognise —
    otherwise gateways retry forever and hammer the endpoint.
    """
    raw = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    if provider != payments.provider_name:
        log.warning("payment.webhook_provider_mismatch", got=provider, expected=payments.provider_name)
        return JSONResponse({"status": "ignored"}, status_code=status.HTTP_200_OK)

    try:
        payment = await payments.handle_webhook(raw, headers)
    except Exception as exc:
        log.error("payment.webhook_failed", provider=provider, error=str(exc)[:300])
        # 4xx tells the gateway the event will never succeed; 5xx triggers a retry.
        return JSONResponse({"status": "error", "detail": str(exc)[:200]}, status_code=400)

    return JSONResponse(
        {"status": "ok", "payment_id": str(payment.id) if payment else None, "status_final": payment.status.value if payment else None},
        status_code=status.HTTP_200_OK,
    )

@router.get("/payments/config", include_in_schema=False)
async def payment_config() -> Message:
    """Diagnostics helper for the Web App (provider name only, no secrets)."""
    return Message(detail=payment_settings.provider_display)