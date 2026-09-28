"""Cron entry points (Vercel Cron / any external scheduler).

Vercel has no long-lived workers, so scheduled work arrives here as an HTTP
call. Every endpoint is idempotent, bounded in time and safe to call twice.
Set `CRON_SECRET` in the project env and Vercel will send it automatically.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import CronAuth
from app.config import worker_settings
from app.database import session_scope
from app.logging_config import get_logger
from app.workers.tasks import (
    check_servers_health,
    expire_subscriptions,
    reconcile_payments,
    run_xray_sync,
    send_expiry_reminders,
)

log = get_logger(__name__)
router = APIRouter(prefix="/internal/cron", tags=["cron"], include_in_schema=False)

# Vercel Hobby: 60s per function. Reserve a margin for the response itself.
TIME_BUDGET_SECONDS = 45


async def _timed(name: str, coro: Any) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = await coro
        duration = int((time.perf_counter() - started) * 1000)
        log.info("cron.done", job=name, duration_ms=duration)
        return {"job": name, "ok": True, "duration_ms": duration, **result}
    except Exception as exc:
        duration = int((time.perf_counter() - started) * 1000)
        log.error("cron.failed", job=name, duration_ms=duration, error=str(exc)[:300])
        return {"job": name, "ok": False, "duration_ms": duration, "error": str(exc)[:300]}


# Vercel Cron issues GET requests; a manual trigger is easier with POST.
# Both verbs run the exact same job, so either works.
@router.api_route("/expire", methods=["GET", "POST"])
async def cron_expire(_: CronAuth) -> dict[str, Any]:
    """Expire lapsed subscriptions and drop their Xray clients."""
    async with session_scope() as session:
        return await _timed("expire", expire_subscriptions(session))


@router.api_route("/sync-xray", methods=["GET", "POST"])
async def cron_sync(_: CronAuth, force: bool = Query(False)) -> dict[str, Any]:
    """Reconcile every node's client list with the database."""
    async with session_scope() as session:
        return await _timed("sync-xray", run_xray_sync(session, force=force))


@router.api_route("/notify", methods=["GET", "POST"])
async def cron_notify(_: CronAuth) -> dict[str, Any]:
    """Send the 3-day / 1-day / expired reminders (deduplicated)."""
    async with session_scope() as session:
        return await _timed("notify", send_expiry_reminders(session))


@router.api_route("/reconcile-payments", methods=["GET", "POST"])
async def cron_reconcile(_: CronAuth) -> dict[str, Any]:
    """Ask the gateway about every unresolved payment (webhook safety net)."""
    async with session_scope() as session:
        return await _timed("reconcile-payments", reconcile_payments(session))


@router.api_route("/health", methods=["GET", "POST"])
async def cron_health(_: CronAuth) -> dict[str, Any]:
    async with session_scope() as session:
        return await _timed("health", check_servers_health(session))


@router.api_route("/all", methods=["GET", "POST"])
async def cron_all(_: CronAuth) -> dict[str, Any]:
    """Everything in one call — the only option on the Vercel Hobby plan,
    where cron may only run once per day."""
    jobs = [
        expire_subscriptions,
        run_xray_sync,
        send_expiry_reminders,
        reconcile_payments,
        check_servers_health,
    ]
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    skipped: list[str] = []

    for job in jobs:
        # Vercel Hobby gives a function 60s. Running every job blindly can blow
        # the limit mid-way, which would make the whole cron invocation fail and
        # delay *all* work to the next day. Stop before that happens: whatever is
        # left runs on the next tick.
        if time.perf_counter() - started > TIME_BUDGET_SECONDS:
            skipped.append(job.__name__)
            log.warning("cron.budget_exhausted", skipped=skipped)
            continue
        async with session_scope() as session:
            results.append(await _timed(job.__name__, job(session)))

    return {
        "ok": all(r["ok"] for r in results),
        "jobs": results,
        "skipped": skipped,
        "budget_exhausted": bool(skipped),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "intervals": {
            "expiry": worker_settings.expiry_check_interval,
            "sync": worker_settings.xray_sync_interval,
            "notify": worker_settings.notify_interval,
        },
    }
