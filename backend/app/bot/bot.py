"""Bot construction and webhook lifecycle.

Long polling is impossible on a serverless platform, so the bot runs entirely
on webhooks: Telegram POSTs updates to `WEBAPP_URL/api/v1/bot/webhook`, which
the API forwards into the same aiogram dispatcher.
"""

from __future__ import annotations

from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app.bot.handlers import router as main_router
from app.bot.middlewares import BanMiddleware, DatabaseMiddleware
from app.config import app_settings, telegram_settings
from app.logging_config import get_logger

log = get_logger(__name__)

COMMANDS = [
    BotCommand(command="start", description="Запустить бота"),
    BotCommand(command="buy", description="Купить подписку"),
    BotCommand(command="vpn", description="Мой VPN и конфигурация"),
    BotCommand(command="status", description="Статус подписки"),
    BotCommand(command="profile", description="Мой профиль"),
    BotCommand(command="pay", description="История платежей"),
    BotCommand(command="support", description="Поддержка"),
    BotCommand(command="help", description="Инструкция"),
]

SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
SECRET_VALUE = "vpn-webhook"


def build_bot() -> Bot:
    return Bot(
        token=telegram_settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode="HTML"),
    )


def build_dispatcher(bot: Bot | None = None) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    # The webhook must be reachable before updates arrive; fail fast otherwise.
    dp.feed_update = _guarded_feed_update(dp.feed_update)  # type: ignore[method-assign]

    if bot is not None:
        dp.update.middleware(DatabaseMiddleware(bot))
        dp.update.middleware(BanMiddleware())

    dp.include_router(main_router)
    return dp


def _guarded_feed_update(original: Any) -> Any:
    async def wrapper(event: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return await original(event, *args, **kwargs)
        except Exception as exc:
            log.error("bot.update_failed", error=str(exc)[:300], update_type=type(event).__name__)
            return None

    return wrapper


def webhook_url() -> str:
    """URL, на который Telegram присылает апдейты.

    Это адрес БЭКЕНДА (`API_PUBLIC_URL`), а не Web App: при раздельном
    деплое фронтенд — статика и `/bot/webhook` там не существует.
    """
    base = telegram_settings.api_base_url
    return f"{base}{app_settings.api_base_path}/bot/webhook"


def secret_token() -> str:
    """Secret sent to Telegram; we verify it on incoming requests."""
    import hashlib

    digest = hashlib.sha256(
        f"{telegram_settings.bot_token.get_secret_value()}:{SECRET_VALUE}".encode()
    ).hexdigest()
    return digest[:32]


async def setup_webhook(bot: Bot) -> None:
    """Point Telegram at our endpoint and publish the command list."""
    if not telegram_settings.configured:
        log.info("bot.webhook_skipped", reason="BOT_TOKEN is not set")
        return
    if not telegram_settings.api_base_url:
        log.info("bot.webhook_skipped", reason="API_PUBLIC_URL / WEBAPP_URL is not set")
        return

    url = webhook_url()
    if not url.startswith("https://"):
        # Telegram refuses plain HTTP, so a wrong setting would otherwise fail
        # silently at delivery time rather than here.
        log.error("bot.webhook_insecure_url", url=url)
        return

    token = secret_token()
    await bot.set_webhook(url, secret_token=token, drop_pending_updates=False)
    await bot.set_my_commands(COMMANDS)
    log.info("bot.webhook_set", url=url, commands=len(COMMANDS))


async def remove_webhook(bot: Bot) -> None:
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        log.info("bot.webhook_removed")
    except Exception as exc:
        log.warning("bot.webhook_remove_failed", error=str(exc)[:200])


def verify_secret(presented: str | None) -> bool:
    if not presented:
        return False
    import hmac

    return hmac.compare_digest(presented.strip(), secret_token())
