"""Admin: tariffs, subscriptions, payments."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import AdminUser, DbSession, PaymentSvc, PlanSvc, SubscriptionSvc
from app.enums import PaymentStatus, SubscriptionStatus
from app.logging_config import get_logger
from app.repositories.payment import PaymentRepository
from app.repositories.user import UserRepository
from app.schemas.common import Message
from app.schemas.plan import PlanCreate, PlanRead, PlanUpdate
from app.schemas.subscription import ExtendDaysRequest, SetExpiryRequest, SubscriptionRead
from app.utils.exceptions import NotFoundError
from app.utils.ids import to_uuid

log = get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------- plans ---- #
@router.get("/plans")
async def admin_plans(admin: AdminUser, plans: PlanSvc) -> list[PlanRead]:
    return [PlanRead.model_validate(p) for p in await plans.list_all()]

@router.post("/plans", response_model=PlanRead, status_code=201)
async def create_plan(payload: PlanCreate, admin: AdminUser, plans: PlanSvc) -> PlanRead:
    try:
        plan = await plans.create(**payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc
    return PlanRead.model_validate(plan)

@router.patch("/plans/{plan_id}", response_model=PlanRead)
async def update_plan(
    plan_id: str, payload: PlanUpdate, admin: AdminUser, plans: PlanSvc
) -> PlanRead:
    plan = await plans.update(
        to_uuid(plan_id), **payload.model_dump(exclude_none=True)
    )
    return PlanRead.model_validate(plan)

@router.delete("/plans/{plan_id}", response_model=Message)
async def deactivate_plan(plan_id: str, admin: AdminUser, plans: PlanSvc) -> Message:
    await plans.set_active(to_uuid(plan_id), False)
    return Message(detail="Тариф отключён")

# -------------------------------------------------------- subscriptions ---- #
@router.get("/subscriptions")
async def list_subscriptions(
    admin: AdminUser,
    subscriptions: SubscriptionSvc,
    status: SubscriptionStatus | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    rows = await subscriptions.list_all(status=status, limit=limit, offset=offset)
    return {
        "items": [SubscriptionRead.from_model(s).model_dump() for s in rows],
        "limit": limit,
        "offset": offset,
    }

@router.post("/subscriptions/{subscription_id}/extend", response_model=SubscriptionRead)
async def extend_subscription(
    subscription_id: str, payload: ExtendDaysRequest, admin: AdminUser, subscriptions: SubscriptionSvc
) -> SubscriptionRead:
    sub = await subscriptions.get(to_uuid(subscription_id))
    await subscriptions.extend(sub, payload.days)
    log.info("admin.subscription_extended", subscription_id=subscription_id, days=payload.days)
    return SubscriptionRead.from_model(sub)

@router.post("/subscriptions/{subscription_id}/expiry", response_model=SubscriptionRead)
async def set_expiry(
    subscription_id: str, payload: SetExpiryRequest, admin: AdminUser, subscriptions: SubscriptionSvc
) -> SubscriptionRead:
    sub = await subscriptions.get(to_uuid(subscription_id))
    await subscriptions.set_expiry(sub, expires_at=payload.expires_at)
    return SubscriptionRead.from_model(sub)

@router.post("/subscriptions/{subscription_id}/suspend", response_model=Message)
async def suspend_subscription(
    subscription_id: str, admin: AdminUser, subscriptions: SubscriptionSvc, reason: str = Query("")
) -> Message:
    sub = await subscriptions.get(to_uuid(subscription_id))
    await subscriptions.suspend(sub, reason=reason)
    return Message(detail="Подписка приостановлена")

@router.post("/subscriptions/{subscription_id}/reactivate", response_model=SubscriptionRead)
async def reactivate_subscription(
    subscription_id: str, admin: AdminUser, subscriptions: SubscriptionSvc
) -> SubscriptionRead:
    sub = await subscriptions.get(to_uuid(subscription_id))
    await subscriptions.reactivate(sub)
    return SubscriptionRead.from_model(sub)

@router.post("/subscriptions/grant", response_model=SubscriptionRead)
async def grant_subscription(
    admin: AdminUser,
    subscriptions: SubscriptionSvc,
    plans: PlanSvc,
    session: DbSession,
    user_id: str = Query(..., description="id пользователя"),
    plan_id: str = Query(..., description="id тарифа"),
    days: int = Query(30, ge=1, le=3650),
) -> SubscriptionRead:
    """Compensatory / test grant — no payment involved."""
    user = await UserRepository(session).get(to_uuid(user_id))
    if user is None:
        raise NotFoundError("Пользователь не найден")
    plan = await plans.get(to_uuid(plan_id))
    sub = await subscriptions.grant(user=user, plan=plan, days=days, actor=f"admin:{admin.telegram_id}")
    log.info("admin.subscription_granted", target=str(user.id), days=days, by=admin.telegram_id)
    return SubscriptionRead.from_model(sub)

# ------------------------------------------------------------- payments ---- #
@router.get("/payments")
async def list_payments(
    admin: AdminUser,
    session: DbSession,
    status: PaymentStatus | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    rows = await PaymentRepository(session).list_all(status=status, limit=limit, offset=offset)
    return {
        "items": [
            {
                "id": str(p.id),
                "user_id": str(p.user_id),
                "username": p.user.username if p.user else None,
                "amount_kopeks": p.amount_kopeks,
                "currency": p.currency,
                "status": str(p.status),
                "provider": p.provider,
                "description": p.description,
                "created_at": p.created_at.isoformat(),
                "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            }
            for p in rows
        ],
        "limit": limit,
        "offset": offset,
    }

@router.post("/payments/{payment_id}/refund", response_model=Message)
async def refund_payment(
    payment_id: str,
    admin: AdminUser,
    payments: PaymentSvc,
    amount_kopeks: int | None = Query(None, ge=1),
) -> Message:
    payment = await payments.refund(
        to_uuid(payment_id), amount_kopeks=amount_kopeks, actor=f"admin:{admin.telegram_id}"
    )
    return Message(detail=f"Возврат выполнен: {payment.refunded_kopeks / 100:.2f} {payment.currency}")