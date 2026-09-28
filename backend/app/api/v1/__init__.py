"""v1 router aggregation."""

from fastapi import APIRouter

from app.api.v1 import auth, bot, cron, payments, plans, user, vpn
from app.api.v1.admin import router as admin_router

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(plans.router)
api_router.include_router(payments.router)
api_router.include_router(vpn.router)
api_router.include_router(user.router)
api_router.include_router(admin_router)
api_router.include_router(cron.router)
api_router.include_router(bot.router)

__all__ = ["api_router"]
