"""Payment provider abstraction: normalisation, mock gateway, Rollypay adapter."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from app.enums import PaymentStatus
from app.payments import available_providers, get_provider
from app.payments.base import (
    CreatePaymentRequest,
    PaymentProvider,
    normalize_status,
    to_kopeks,
)
from app.payments.mock import MockPaymentProvider
from app.payments.rollypay import RollypayProvider, _dig
from app.utils.exceptions import PaymentError

TOKEN = "test_shop_secret"


def request_for(amount: int = 29900) -> CreatePaymentRequest:
    return CreatePaymentRequest(
        amount_kopeks=amount,
        currency="RUB",
        description="VPN 30 дней",
        idempotency_key="idem-1",
        return_url="https://app.test/paid",
        metadata={"plan_code": "vpn_30d"},
    )


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("succeeded", PaymentStatus.SUCCEEDED),
        ("SUCCESS", PaymentStatus.SUCCEEDED),
        ("paid", PaymentStatus.SUCCEEDED),
        ("pending", PaymentStatus.PENDING),
        ("waiting", PaymentStatus.PENDING),
        ("in_progress", PaymentStatus.PENDING),
        ("failed", PaymentStatus.FAILED),
        ("rejected", PaymentStatus.FAILED),
        ("cancelled", PaymentStatus.CANCELLED),
        ("canceled", PaymentStatus.CANCELLED),
        ("expired", PaymentStatus.CANCELLED),
        ("refunded", PaymentStatus.REFUNDED),
        ("partially_refunded", PaymentStatus.PARTIALLY_REFUNDED),
        (None, PaymentStatus.PENDING),
        ("", PaymentStatus.PENDING),
        ("something-new", PaymentStatus.PENDING),
    ],
)
def test_normalize_status(raw: str | None, expected: PaymentStatus) -> None:
    assert normalize_status(raw) is expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("299.00", 29900),
        ("299,00", 29900),
        (299.0, 29900),
        (29900, 29900),  # plain ints are already minor units (kopeks)
        ("299", 29900),
        (None, None),
        ("n/a", None),
    ],
)
def test_to_kopeks(raw: object, expected: int | None) -> None:
    assert to_kopeks(raw) == expected


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
def test_registry_lists_providers() -> None:
    assert "mock" in available_providers()
    assert "rollypay" in available_providers()


def test_registry_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Неизвестный платёжный провайдер"):
        get_provider("stripe")


def test_registry_builds_mock() -> None:
    provider = get_provider("mock")
    assert isinstance(provider, MockPaymentProvider)
    assert provider.name == "mock"


def test_rollypay_requires_token() -> None:
    with pytest.raises(PaymentError, match="PAYMENT_TOKEN"):
        RollypayProvider(api_url="https://example.test", token="")


# --------------------------------------------------------------------------- #
# Mock gateway — the full lifecycle used by the Web App
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_mock_payment_lifecycle() -> None:
    provider = MockPaymentProvider()
    intent = await provider.create_payment(request_for())
    assert intent.provider == "mock"
    assert intent.provider_payment_id.startswith("mock_")
    assert intent.status == PaymentStatus.PENDING
    assert "mock_id=" in (intent.confirmation_url or "")

    polled = await provider.get_status(intent.provider_payment_id)
    assert polled.status == PaymentStatus.PENDING

    confirmed = await provider.confirm(intent.provider_payment_id)
    assert confirmed.status == PaymentStatus.SUCCEEDED
    assert confirmed.amount_kopeks == 29900

    refund = await provider.refund(intent.provider_payment_id, 1000)
    assert refund.ok
    assert refund.amount_kopeks == 1000


@pytest.mark.asyncio
async def test_mock_get_status_unknown_id() -> None:
    result = await MockPaymentProvider().get_status("mock_missing")
    assert result.status == PaymentStatus.FAILED


@pytest.mark.asyncio
async def test_mock_webhook_marks_paid() -> None:
    provider = MockPaymentProvider()
    intent = await provider.create_payment(request_for())
    event = await provider.verify_webhook(
        json.dumps({"mock_id": intent.provider_payment_id, "mock_status": "succeeded"}).encode(),
        {},
    )
    assert event.status == PaymentStatus.SUCCEEDED
    assert event.provider_payment_id == intent.provider_payment_id
    assert (await provider.get_status(intent.provider_payment_id)).status == PaymentStatus.SUCCEEDED


def test_base_provider_requires_the_contract() -> None:
    class Incomplete(PaymentProvider):
        name = "incomplete"

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


# --------------------------------------------------------------------------- #
# Rollypay adapter (offline: payload building, extraction, signatures)
# --------------------------------------------------------------------------- #
def make_rollypay() -> RollypayProvider:
    return RollypayProvider(api_url="https://api.rollypay.test/v1", token=TOKEN)


def test_rollypay_create_payload_shape() -> None:
    payload = make_rollypay()._build_create_payload(request_for())
    assert payload["amount"] == {"value": "299.00", "currency": "RUB"}
    assert payload["confirmation"]["return_url"] == "https://app.test/paid"
    assert payload["description"] == "VPN 30 дней"
    assert payload["metadata"]["plan_code"] == "vpn_30d"
    assert payload["capture"] is True


@pytest.mark.parametrize(
    "body,expected_id,expected_status,expected_amount",
    [
        ({"id": "p1", "status": "succeeded", "amount": "299.00"}, "p1", PaymentStatus.SUCCEEDED, 29900),
        ({"payment": {"id": "p2", "status": "pending", "amount": 1000}}, "p2", PaymentStatus.PENDING, 1000),
        ({"data": {"payment_id": "p3", "state": "paid"}}, "p3", PaymentStatus.SUCCEEDED, None),
        ({"order": {"uuid": "p4", "status": "failed"}}, "p4", PaymentStatus.FAILED, None),
    ],
)
def test_rollypay_extract_handles_shapes(
    body: dict, expected_id: str, expected_status: PaymentStatus, expected_amount: int | None
) -> None:
    got_id, got_status, got_amount, _ = RollypayProvider._extract(body)
    assert got_id == expected_id
    assert got_status is expected_status
    assert got_amount == expected_amount


def test_rollypay_extract_finds_nested_values() -> None:
    assert _dig({"result": {"payment": {"confirmation_url": "https://pay"}}}, ("confirmation_url",)) == (
        "https://pay"
    )


def test_rollypay_signature_verification() -> None:
    provider = make_rollypay()
    body = b'{"id":"p1","status":"succeeded"}'
    digest = hmac.new(TOKEN.encode(), body, hashlib.sha256).hexdigest()

    assert provider.verify_signature(body, digest) is True
    assert provider.verify_signature(body, f"sha256={digest}") is True
    assert provider.verify_signature(body, digest.upper()) is True
    assert provider.verify_signature(body, "deadbeef") is False
    assert provider.verify_signature(body, "") is False
    # a body that was tampered with must not validate
    assert provider.verify_signature(body + b"x", digest) is False


@pytest.mark.asyncio
async def test_rollypay_webhook_accepts_valid_signature() -> None:
    provider = make_rollypay()
    body = json.dumps({"id": "p1", "status": "succeeded", "amount": "299.00"}).encode()
    digest = hmac.new(TOKEN.encode(), body, hashlib.sha256).hexdigest()
    event = await provider.verify_webhook(body, {"signature": digest})
    assert event.status == PaymentStatus.SUCCEEDED
    assert event.amount_kopeks == 29900
    assert event.signature_valid is True


@pytest.mark.asyncio
async def test_rollypay_webhook_rejects_bad_signature() -> None:
    provider = make_rollypay()
    body = b'{"id":"p1","status":"succeeded"}'
    with pytest.raises(PaymentError, match="Подпись"):
        await provider.verify_webhook(body, {"signature": "0" * 64})


@pytest.mark.asyncio
async def test_rollypay_webhook_requires_payment_id() -> None:
    provider = make_rollypay()
    body = b'{"status":"succeeded"}'
    digest = hmac.new(TOKEN.encode(), body, hashlib.sha256).hexdigest()
    with pytest.raises(PaymentError, match="идентификатор"):
        await provider.verify_webhook(body, {"signature": digest})
