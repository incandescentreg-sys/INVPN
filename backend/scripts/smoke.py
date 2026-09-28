"""Smoke check used during development: boots the app and hits a few endpoints.

    python scripts/smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./smoke.db")
os.environ.setdefault("SECRET_KEY", "smoke-test-secret-key-not-for-production")
os.environ.setdefault("PAYMENT_PROVIDER", "mock")
os.environ.setdefault("LOG_LEVEL", "ERROR")

import httpx  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

PATHS = [
    ("GET", "/health"),
    ("GET", "/"),
    ("GET", "/api/v1/plans"),
    ("GET", "/api/v1/auth/me"),          # 401 expected
    ("POST", "/api/v1/auth/telegram"),   # 422 expected (no body)
    ("GET", "/api/v1/vpn/state"),        # 401 expected
    ("GET", "/api/v1/support"),
    ("GET", "/api/v1/instructions"),
    ("POST", "/api/v1/internal/cron/expire"),
]


async def main() -> int:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    failures = 0
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for method, path in PATHS:
                response = await client.request(method, path)
                ok = response.status_code < 500
                failures += 0 if ok else 1
                body = response.text[:110].replace("\n", " ")
                print(f"{'OK ' if ok else 'ERR'} {method:4} {path:38} {response.status_code}  {body}")

    Path("smoke.db").unlink(missing_ok=True)
    print("\nfailures:", failures)
    return failures


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
