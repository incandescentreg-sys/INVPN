"""Rollypay payment provider.

ВНИМАНИЕ: публичная документация Rollypay (api.rollypay.com) недоступна из этой
среды, поэтому точный контракт запросов/ответов здесь вынесен в две места,
которые нужно сверить с их докой (раздел 9 документации):

  1. `RollypaySettings.create_path / status_path / refund_path` (или .env
     ROLLYPAY_CREATE_PATH, ROLLYPAY_STATUS_PATH, ROLLYPAY_REFUND_PATH);
  2. `_build_create_payload()` и `_extract()` ниже.

Всё остальное (нормализация статусов, идемпотентность, проверка подписи,
рефанды, обработка вебхуков) реализовано полностью и от провайдера не зависит.
Ниже используется YooKassa-подобная схема полей, которую Rollypay наследует.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any, ClassVar

import httpx

from app.config import payment_settings
from app.enums import PaymentStatus
from app.logging_config import get_logger
from app.payments.base import (
    CreatePaymentRequest,
    PaymentIntent,
    PaymentProvider,
    RefundResult,
    WebhookEvent,
    normalize_status,
    to_kopeks,
)
from app.utils.exceptions import PaymentError

log = get_logger(__name__)

# Gateways nest the useful bits differently; try the common shapes in order.
_ID_KEYS = ("id", "payment_id", "paymentId", "uuid", "order_id")
_STATUS_KEYS = ("status", "state", "payment_status")
_AMOUNT_KEYS = ("amount", "amount_value", "total")
_CONFIRM_KEYS = ("confirmation_url", "confirmationUrl", "redirect_url", "url", "pay_url")


def _dig(data: Any, keys: tuple[str, ...]) -> Any:
    """Search top level, then common nested containers."""
    if isinstance(data, dict):
        for key in keys:
            if key in data and data[key] not in (None, ""):
                return data[key]
        for nested in ("payment", "data", "result", "order", "goods", "response"):
            if isinstance(data.get(nested), (dict, list)):
                found = _dig(data[nested], keys)
                if found is not None:
                    return found
    return None


class RollypayProvider(PaymentProvider):
    name: ClassVar[str] = "rollypay"
    display_name: ClassVar[str] = "Rollypay"

    def __init__(
        self,
        *,
        api_url: str | None = None,
        token: str | None = None,
        shop_id: str | None = None,
        timeout: int | None = None,
        verify_signature: bool = True,
    ) -> None:
        settings = payment_settings
        self._api_url = (api_url or settings.rollypay_api_url).rstrip("/")
        self._token = token if token is not None else settings.token.get_secret_value()
        self._shop_id = shop_id if shop_id is not None else settings.rollypay_shop_id
        self._timeout = timeout or settings.http_timeout
        self._verify_signature = verify_signature
        if not self._token:
            raise PaymentError("PAYMENT_TOKEN не задан для провайдера Rollypay")

    # ------------------------------------------------------------------ #
    def _url(self, path: str) -> str:
        return f"{self._api_url}/{path.lstrip('/')}"

    def _headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if idempotency_key:
            # Gateway-side protection against double charges.
            headers["Idempotence-Key"] = idempotency_key
        return headers

    def _build_create_payload(self, request: CreatePaymentRequest) -> dict[str, Any]:
        """CHECK AGAINST ROLLYPAY DOCS — this is the one place to adjust."""
        payload: dict[str, Any] = {
            "amount": {
                "value": f"{request.amount_kopeks / 100:.2f}",
                "currency": request.currency.upper(),
            },
            "capture": True,
            "confirmation": {
                "type": "redirect",
                "return_url": request.return_url,
            },
            "description": request.description[:128],
            "metadata": dict(request.metadata),
        }
        if self._shop_id:
            payload["shop_id"] = self._shop_id
        if request.email:
            payload["receipt"] = {"email": request.email, "customer_email": request.email}
        return payload

    @staticmethod
    def _extract(data: Any) -> tuple[str | None, PaymentStatus, int | None, str | None]:
        payment_id = _dig(data, _ID_KEYS)
        status = normalize_status(_dig(data, _STATUS_KEYS))
        amount = to_kopeks(_dig(data, _AMOUNT_KEYS))
        confirm = _dig(data, _CONFIRM_KEYS)
        return (
            str(payment_id) if payment_id else None,
            status,
            amount,
            str(confirm) if confirm else None,
        )

    async def _post(
        self, path: str, payload: dict[str, Any], *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                response = await client.post(
                    self._url(path), json=payload, headers=self._headers(idempotency_key=idempotency_key)
                )
            except httpx.HTTPError as exc:
                raise PaymentError(f"Rollypay недоступен: {exc}") from exc

        if response.status_code >= 400:
            log.error("rollypay.http_error", path=path, status=response.status_code, body=response.text[:300])
            raise PaymentError(f"Rollypay вернул {response.status_code}: {response.text[:200]}")
        return self._json(response)

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                response = await client.get(self._url(path), params=params, headers=self._headers())
            except httpx.HTTPError as exc:
                raise PaymentError(f"Rollypay недоступен: {exc}") from exc
        if response.status_code >= 400:
            log.error("rollypay.http_error", path=path, status=response.status_code, body=response.text[:300])
            raise PaymentError(f"Rollypay вернул {response.status_code}: {response.text[:200]}")
        return self._json(response)

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise PaymentError(f"Rollypay вернул не-JSON: {response.text[:200]}") from exc
        if not isinstance(data, dict):
            return {"data": data}
        return data

    # ------------------------------------------------------------------ #
    async def create_payment(self, request: CreatePaymentRequest) -> PaymentIntent:
        data = await self._post(
            payment_settings.rollypay_create_path,
            self._build_create_payload(request),
            idempotency_key=request.idempotency_key,
        )
        payment_id, status, amount, confirm = self._extract(data)
        if not payment_id:
            raise PaymentError(f"Rollypay не вернул идентификатор платежа: {str(data)[:200]}")
        log.info("rollypay.payment_created", payment_id=payment_id, amount=request.amount_kopeks)
        return PaymentIntent(
            provider=self.name,
            provider_payment_id=payment_id,
            amount_kopeks=amount or request.amount_kopeks,
            currency=request.currency,
            status=status,
            confirmation_url=confirm,
            raw=data,
        )

    async def get_status(self, provider_payment_id: str) -> PaymentIntent:
        data = await self._get(
            payment_settings.rollypay_status_path, {"payment_id": provider_payment_id}
        )
        payment_id, status, amount, _ = self._extract(data)
        return PaymentIntent(
            provider=self.name,
            provider_payment_id=payment_id or provider_payment_id,
            amount_kopeks=amount or 0,
            currency=payment_settings.currency,
            status=status,
            raw=data,
        )

    async def refund(
        self, provider_payment_id: str, amount_kopeks: int | None = None
    ) -> RefundResult:
        payload: dict[str, Any] = {"payment_id": provider_payment_id}
        if amount_kopeks is not None:
            payload["amount"] = {"value": f"{amount_kopeks / 100:.2f}", "currency": payment_settings.currency}
        data = await self._post(payment_settings.rollypay_refund_path, payload)
        return RefundResult(
            provider=self.name,
            provider_refund_id=_dig(data, ("id", "refund_id")),
            amount_kopeks=amount_kopeks or 0,
            status=PaymentStatus.REFUNDED,
            raw=data,
        )

    # -- webhooks -------------------------------------------------------- #
    def verify_signature(self, raw_body: bytes, signature: str | None) -> bool:
        """HMAC-SHA256 of the raw body. Accepts `hex` and `sha256=<hex>` forms."""
        if not signature:
            return False
        signature = signature.strip()
        if signature.lower().startswith("sha256="):
            signature = signature.split("=", 1)[1]
        expected = hmac.new(self._token.encode(), raw_body, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, signature.lower()):
            return True
        # Some gateways send base64 of the same digest.
        try:
            expected_b64 = base64.b64encode(
                hmac.new(self._token.encode(), raw_body, hashlib.sha256).digest()
            ).decode()
            return hmac.compare_digest(expected_b64, signature)
        except Exception:
            return False

    async def verify_webhook(self, payload: bytes, headers: Mapping[str, str]) -> WebhookEvent:
        header = payment_settings.rollypay_signature_header
        signature = None
        for candidate in (header, "signature", "x-signature", "X-Signature", "Authorization"):
            if candidate in headers:
                signature = headers[candidate]
                break

        valid = True
        if self._verify_signature and signature is not None:
            valid = self.verify_signature(payload, signature)
        elif self._verify_signature:
            valid = False

        if not valid:
            log.warning("rollypay.webhook_bad_signature", header=header)
            raise PaymentError("Подпись вебхука Rollypay неверна", code="bad_signature")

        try:
            data = json.loads(payload or b"{}")
        except json.JSONDecodeError as exc:
            raise PaymentError("Тело вебхука не является JSON") from exc

        event_obj = data.get("event") if isinstance(data, dict) else None
        event_type = str(event_obj if isinstance(event_obj, str) else data.get("type", "payment.updated"))
        payment_id, status, amount, _ = self._extract(data)
        if not payment_id:
            raise PaymentError("В вебхуке нет идентификатора платежа")

        return WebhookEvent(
            provider=self.name,
            provider_payment_id=payment_id,
            status=status,
            event_type=event_type,
            amount_kopeks=amount,
            signature_valid=valid,
            raw=data if isinstance(data, dict) else {},
        )

    async def health(self) -> bool:
        try:
            await self._get(payment_settings.rollypay_status_path, {"payment_id": "0"})
        except PaymentError:
            return False
        return True


def fingerprint_sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
