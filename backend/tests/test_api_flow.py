"""End-to-end API flows: registration, purchase, provisioning, cron jobs."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import make_init_data


async def _register(client: AsyncClient, telegram_id: int = 424242) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/auth/telegram", json={"init_data": make_init_data(telegram_id)}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    client.headers["Authorization"] = f"Bearer {body['token']['access_token']}"
    return body


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_register_creates_user_and_is_idempotent(client: AsyncClient) -> None:
    first = await _register(client, 1001)
    assert first["is_new"] is True
    assert first["user"]["telegram_id"] == 1001
    assert first["is_admin"] is False
    assert first["token"]["access_token"]

    # a second /start from the same user must not create a duplicate
    client.headers.pop("Authorization")
    second = await _register(client, 1001)
    assert second["is_new"] is False
    assert second["user"]["id"] == first["user"]["id"]


@pytest.mark.asyncio
async def test_protected_endpoint_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/api/v1/vpn/state")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_bad_init_data_is_rejected(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/telegram", json={"init_data": "hash=deadbeef"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_init_data_header_is_accepted(client: AsyncClient) -> None:
    """The browser may send raw initData instead of a token."""
    await client.post("/api/v1/auth/telegram", json={"init_data": make_init_data(1002)})
    response = await client.get(
        "/api/v1/auth/me", headers={"X-Telegram-Init-Data": make_init_data(1002)}
    )
    assert response.status_code == 200
    assert response.json()["telegram_id"] == 1002


@pytest.mark.asyncio
async def test_me_endpoint(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["telegram_id"] == 123456


# --------------------------------------------------------------------------- #
# Catalogue
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_plans_are_seeded_from_env(client: AsyncClient) -> None:
    await _register(client, 1003)
    from app.database import session_scope
    from app.services.plan import PlanService

    async with session_scope() as session:
        await PlanService(session).seed_default()

    response = await client.get("/api/v1/plans")
    assert response.status_code == 200
    plans = response.json()
    assert len(plans) == 1
    assert plans[0]["code"] == "vpn_30d"
    assert plans[0]["days"] == 30
    assert plans[0]["price_kopeks"] == 29900  # from .env, not hardcoded
    assert plans[0]["currency"] == "RUB"


# --------------------------------------------------------------------------- #
# Purchase flow
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_full_purchase_flow(client: AsyncClient, session: Any, vpn_server: dict[str, Any]) -> None:
    await _register(client, 2001)
    from app.database import session_scope
    from app.services.plan import PlanService

    async with session_scope() as s:
        plan = (await PlanService(s).seed_default())[0]
        plan_id = str(plan.id)

    # 1. state is empty before purchase
    state = (await client.get("/api/v1/vpn/state")).json()
    assert state["has_access"] is False
    assert state["subscription"] is None

    # 2. create an order
    created = await client.post("/api/v1/payments", json={"plan_id": plan_id})
    assert created.status_code == 200, created.text
    order = created.json()
    payment_id = order["payment"]["id"]
    assert order["payment"]["status"] == "pending"
    assert order["payment"]["amount_kopeks"] == 29900
    assert order["redirect_url"] and "mock_id=" in order["redirect_url"]

    # 3. the same idempotency key must reuse the order, not create a second one
    again = await client.post(
        "/api/v1/payments", json={"plan_id": plan_id, "idempotency_key": "order-abc"}
    )
    assert again.status_code == 200
    third = await client.post(
        "/api/v1/payments", json={"plan_id": plan_id, "idempotency_key": "order-abc"}
    )
    assert third.json()["payment"]["id"] == again.json()["payment"]["id"]

    # 4. still pending before the gateway confirms
    assert (await client.get(f"/api/v1/payments/{payment_id}")).json()["payment"]["status"] == "pending"

    # 5. the gateway calls our webhook
    mock_id = order["redirect_url"].split("mock_id=")[1].split("&")[0]
    hook = await client.post(
        "/api/v1/webhooks/mock", json={"mock_id": mock_id, "mock_status": "succeeded", "amount": "299.00"}
    )
    assert hook.status_code == 200, hook.text
    assert hook.json()["status"] == "ok"

    # 6. subscription is active and a client was issued
    status = (await client.get(f"/api/v1/payments/{payment_id}")).json()
    assert status["payment"]["status"] == "succeeded"
    assert status["subscription_activated"] is True

    state = (await client.get("/api/v1/vpn/state")).json()
    assert state["subscription"]["status"] == "active"
    assert state["subscription"]["days_left"] in (29, 30)
    assert len(state["clients"]) == 1
    assert state["primary_client"]["uuid"]
    # Xray is not reachable in tests, so the client stays PENDING — the user
    # still has paid, and the cron job will finish the job.
    assert state["primary_client"]["status"] in ("pending", "active")
    assert state["device_limit"] == {"limit": 0, "used": 1, "remaining": None}

    # 7. notifications were written
    notes = (await client.get("/api/v1/notifications")).json()
    assert any(n["kind"] == "payment_success" for n in notes)


@pytest.mark.asyncio
async def test_webhook_replay_does_not_duplicate(client: AsyncClient, vpn_server: dict[str, Any]) -> None:
    await _register(client, 2002)
    from app.database import session_scope
    from app.services.plan import PlanService

    async with session_scope() as s:
        plan_id = str((await PlanService(s).seed_default())[0].id)

    order = (await client.post("/api/v1/payments", json={"plan_id": plan_id})).json()
    mock_id = order["redirect_url"].split("mock_id=")[1].split("&")[0]
    payload = {"mock_id": mock_id, "mock_status": "succeeded", "amount": "299.00"}

    for _ in range(3):  # gateways retry
        assert (await client.post("/api/v1/webhooks/mock", json=payload)).status_code == 200

    subs = (await client.get("/api/v1/subscriptions")).json()
    assert len(subs["history"]) == 1
    assert len(subs["history"][0]["plan_title"]) > 0

    history = (await client.get("/api/v1/payments")).json()
    assert len([p for p in history if p["status"] == "succeeded"]) == 1


@pytest.mark.asyncio
async def test_webhook_with_unknown_payment_is_acked(client: AsyncClient) -> None:
    """A 200 keeps the gateway from retrying something we will never accept."""
    response = await client.post(
        "/api/v1/webhooks/mock", json={"mock_id": "does-not-exist", "mock_status": "succeeded"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_webhook_for_wrong_provider_is_ignored(client: AsyncClient) -> None:
    response = await client.post("/api/v1/webhooks/rollypay", json={})
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_payment_for_unknown_plan(client: AsyncClient) -> None:
    await _register(client, 2003)
    response = await client.post("/api/v1/payments", json={"plan_id": "00000000-0000-0000-0000-000000000000"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_payment_amount_mismatch_is_rejected(client: AsyncClient) -> None:
    """A tampered amount must not grant access."""
    await _register(client, 2004)
    from app.database import session_scope
    from app.services.plan import PlanService

    async with session_scope() as s:
        plan_id = str((await PlanService(s).seed_default())[0].id)

    order = (await client.post("/api/v1/payments", json={"plan_id": plan_id})).json()
    payment_id = order["payment"]["id"]
    mock_id = order["redirect_url"].split("mock_id=")[1].split("&")[0]

    await client.post(
        "/api/v1/webhooks/mock", json={"mock_id": mock_id, "mock_status": "succeeded", "amount": "1.00"}
    )
    status = (await client.get(f"/api/v1/payments/{payment_id}")).json()
    assert status["payment"]["status"] == "failed"
    state = (await client.get("/api/v1/vpn/state")).json()
    assert state["has_access"] is False


# --------------------------------------------------------------------------- #
# Devices
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_device_management(client: AsyncClient, vpn_server: dict[str, Any]) -> None:
    await _register(client, 2005)
    from app.database import session_scope
    from app.services.plan import PlanService

    async with session_scope() as s:
        plan_id = str((await PlanService(s).seed_default())[0].id)

    order = (await client.post("/api/v1/payments", json={"plan_id": plan_id})).json()
    mock_id = order["redirect_url"].split("mock_id=")[1].split("&")[0]
    await client.post("/api/v1/webhooks/mock", json={"mock_id": mock_id, "mock_status": "succeeded"})

    clients = (await client.get("/api/v1/vpn/clients")).json()
    assert len(clients) == 1
    first_id = clients[0]["id"]

    # reveal the link
    link = (await client.get(f"/api/v1/vpn/clients/{first_id}/link")).json()
    assert link["link"].startswith("vless://")
    assert link["deep_links"]["Hiddify"].startswith("hiddify://add/")

    # add a second device
    added = await client.post("/api/v1/vpn/clients", json={"label": "Ноутбук"})
    assert added.status_code == 201, added.text
    assert added.json()["label"] == "Ноутбук"
    second_id = added.json()["id"]

    # rotate its UUID
    rotated = (await client.post(f"/api/v1/vpn/clients/{second_id}/rotate")).json()
    assert rotated["link"].startswith("vless://")

    # remove one
    removed = await client.delete(f"/api/v1/vpn/clients/{second_id}")
    assert removed.status_code == 200
    assert len((await client.get("/api/v1/vpn/clients")).json()) == 2  # disabled row stays

    # the last active device is protected
    active = [c for c in (await client.get("/api/v1/vpn/clients")).json() if c["status"] == "active"]
    if active:
        blocked = await client.delete(f"/api/v1/vpn/clients/{active[0]['id']}")
        assert blocked.status_code == 409


@pytest.mark.asyncio
async def test_cannot_touch_another_users_client(client: AsyncClient) -> None:
    await _register(client, 2006)
    victim = (await client.get("/api/v1/vpn/clients"))
    assert victim.status_code == 200
    assert victim.json() == []

    # an id that belongs to nobody
    response = await client.get(
        "/api/v1/vpn/clients/11111111-1111-1111-1111-111111111111/link"
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Cron
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_cron_endpoints_run(client: AsyncClient) -> None:
    for path in (
        "/api/v1/internal/cron/expire",
        "/api/v1/internal/cron/sync-xray",
        "/api/v1/internal/cron/notify",
        "/api/v1/internal/cron/reconcile-payments",
        "/api/v1/internal/cron/health",
        "/api/v1/internal/cron/all",
    ):
        response = await client.post(path)
        assert response.status_code == 200, f"{path}: {response.text}"
        body = response.json()
        assert "job" in body or "jobs" in body


@pytest.mark.asyncio
async def test_cron_requires_secret_when_configured(client: AsyncClient, monkeypatch: Any) -> None:
    from app.config import app_settings

    monkeypatch.setattr(app_settings, "cron_secret", type(app_settings.cron_secret)("letmein"))

    denied = await client.post("/api/v1/internal/cron/expire")
    assert denied.status_code == 401

    allowed = await client.post(
        "/api/v1/internal/cron/expire", headers={"Authorization": "Bearer letmein"}
    )
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_expire_job_disables_access(client: AsyncClient) -> None:
    """An expired subscription must be marked EXPIRED."""
    import datetime as dt

    from app.database import session_scope
    from app.enums import SubscriptionStatus
    from app.repositories.subscription import SubscriptionRepository
    from app.repositories.user import UserRepository
    from app.services.plan import PlanService
    from app.services.subscription import SubscriptionService
    from app.utils.time import now

    await _register(client, 2007)
    async with session_scope() as s:
        plan = (await PlanService(s).seed_default())[0]
        db_user = await UserRepository(s).get_by_telegram_id(2007)
        subscription = await SubscriptionService(s).grant(user=db_user, plan=plan, days=30, actor="test")
        # rewind the expiry so the job has something to collect
        subscription.expires_at = now() - dt.timedelta(hours=1)
        subscription.status = SubscriptionStatus.ACTIVE
        sub_id = subscription.id
        await s.flush()

    result = (await client.post("/api/v1/internal/cron/expire")).json()
    assert result["ok"] is True
    assert result["expired"] == 1

    async with session_scope() as s:
        stored = await SubscriptionRepository(s).get(sub_id)
        assert stored is not None
        assert stored.status == SubscriptionStatus.EXPIRED
