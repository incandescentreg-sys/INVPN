"""FastAPI application factory.

Works in three places with the same code:
  * Vercel serverless  — via `api/index.py` (Mangum ASGI handler)
  * docker compose     — `uvicorn app.main:app`
  * local dev          — `python -m app.main`
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.v1 import api_router
from app.api.v1.health import router as health_router
from app.config import app_settings, payment_settings, telegram_settings
from app.database import dispose_engine, session_scope
from app.logging_config import configure_logging, get_logger
from app.utils.exceptions import AppError

log = get_logger(__name__)


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title=app_settings.api_title,
        version=app_settings.api_version or __version__,
        description=(
            "API коммерческого VPN-сервиса на VLESS/REALITY.\n\n"
            "Авторизация: передайте `Authorization: Bearer <token>` (получен при обмене "
            "Telegram `initData` на `/auth/telegram`) либо заголовок `X-Telegram-Init-Data`."
        ),
        docs_url="/docs" if not app_settings.is_production else None,
        redoc_url="/redoc" if not app_settings.is_production else None,
        openapi_url="/openapi.json" if not app_settings.is_production else None,
    )

    # -- middleware ------------------------------------------------------ #
    if app_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=app_settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Any:
        import time

        import structlog

        structlog.contextvars.bind_contextvars(
            path=request.url.path,
            method=request.method,
            request_id=request.headers.get("x-request-id", ""),
        )
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("request.failed", path=request.url.path)
            raise
        finally:
            structlog.contextvars.clear_contextvars()
        duration = int((time.perf_counter() - started) * 1000)
        response.headers["X-Response-Time"] = f"{duration}ms"
        if duration > 2000:
            log.warning("request.slow", path=request.url.path, duration_ms=duration)
        return response

    # -- error handling -------------------------------------------------- #
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.code, "code": exc.code, "detail": exc.message},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": "validation_error",
                "code": "validation_error",
                "detail": "Некорректные данные",
                "errors": exc.errors()[:10],
            },
        )

    # -- routers --------------------------------------------------------- #
    app.include_router(health_router)
    app.include_router(api_router, prefix=app_settings.api_base_path)

    # -- lifecycle ------------------------------------------------------- #
    @app.on_event("startup")
    async def on_startup() -> None:
        await _startup(app)
        log.info(
            "app.started",
            env=app_settings.env,
            api=app_settings.api_base_path,
            payment=payment_settings.provider,
            bot=telegram_settings.configured,
        )

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        bot = getattr(app.state, "bot", None)
        if bot is not None:
            with contextlib.suppress(Exception):
                await bot.session.close()
        await dispose_engine()
        log.info("app.stopped")

    return app


async def _startup(app: FastAPI) -> None:
    """Seed data, set the bot webhook, register cron handlers.

    On serverless this runs per cold start, so every step must be cheap and
    failure-tolerant.
    """
    # 1. Telegram bot (webhook mode — long polling is impossible on Vercel).
    if telegram_settings.configured and telegram_settings.webapp_url:
        from app.bot.bot import build_bot, setup_webhook

        try:
            bot = build_bot()
            app.state.bot = bot
            await setup_webhook(bot)
        except Exception as exc:
            log.error("startup.bot_failed", error=str(exc)[:300])

    # 2. Catalogue + default node.
    with contextlib.suppress(Exception):
        from app.workers.tasks import bootstrap

        async with session_scope() as session:
            result = await bootstrap(session)
            log.info("startup.bootstrap", **result)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await _startup(app)
    try:
        yield
    finally:
        bot = getattr(app.state, "bot", None)
        if bot is not None:
            with contextlib.suppress(Exception):
                await bot.session.close()
        await dispose_engine()


app = create_app()
