"""Entrypoints.

`app.main:app` — FastAPI application (self-hosted / docker).
`api.index:app`  — Mangum-wrapped ASGI handler for Vercel serverless.
"""

from app.main import app

__all__ = ["app"]
