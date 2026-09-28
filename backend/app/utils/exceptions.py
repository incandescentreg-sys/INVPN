"""Domain exceptions with a stable HTTP mapping."""

from __future__ import annotations


class AppError(Exception):
    """Base class for expected, user-facing errors."""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(self, message: str | None = None, *, code: str | None = None) -> None:
        super().__init__(message or self.__class__.__doc__ or "Ошибка")
        self.message = message or self.__class__.__doc__ or "Ошибка"
        if code:
            self.code = code


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    """Объект не найден"""


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"
    """Некорректные данные"""


class AuthError(AppError):
    status_code = 401
    code = "unauthorized"
    """Требуется авторизация"""


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    """Доступ запрещён"""


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    """Конфликт состояния"""


class PaymentError(AppError):
    status_code = 402
    code = "payment_error"
    """Ошибка платежа"""


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"
    """Слишком много запросов"""


class VpnError(AppError):
    status_code = 502
    code = "vpn_error"
    """Ошибка VPN-сервера"""


class VpnUnavailableError(VpnError):
    code = "vpn_unavailable"
    """VPN-сервер недоступен"""


class ConfigError(AppError):
    status_code = 500
    code = "config_error"
    """Ошибка конфигурации"""
