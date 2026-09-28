"""Admin panel endpoints: access control and CRUD."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import FAKE_SSH_KEY, make_init_data


async def register(http: AsyncClient, telegram_id: int) -> dict[str, Any]:
    """Register a user on a *dedicated* client and return the auth body."""
    response = await http.post(
        "/api/v1/auth/telegram", json={"init_data": make_init_data(telegram_id)}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    http.headers["Authorization"] = f"Bearer {body['token']['access_token']}"
    return body


# --------------------------------------------------------------------------- #
# Access control
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/admin/stats"),
        ("GET", "/api/v1/admin/users"),
        ("GET", "/api/v1/admin/plans"),
        ("GET", "/api/v1/admin/payments"),
        ("GET", "/api/v1/admin/servers"),
        ("POST", "/api/v1/admin/servers/sync"),
    ],
)
async def test_admin_endpoints_reject_regular_users(
    client_factory: Any, method: str, path: str
) -> None:
    user = await client_factory()
    await register(user, 100_001)
    response = await user.request(method, path)
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


@pytest.mark.asyncio
async def test_admin_endpoints_reject_anonymous(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/admin/stats")).status_code == 401


@pytest.mark.asyncio
async def test_admin_flag_comes_from_env(admin_client: AsyncClient) -> None:
    """ADMIN_TELEGRAM_IDS is the source of truth."""
    me = (await admin_client.get("/api/v1/auth/me")).json()
    assert me["is_admin"] is True
    assert me["telegram_id"] == 777000


# --------------------------------------------------------------------------- #
# Plans
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_plan_crud(admin_client: AsyncClient) -> None:
    created = await admin_client.post(
        "/api/v1/admin/plans",
        json={
            "code": "vpn_90d",
            "title": "VPN 90 дней",
            "days": 90,
            "price_kopeks": 79900,
            "features": ["Всё из 30 дней", "Выгоднее на 20%"],
            "is_popular": False,
        },
    )
    assert created.status_code == 201, created.text
    plan = created.json()
    assert plan["code"] == "vpn_90d"
    assert plan["price_kopeks"] == 79900
    plan_id = plan["id"]

    codes = [p["code"] for p in (await admin_client.get("/api/v1/plans")).json()]
    assert "vpn_90d" in codes

    updated = await admin_client.patch(f"/api/v1/admin/plans/{plan_id}", json={"price_kopeks": 69900})
    assert updated.json()["price_kopeks"] == 69900

    assert (await admin_client.delete(f"/api/v1/admin/plans/{plan_id}")).status_code == 200
    codes = [p["code"] for p in (await admin_client.get("/api/v1/plans")).json()]
    assert "vpn_90d" not in codes


@pytest.mark.asyncio
async def test_duplicate_plan_code_is_rejected(admin_client: AsyncClient) -> None:
    payload = {"code": "dup_plan", "title": "T", "days": 30, "price_kopeks": 100}
    assert (await admin_client.post("/api/v1/admin/plans", json=payload)).status_code == 201
    second = await admin_client.post("/api/v1/admin/plans", json=payload)
    assert second.status_code in (400, 404, 409)


@pytest.mark.asyncio
async def test_plan_validation(admin_client: AsyncClient) -> None:
    bad = await admin_client.post(
        "/api/v1/admin/plans", json={"code": "Bad Code!", "title": "", "days": 0, "price_kopeks": -5}
    )
    assert bad.status_code == 422


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_user_ban_and_unban(admin_client: AsyncClient, client_factory: Any) -> None:
    user = await client_factory()
    await register(user, 100_002)

    listed = (await admin_client.get("/api/v1/admin/users", params={"search": "100002"})).json()
    assert listed["total"] >= 1
    user_id = listed["items"][0]["id"]

    assert (await admin_client.post(f"/api/v1/admin/users/{user_id}/ban")).status_code == 200
    banned = (await admin_client.get("/api/v1/admin/users", params={"is_banned": True})).json()
    assert any(u["id"] == user_id for u in banned["items"])

    assert (await admin_client.post(f"/api/v1/admin/users/{user_id}/unban")).status_code == 200
    active = (await admin_client.get("/api/v1/admin/users", params={"is_banned": False})).json()
    assert any(u["id"] == user_id for u in active["items"])


@pytest.mark.asyncio
async def test_banned_user_is_locked_out(admin_client: AsyncClient, client_factory: Any) -> None:
    victim = await client_factory()
    await register(victim, 100_003)
    assert (await victim.get("/api/v1/profile")).status_code == 200

    listed = (await admin_client.get("/api/v1/admin/users", params={"search": "100003"})).json()
    await admin_client.post(f"/api/v1/admin/users/{listed['items'][0]['id']}/ban")

    blocked = await victim.get("/api/v1/profile")
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "forbidden"
    # the token is still valid — access is refused, not the session
    assert (await victim.get("/api/v1/auth/me")).status_code == 200


# --------------------------------------------------------------------------- #
# Subscriptions & stats
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_admin_can_grant_and_extend(
    admin_client: AsyncClient, vpn_server: dict[str, Any], client_factory: Any
) -> None:
    from app.database import session_scope
    from app.services.plan import PlanService

    async with session_scope() as s:
        plan_id = str((await PlanService(s).seed_default())[0].id)

    member = await client_factory()
    await register(member, 100_004)
    users = (await admin_client.get("/api/v1/admin/users", params={"search": "100004"})).json()
    user_id = users["items"][0]["id"]

    granted = await admin_client.post(
        "/api/v1/admin/subscriptions/grant",
        params={"user_id": user_id, "plan_id": plan_id, "days": 30},
    )
    assert granted.status_code == 200, granted.text
    subscription = granted.json()
    assert subscription["status"] == "active"
    assert subscription["plan_title"]

    extended = await admin_client.post(
        f"/api/v1/admin/subscriptions/{subscription['id']}/extend", json={"days": 30}
    )
    assert extended.status_code == 200
    assert extended.json()["days_left"] >= subscription["days_left"]

    assert (
        await admin_client.post(
            f"/api/v1/admin/subscriptions/{subscription['id']}/suspend", params={"reason": "abuse"}
        )
    ).status_code == 200
    assert (
        await admin_client.post(f"/api/v1/admin/subscriptions/{subscription['id']}/reactivate")
    ).status_code == 200


@pytest.mark.asyncio
async def test_stats_shape(admin_client: AsyncClient, vpn_server: dict[str, Any]) -> None:
    stats = (await admin_client.get("/api/v1/admin/stats")).json()
    assert set(stats) == {"users", "subscriptions", "payments", "vpn"}
    assert stats["users"]["total"] >= 1
    assert isinstance(stats["payments"]["revenue_kopeks"], int)
    assert isinstance(stats["vpn"]["servers"], list)


@pytest.mark.asyncio
async def test_subscription_history_endpoint(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/v1/admin/subscriptions")
    assert response.status_code == 200
    assert "items" in response.json()


# --------------------------------------------------------------------------- #
# Servers
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_server_creation_encrypts_secrets(admin_client: AsyncClient) -> None:
    """The API must never hand back the SSH key or the REALITY private key."""
    created = await admin_client.post(
        "/api/v1/admin/servers",
        json={
            "name": "second-node",
            "host": "10.0.0.2",
            "public_host": "vpn2.test",
            "ssh_key": FAKE_SSH_KEY,
            "ssh_host_key_sha256": "SHA256:abc",
            "reality_server_names": ["www.microsoft.com", "microsoft.com"],
        },
    )
    assert created.status_code == 201, created.text
    assert "BEGIN OPENSSH PRIVATE KEY" not in created.text
    assert "private" not in created.json()

    server = created.json()
    assert server["reality_public_key"]  # derived for the client link
    assert "www.microsoft.com" in server["reality_server_names"]

    listed = (await admin_client.get("/api/v1/admin/servers")).json()
    assert len(listed) == 1
    assert "BEGIN OPENSSH" not in str(listed)
