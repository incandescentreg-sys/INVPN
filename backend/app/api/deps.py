"""FastAPI dependencies: auth, service wiring, pagination."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import app_settings, telegram_settings
from app.database import get_db
from app.models.user import User
from app.repositories.user import UserRepository
from app.services.notification import NotificationService
from app.services.payment import PaymentService
from app.services.plan import PlanService
from app.services.server import ServerService
from app.services.stats import StatsService
from app.services.subscription import SubscriptionService
from app.services.user import UserService
from app.services.vpn import VpnService
from app.utils.exceptions import AuthError, ForbiddenError
from app.utils.security import create_access_token, decode_access_token, verify_cron_secret, verify_init_data

_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
async def get_current_user(
    request: Request,
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
    x_telegram_init_data: Annotated[str | None, Header()] = None,
) -> User:
    """Accepts a signed JWT *or* raw Telegram `initData` on every call."""
    user: User | None = None

    if credentials and credentials.scheme.lower() == "bearer":
        payload = decode_access_token(credentials.credentials)
        try:
            user_id = payload["sub"]
        except KeyError as exc:  # pragma: no cover
            raise AuthError("Токен не содержит идентификатор") from exc
        user = await UserRepository(session).get(_as_uuid(user_id))

    elif x_telegram_init_data:
        # The Mini App can also call the API straight from the browser.
        tg = verify_init_data(x_telegram_init_data)
        user = await UserRepository(session).get_by_telegram_id(tg.id)

    if user is None:
        raise AuthError("Требуется авторизация в Telegram")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_admin(user: CurrentUser) -> User:
    is_admin = user.is_admin or user.telegram_id in telegram_settings.admin_set
    if not is_admin:
        log_attempt(user)
        raise ForbiddenError("Недостаточно прав")
    return user


AdminUser = Annotated[User, Depends(get_current_admin)]


def log_attempt(user: User) -> None:
    from app.logging_config import get_logger

    get_logger("app.api.deps").warning(
        "auth.admin_denied", telegram_id=user.telegram_id, username=user.username
    )


async def ensure_not_banned(user: CurrentUser) -> User:
    if user.is_banned:
        raise ForbiddenError(user.ban_reason or "Доступ заблокирован")
    return user


ActiveUser = Annotated[User, Depends(ensure_not_banned)]


def issue_token(user: User) -> tuple[str, int]:
    token = create_access_token(
        subject=str(user.id),
        telegram_id=user.telegram_id,
        is_admin=user.is_admin or user.telegram_id in telegram_settings.admin_set,
    )
    return token, app_settings.access_token_ttl_minutes * 60


def require_cron_auth(
    authorization: Annotated[str | None, Header()] = None,
    x_cron_secret: Annotated[str | None, Header()] = None,
) -> None:
    """Guard for Vercel Cron and other service-to-service callers."""
    presented = x_cron_secret
    if not presented and authorization:
        presented = authorization.removeprefix("Bearer ").strip()
    verify_cron_secret(presented, app_settings.cron_secret.get_secret_value() or None)


CronAuth = Annotated[None, Depends(require_cron_auth)]


# --------------------------------------------------------------------------- #
# Services
# --------------------------------------------------------------------------- #
async def get_bot(request: Request) -> Any | None:
    return getattr(request.app.state, "bot", None)


def get_user_service(session: DbSession) -> UserService:
    return UserService(session)


def get_plan_service(session: DbSession) -> PlanService:
    return PlanService(session)


def get_server_service(session: DbSession) -> ServerService:
    return ServerService(session)


def get_subscription_service(session: DbSession) -> SubscriptionService:
    return SubscriptionService(session)


def get_vpn_service(session: DbSession) -> VpnService:
    return VpnService(session)


def get_payment_service(session: DbSession, request: Request) -> PaymentService:
    return PaymentService(session, bot=getattr(request.app.state, "bot", None))


def get_stats_service(session: DbSession) -> StatsService:
    return StatsService(session)


async def get_notification_service(
    session: DbSession, request: Request
) -> AsyncGenerator[NotificationService, None]:
    yield NotificationService(session, bot=getattr(request.app.state, "bot", None))


UserSvc = Annotated[UserService, Depends(get_user_service)]
PlanSvc = Annotated[PlanService, Depends(get_plan_service)]
ServerSvc = Annotated[ServerService, Depends(get_server_service)]
SubscriptionSvc = Annotated[SubscriptionService, Depends(get_subscription_service)]
VpnSvc = Annotated[VpnService, Depends(get_vpn_service)]
PaymentSvc = Annotated[PaymentService, Depends(get_payment_service)]
StatsSvc = Annotated[StatsService, Depends(get_stats_service)]
NotificationSvc = Annotated[NotificationService, Depends(get_notification_service)]


# --------------------------------------------------------------------------- #
# Query params
# --------------------------------------------------------------------------- #
class Pagination:
    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


PageParamsDep = Annotated[Pagination, Depends(Pagination)]


def _as_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise AuthError("Некорректный идентификатор") from exc
