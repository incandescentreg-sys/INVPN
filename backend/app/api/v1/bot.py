"""Telegram webhook receiver.

This is what makes the bot work on Vercel: no long-lived process is needed,
Telegram simply POSTs each update here and the request is answered once the
update has been handled.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Request, Response, status

from app.bot.bot import build_dispatcher, verify_secret
from app.logging_config import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/bot", tags=["bot"])

_dispatcher: Any = None


def get_dispatcher() -> Any:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = build_dispatcher()
    return _dispatcher


@router.post("/webhook", include_in_schema=False)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> Response:
    if not verify_secret(x_telegram_bot_api_secret_token):
        log.warning("bot.webhook_bad_secret")
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    try:
        payload = await request.json()
    except Exception:
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    dispatcher = get_dispatcher()
    try:
        await dispatcher.feed_update(payload)
    except Exception as exc:
        # Answer 200 anyway: a retry would replay a broken update forever.
        log.error("bot.webhook_processing_failed", error=str(exc)[:300])
    return Response(status_code=status.HTTP_200_OK)


@router.get("/webhook-info", include_in_schema=False)
async def webhook_info(request: Request) -> dict:
    from app.bot.bot import webhook_url
    from app.config import telegram_settings

    bot = getattr(request.app.state, "bot", None)
    info: dict = {
        "configured": telegram_settings.configured,
        "webapp_url": telegram_settings.webapp_url,
        "expected_url": webhook_url() if telegram_settings.webapp_url else None,
    }
    if bot is not None:
        try:
            info["remote"] = await bot.get_webhook_info()
        except Exception as exc:
            info["remote_error"] = str(exc)[:200]
    return info
