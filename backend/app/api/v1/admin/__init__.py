"""Admin router aggregation."""

from fastapi import APIRouter

from app.api.v1.admin import commerce, servers, users

router = APIRouter()
router.include_router(users.router)
router.include_router(commerce.router)
router.include_router(servers.router)

__all__ = ["router"]
