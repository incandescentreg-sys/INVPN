"""Background jobs.

Each function opens no session of its own, returns a small JSON-serialisable
summary, and is safe to run concurrently with itself *and* safe to re-run — the
same code path serves Vercel Cron and the APScheduler process.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.services.notification import NotificationService
from app.services.payment import PaymentService
from app.services.subscription import SubscriptionService
from app.services.vpn import VpnService

log = get_logger(__name__)

# Bounds keep a job comfortably inside the serverless execution limit.
EXPIRE_BATCH = 200
SYNC_BATCH = 2000
NOTIFY_BATCH = 200
RECONCILE_BATCH = 50


async def expire_subscriptions(session: AsyncSession) -> dict[str, Any]:
    """Expire overdue subscriptions and remove their clients from Xray."""
    subscriptions = SubscriptionService(session)
    vpn = VpnService(session)
    notifications = NotificationService(session)

    expired = await subscriptions.expire_due(limit=EXPIRE_BATCH)
    if not expired:
        return {"expired": 0, "revoked": 0}

    # Collect affected nodes, then sync each one exactly once.
    server_ids = {s.server_id for s in expired if s.server_id}
    revoked = 0
    for subscription in expired:
        revoked += await vpn.delete_clients(subscription)

    synced: list[str] = []
    for server_id in server_ids:
        server = await vpn.get_server(server_id)
        if server is None:
            continue
        try:
            await vpn.sync_server(server)
            synced.append(server.name)
        except Exception as exc:
            log.error("worker.expire_sync_failed", server=server.name, error=str(exc)[:200])
            await vpn.record_error(server, str(exc))

    await notifications.notify_expired(list(expired))
    return {
        "expired": len(expired),
        "revoked_clients": revoked,
        "synced_servers": synced,
    }


async def run_xray_sync(session: AsyncSession, *, force: bool = False) -> dict[str, Any]:
    """Reconcile every active node with the desired client list."""
    vpn = VpnService(session)
    results = await vpn.sync_all_servers(force=force)
    return {
        "servers": len(results),
        "ok": sum(1 for r in results if r.get("ok")),
        "results": results,
    }


async def send_expiry_reminders(session: AsyncSession) -> dict[str, Any]:
    """Notify about upcoming expiry (3 days / 1 day / today) exactly once each."""
    notifications = NotificationService(session)
    return await notifications.send_expiry_reminders(limit=NOTIFY_BATCH)


async def reconcile_payments(session: AsyncSession) -> dict[str, Any]:
    """Resolve payments that never produced a webhook."""
    payments = PaymentService(session)
    results = await payments.reconcile_pending(limit=RECONCILE_BATCH)
    return {
        "checked": len(results),
        "succeeded": sum(1 for r in results if r.get("status") == "succeeded"),
        "failed": sum(1 for r in results if not r.get("ok")),
    }


async def check_servers_health(session: AsyncSession) -> dict[str, Any]:
    """Probe each node: service state, config validity, listening port."""
    vpn = VpnService(session)
    reports = await vpn.check_all_servers()
    return {
        "servers": len(reports),
        "up": sum(1 for r in reports if r.get("status") == "up"),
        "reports": reports,
    }


async def bootstrap(session: AsyncSession) -> dict[str, Any]:
    """Startup housekeeping: seed the catalogue and the default node."""
    from app.config import plan_seed_settings
    from app.services.plan import PlanService
    from app.services.server import ServerService

    seeded: list[str] = []
    if plan_seed_settings.seed_on_startup:
        plans = await PlanService(session).seed_default()
        seeded = [p.code for p in plans]

    server = await ServerService(session).bootstrap_from_env()
    return {
        "plans": seeded,
        "server": server.name if server else None,
        "server_configured": bool(server and server.is_active),
    }


ALL_TASKS = {
    "expire": expire_subscriptions,
    "sync": run_xray_sync,
    "notify": send_expiry_reminders,
    "reconcile": reconcile_payments,
    "health": check_servers_health,
}


async def run_all() -> list[dict[str, Any]]:
    """Sequential run used by the local scheduler and the `/all` cron route."""
    from app.database import session_scope

    results: list[dict[str, Any]] = []
    for name, task in ALL_TASKS.items():
        try:
            async with session_scope() as session:
                results.append({"job": name, "ok": True, **(await task(session))})
        except Exception as exc:
            log.error("worker.failed", job=name, error=str(exc)[:200])
            results.append({"job": name, "ok": False, "error": str(exc)[:200]})
        await asyncio.sleep(0)  # yield to the event loop between jobs
    return results
