"""Shared pytest fixtures.

Env vars are set before importing the app because `app.config` snapshots the
settings at import time.
"""

from __future__ import annotations

import os
import tempfile
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

TEST_BOT_TOKEN = "123456:TEST-TOKEN-FOR-UNIT-TESTS"
# Syntactically valid but unusable — the manager must never reach a real host.
FAKE_SSH_KEY = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n"
    "QyNTUxOQAAACBHdGVzdEtleUJsb2NrZXJUZXN0T25seUJsb2NrZXJUZXN0T25seQ==\n"
    "-----END OPENSSH PRIVATE KEY-----\n"
)
# One database file per test session. The path must be unique because Windows
# keeps the file locked while the engine's pool is open.
SESSION_ID = os.urandom(4).hex()
TEST_DIR = Path(tempfile.gettempdir()) / f"vpn-service-tests-{SESSION_ID}"
TEST_DIR.mkdir(parents=True, exist_ok=True)
TEST_DB = TEST_DIR / "test.db"

os.environ.update(
    {
        "DATABASE_URL": f"sqlite+aiosqlite:///{TEST_DB.as_posix()}",
        "SECRET_KEY": "unit-test-secret-key-value-0123456789",
        "BOT_TOKEN": TEST_BOT_TOKEN,
        "WEBAPP_URL": "https://app.test",
        "APP_ENV": "local",
        "LOG_LEVEL": "ERROR",
        "PAYMENT_PROVIDER": "mock",
        "MOCK_PAYMENT_AUTO_CONFIRM": "false",
        "MOCK_PAYMENT_RETURN_URL": "https://app.test/paid",
        "SEED_PLANS_ON_STARTUP": "true",
        "SERVER_HOST": "",
        "ADMIN_TELEGRAM_IDS": "777000",
        "EXPIRY_NOTIFY_DAYS": "3,1,0",
    }
)

import hashlib  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.database import get_db  # noqa: E402
from app.models import Base  # noqa: E402


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
@pytest_asyncio.fixture
async def engine() -> AsyncIterator[Any]:
    """Fresh database per test, wired into the app's `session_scope` too."""
    db_file = TEST_DIR / f"test-{os.urandom(4).hex()}.db"
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}", future=True)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

    # Services and workers open their own sessions via `session_scope()`;
    # point it at the same test database.
    import app.database as database_module

    original = database_module.SessionLocal
    database_module.SessionLocal = factory
    try:
        yield test_engine
    finally:
        database_module.SessionLocal = original
        await test_engine.dispose()
        db_file.unlink(missing_ok=True)


@pytest_asyncio.fixture
async def session(engine: Any) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session


@pytest_asyncio.fixture
async def client(engine: Any) -> AsyncIterator[AsyncClient]:
    """HTTP client with the DB dependency pointed at the test database."""
    from app.main import app

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def _get_db() -> AsyncIterator[AsyncSession]:
        async with factory() as db_session:
            try:
                yield db_session
                await db_session.commit()
            except Exception:
                await db_session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Telegram initData
# --------------------------------------------------------------------------- #
def make_init_data(
    telegram_id: int,
    *,
    first_name: str = "Test",
    username: str = "tester",
    auth_date: int | None = None,
    bot_token: str = TEST_BOT_TOKEN,
) -> str:
    """Build a correctly signed `initData` string (same algorithm as Telegram)."""
    user = {
        "id": telegram_id,
        "first_name": first_name,
        "username": username,
        "language_code": "ru",
        "is_premium": False,
    }
    pairs = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAE-test",
        "user": json.dumps(user, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


@pytest.fixture
def init_data_factory():
    return make_init_data


@pytest_asyncio.fixture
async def client_factory(engine: Any):
    """Creates extra clients on the same database (independent auth headers)."""
    from app.main import app

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    created: list[AsyncClient] = []

    async def _get_db() -> AsyncIterator[AsyncSession]:
        async with factory() as db_session:
            try:
                yield db_session
                await db_session.commit()
            except Exception:
                await db_session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_db

    async def _make() -> AsyncClient:
        http = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        created.append(http)
        return await http.__aenter__()

    try:
        yield _make
    finally:
        for http in created:
            await http.__aexit__(None, None, None)
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient) -> AsyncClient:
    """Client that has already exchanged initData for a token."""
    response = await client.post(
        "/api/v1/auth/telegram", json={"init_data": make_init_data(123456)}
    )
    assert response.status_code == 200, response.text
    client.headers["Authorization"] = f"Bearer {response.json()['token']['access_token']}"
    return client


@pytest_asyncio.fixture
async def admin_client(client: AsyncClient) -> AsyncClient:
    response = await client.post(
        "/api/v1/auth/telegram", json={"init_data": make_init_data(777000, username="boss")}
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_admin"] is True
    client.headers["Authorization"] = f"Bearer {response.json()['token']['access_token']}"
    return client


@pytest_asyncio.fixture
async def vpn_server() -> dict[str, Any]:
    """A configured node row.

    The Xray sync will fail (there is no real SSH host in tests), which is
    exactly the path we want to exercise: the user keeps access and the cron
    job retries the sync later.
    """
    from app.database import session_scope
    from app.services.server import ServerService

    async with session_scope() as session:
        server = await ServerService(session).create(
            name="test-node",
            host="10.0.0.1",
            public_host="vpn.test",
            ssh_key=FAKE_SSH_KEY,
            reality_target="www.microsoft.com:443",
            reality_server_names=["www.microsoft.com"],
        )
        return {
            "id": str(server.id),
            "name": server.name,
            "public_key": server.reality_public_key,
            "short_id": server.reality_short_id,
        }


@pytest_asyncio.fixture
async def seeded_plan(client: AsyncClient) -> dict[str, Any]:
    """The starter tariff created by the startup bootstrap."""
    from app.database import session_scope
    from app.services.plan import PlanService

    async with session_scope() as session:
        plans = await PlanService(session).seed_default()
        return {"id": str(plans[0].id), "code": plans[0].code, "price": plans[0].price_kopeks}
