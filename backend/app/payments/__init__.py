"""Payment provider registry — the only place that knows the available gateways."""

from __future__ import annotations

from functools import lru_cache

from app.config import payment_settings
from app.logging_config import get_logger
from app.payments.base import PaymentProvider
from app.payments.mock import MockPaymentProvider
from app.payments.rollypay import RollypayProvider

log = get_logger(__name__)

_PROVIDERS: dict[str, type[PaymentProvider]] = {
    MockPaymentProvider.name: MockPaymentProvider,
    RollypayProvider.name: RollypayProvider,
}


def get_provider(name: str | None = None) -> PaymentProvider:
    """Instantiate the configured provider (or one named explicitly)."""
    provider_name = (name or payment_settings.provider).lower()
    provider_cls = _PROVIDERS.get(provider_name)
    if provider_cls is None:
        available = ", ".join(sorted(_PROVIDERS))
        raise ValueError(f"Неизвестный платёжный провайдер {provider_name!r}. Доступны: {available}")
    return provider_cls()


@lru_cache(maxsize=1)
def get_default_provider() -> PaymentProvider:
    return get_provider(payment_settings.provider)


def available_providers() -> list[str]:
    return sorted(_PROVIDERS)


def webhook_path(provider: str | None = None) -> str:
    return get_provider(provider).name and payment_settings.webhook_path


__all__ = ["available_providers", "get_default_provider", "get_provider", "webhook_path"]
