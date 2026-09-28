"""APScheduler runner — for self-hosted deployments (docker compose, VPS).

On Vercel the very same tasks are triggered by Vercel Cron through
`/api/v1/internal/cron/*`; this process is the alternative for a classic box.

    python -m app.workers.scheduler
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import worker_settings
from app.database import session_scope
from app.logging_config import configure_logging, get_logger
from app.workers import tasks

log = get_logger(__name__)

# name -> (coroutine, interval seconds)
JOBS: dict[str, tuple[Any, int]] = {
    "expire_subscriptions": (tasks.expire_subscriptions, worker_settings.expiry_check_interval),
    "xray_sync": (tasks.run_xray_sync, worker_settings.xray_sync_interval),
    "expiry_notifications": (tasks.send_expiry_reminders, worker_settings.notify_interval),
    "payment_reconcile": (tasks.reconcile_payments, worker_settings.payment_reconcile_interval),
    "server_health": (tasks.check_servers_health, worker_settings.health_check_interval),
}

# Xray sync does more work than the others: give it more headroom.
TIMEOUTS: dict[str, int] = {
    "expire_subscriptions": 120,
    "xray_sync": 600,
    "expiry_notifications": 120,
    "payment_reconcile": 180,
    "server_health": 180,
}


async def _run(name: str, func: Any) -> None:
    from time import perf_counter

    started = perf_counter()
    try:
        async with session_scope() as session:
            result = await func(session)
        log.info("scheduler.job_done", job=name, ms=int((perf_counter() - started) * 1000), result=result)
    except Exception as exc:
        log.error("scheduler.job_failed", job=name, error=str(exc)[:300])


async def main() -> None:
    configure_logging()
    log.info("scheduler.starting", jobs=sorted(JOBS))

    async with session_scope() as session:
        log.info("scheduler.bootstrap", result=await tasks.bootstrap(session))

    scheduler = AsyncIOScheduler(timezone="UTC")
    for name, (func, interval) in JOBS.items():
        scheduler.add_job(
            _run,
            trigger=IntervalTrigger(seconds=interval),
            args=[name, func],
            id=name,
            name=name,
            max_instances=1,
            coalesce=True,      # collapse missed runs instead of stacking them
            misfire_grace_time=60,
            replace_existing=True,
        )

    scheduler.start()
    log.info("scheduler.started", jobs={k: v[1] for k, v in JOBS.items()})

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        # add_signal_handler is unavailable on Windows.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    await stop.wait()
    log.info("scheduler.stopping")
    scheduler.shutdown(wait=True)
    from app.database import dispose_engine

    await dispose_engine()
    log.info("scheduler.stopped")


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt, asyncio.CancelledError):
        asyncio.run(main())
