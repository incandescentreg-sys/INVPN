"""Vercel serverless entry point.

Vercel's Python runtime calls a WSGI-style `app` attribute. FastAPI is ASGI, so
we adapt it with Mangum. `lifespan="on"` makes startup/shutdown hooks run, which
is what registers the Telegram webhook and seeds the catalogue on a cold start.
"""

from mangum import Mangum

from app.main import app as fastapi_app

app = Mangum(fastapi_app, lifespan="on", api_gateway_base_path="/")
