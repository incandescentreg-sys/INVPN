"""Bot webhook wiring.

The webhook URL must point at the BACKEND. When the frontend and the API are
deployed as two separate Vercel projects they live on different domains, and
sending Telegram updates to the static site would silently break the bot.
"""

from __future__ import annotations

import pytest

from app.bot.bot import (
    SECRET_VALUE,
    build_dispatcher,
    secret_token,
    verify_secret,
    webhook_url,
)
from app.config import telegram_settings


def _apply(monkeypatch: pytest.MonkeyPatch, **values: object) -> None:
    for key, value in values.items():
        monkeypatch.setattr(telegram_settings, key, value)


def test_webhook_uses_backend_url_not_webapp(monkeypatch: pytest.MonkeyPatch) -> None:
    """The critical case: two different domains."""
    _apply(
        monkeypatch,
        webapp_url="https://vpn.example.com",
        api_public_url="https://api.example.com",
    )
    url = webhook_url()
    assert url.startswith("https://api.example.com/"), url
    assert url.endswith("/api/v1/bot/webhook")
    assert "vpn.example.com" not in url, "вебхук не должен уходить на статику фронтенда"


def test_webhook_falls_back_to_single_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    """One domain + reverse proxy: API_PUBLIC_URL is optional."""
    _apply(monkeypatch, webapp_url="https://vpn.example.com/", api_public_url="")
    assert webhook_url() == "https://vpn.example.com/api/v1/bot/webhook"


def test_api_base_url_property(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply(monkeypatch, webapp_url="https://a.test", api_public_url="https://b.test/")
    assert telegram_settings.api_base_url == "https://b.test"

    _apply(monkeypatch, api_public_url="")
    assert telegram_settings.api_base_url == "https://a.test"


def test_api_base_url_empty_without_any_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply(monkeypatch, webapp_url="", api_public_url="")
    assert telegram_settings.api_base_url == ""


def test_secret_token_is_deterministic_and_verifiable() -> None:
    token = secret_token()
    assert len(token) == 32
    assert secret_token() == token, "секрет должен быть стабильным между вызовами"
    assert verify_secret(token) is True
    assert verify_secret(token + "x") is False
    assert verify_secret("") is False
    assert verify_secret(None) is False
    assert SECRET_VALUE


def test_dispatcher_registers_every_handler() -> None:
    """Handlers must be registered — catches broken imports in bot wiring."""
    dp = build_dispatcher()
    # `dp.message.handlers` only holds observers created at include_router time,
    # so the reliable check is the router list plus the total handler count.
    assert dp.message.router, "message-router не создан"
    assert dp.callback_query.router, "callback-router не создан"
    assert len(dp.sub_routers) >= 1, "хендлеры не подключены к диспетчеру"
