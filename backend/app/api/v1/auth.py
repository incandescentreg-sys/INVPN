"""Auth: exchange Telegram initData for an API token."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import ActiveUser, CurrentUser, UserSvc, issue_token
from app.schemas.user import AuthResponse, ProfileUpdate, TelegramAuthRequest, UserRead
from app.utils.security import verify_init_data

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/telegram", response_model=AuthResponse, status_code=status.HTTP_200_OK)
async def telegram_auth(payload: TelegramAuthRequest, users: UserSvc) -> AuthResponse:
    """Called by the Mini App on start. Registers the user on first contact."""
    tg = verify_init_data(payload.init_data)
    user, created = await users.register(tg)
    token, expires_in = issue_token(user)
    return AuthResponse(
        user=UserRead.from_model(user),
        token={"access_token": token, "expires_in": expires_in},
        is_new=created,
        is_admin=user.is_admin,
    )


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser) -> UserRead:
    # Deliberately not `ActiveUser`: a banned user must still be able to read
    # their profile so the Web App can show why everything else returns 403.
    return UserRead.from_model(user)


@router.patch("/me", response_model=UserRead)
async def update_me(payload: ProfileUpdate, user: ActiveUser, users: UserSvc) -> UserRead:
    """Minimal profile mutation — currently just the marketing opt-in flag."""
    row = await users.update_profile(user.id, marketing_opt_in=payload.marketing_opt_in)
    if row is None:  # pragma: no cover
        return UserRead.from_model(user)
    return UserRead.from_model(row)
