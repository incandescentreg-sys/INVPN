"""Structured logging setup (structlog), console + optional Sentry."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.config import app_settings

_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return

    level = getattr(logging, app_settings.log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    for noisy in ("uvicorn.access", "aiogram.event", "asyncio", "apscheduler.executors"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if app_settings.log_json
        else structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    )

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    if app_settings.sentry_dsn:
        try:
            import sentry_sdk

            sentry_sdk.init(
                dsn=app_settings.sentry_dsn,
                environment=app_settings.env,
                traces_sample_rate=0.1,
                send_default_pii=False,
            )
        except ImportError:  # pragma: no cover
            pass

    _configured = True


def get_logger(name: str) -> Any:
    """Return a bound structlog logger. `name` is attached as `logger=`."""
    configure_logging()
    return structlog.get_logger(name)
