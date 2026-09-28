"""Admin: dashboard and users."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import AdminUser, DbSession, StatsSvc, UserSvc
from app.logging_config import get_logger
from app.repositories.user import UserRepository
from app.schemas.common import Message
from app.schemas.user import UserRead
from app.utils.exceptions import NotFoundError
from app.utils.ids import to_uuid

log = get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/stats")
async def stats(admin: AdminUser, stats_svc: StatsSvc) -> dict:
    return await stats_svc.dashboard()

@router.get("/users")
async def list_users(
    admin: AdminUser,
    session: DbSession,
    search: str | None = Query(None, max_length=128),
    is_banned: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    repo = UserRepository(session)
    users = await repo.list(search=search, is_banned=is_banned, limit=limit, offset=offset)
    total = await repo.count(search=search, is_banned=is_banned)
    return {
        "items": [UserRead.from_model(u).model_dump() for u in users],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

@router.get("/users/{user_id}")
async def get_user(user_id: str, admin: AdminUser, session: DbSession, users: UserSvc) -> dict:
    uid = to_uuid(user_id)
    user = await users.get(uid)
    if user is None:
        raise NotFoundError("Пользователь не найден")

    from app.repositories.payment import PaymentRepository
    from app.repositories.subscription import SubscriptionRepository

    subs = await SubscriptionRepository(session).list_by_user(uid, limit=20)
    payments = await PaymentRepository(session).list_all(user_id=uid, limit=20)
    return {
        "user": UserRead.from_model(user).model_dump(),
        "subscriptions": [
            {
                "id": str(s.id),
                "status": str(s.status),
                "plan": s.plan.title,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "expires_at": s.expires_at.isoformat() if s.expires_at else None,
                "days_left": s.days_left,
            }
            for s in subs
        ],
        "payments": [
            {
                "id": str(p.id),
                "status": str(p.status),
                "amount_kopeks": p.amount_kopeks,
                "provider": p.provider,
                "created_at": p.created_at.isoformat(),
                "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            }
            for p in payments
        ],
        "revenue_kopeks": user.successful_payments_total(),
    }

@router.post("/users/{user_id}/ban", response_model=Message)
async def ban_user(
    user_id: str, admin: AdminUser, session: DbSession, reason: str | None = Query(None, max_length=255)
) -> Message:
    uid = to_uuid(user_id)
    repo = UserRepository(session)
    user = await repo.set_ban(uid, True, reason)
    if user is None:
        raise NotFoundError("Пользователь не найден")
    log.info("admin.user_banned", target=str(uid), by=admin.telegram_id)
    return Message(detail=f"Пользователь {user.display_name} заблокирован")

@router.post("/users/{user_id}/unban", response_model=Message)
async def unban_user(user_id: str, admin: AdminUser, session: DbSession) -> Message:
    uid = to_uuid(user_id)
    user = await UserRepository(session).set_ban(uid, False)
    if user is None:
        raise NotFoundError("Пользователь не найден")
    return Message(detail=f"Пользователь {user.display_name} разблокирован")

@router.post("/users/{user_id}/admin", response_model=Message)
async def toggle_admin(user_id: str, admin: AdminUser, session: DbSession) -> Message:
    uid = to_uuid(user_id)
    user = await UserRepository(session).get(uid)
    if user is None:
        raise NotFoundError("Пользователь не найден")
    updated = await UserRepository(session).set_admin(uid, not user.is_admin)
    state = "администратором" if updated and updated.is_admin else "обычным пользователем"  # type: ignore[union-attr]
    return Message(detail=f"Пользователь {updated.display_name} теперь {state}")  # type: ignore[union-attr]