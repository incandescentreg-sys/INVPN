"""Liveness / readiness endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app import __version__
from app.api.deps import DbSession
from app.config import app_settings, payment_settings, telegram_settings
from app.schemas.common import HealthResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse, include_in_schema=False)
async def health(session: DbSession, response: Response) -> HealthResponse:
    """Liveness probe. Never raises: reports component status instead."""
    database = "down"
    try:
        await session.execute(text("SELECT 1"))
        database = "up"
    except Exception as exc:
        database = f"down: {type(exc).__name__}"

    bot = "configured" if telegram_settings.configured else "not configured"

    servers: list[dict[str, Any]] = []
    try:
        from app.services.server import ServerService

        for server in await ServerService(session).list_all():
            servers.append(
                {
                    "id": str(server.id),
                    "name": server.name,
                    "active": server.is_active,
                    "status": server.last_check_status,
                    "last_checked_at": server.last_checked_at.isoformat()
                    if server.last_checked_at
                    else None,
                }
            )
    except Exception as exc:
        servers = [{"error": type(exc).__name__}]

    ok = database == "up"
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status="ok" if ok else "degraded",
        version=__version__,
        environment=app_settings.env,
        database=database,
        bot=bot,
        payment_provider=payment_settings.provider_display,
        vpn_servers=servers,
    )


@router.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "service": app_settings.name,
        "version": __version__,
        "docs": "/docs",
        "api": app_settings.api_base_path,
    }
