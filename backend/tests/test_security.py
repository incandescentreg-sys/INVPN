"""Telegram initData verification and JWT handling."""

from __future__ import annotations

import time

import pytest

from app.utils.exceptions import AuthError
from app.utils.security import (
    TelegramUser,
    create_access_token,
    decode_access_token,
    verify_cron_secret,
    verify_init_data,
)
from tests.conftest import TEST_BOT_TOKEN, make_init_data


def test_valid_init_data_is_accepted() -> None:
    tg = verify_init_data(make_init_data(555000, first_name="Иван", username="ivan"))
    assert tg.id == 555000
    assert tg.first_name == "Иван"
    assert tg.display_name == "Иван"


def test_tampered_hash_is_rejected() -> None:
    data = make_init_data(555001)
    broken = data.replace("hash=", "hash=0")[:-1]
    with pytest.raises(AuthError) as exc:
        verify_init_data(broken)
    assert exc.value.code == "invalid_init_data"


def test_wrong_bot_token_is_rejected() -> None:
    data = make_init_data(555002, bot_token="999:OTHER")
    with pytest.raises(AuthError):
        verify_init_data(data)


def test_missing_hash_is_rejected() -> None:
    with pytest.raises(AuthError):
        verify_init_data("auth_date=1&user=%7B%7D")


def test_expired_init_data_is_rejected() -> None:
    stale = make_init_data(555003, auth_date=int(time.time()) - 100_000)
    with pytest.raises(AuthError) as exc:
        verify_init_data(stale, max_age=3600)
    assert exc.value.code == "init_data_expired"


def test_empty_init_data() -> None:
    with pytest.raises(AuthError):
        verify_init_data("")


# --------------------------------------------------------------------------- #
def test_access_token_roundtrip() -> None:
    token = create_access_token(subject="user-id", telegram_id=42, is_admin=True)
    payload = decode_access_token(token)
    assert payload["sub"] == "user-id"
    assert payload["tid"] == 42
    assert payload["adm"] is True


def test_garbage_token_rejected() -> None:
    with pytest.raises(AuthError):
        decode_access_token("not-a-jwt")


def test_cron_secret_comparison() -> None:
    verify_cron_secret("s3cret", "s3cret")  # no raise
    verify_cron_secret(None, None)  # protection disabled
    with pytest.raises(AuthError):
        verify_cron_secret("wrong", "s3cret")


def test_telegram_user_helpers() -> None:
    tg = TelegramUser(id=1, first_name="А", last_name="Б")
    assert tg.display_name == "А Б"
    assert TelegramUser(id=1, username="u").display_name == "@u"
    assert "is_premium" in tg.to_dict()
    assert TEST_BOT_TOKEN  # fixture token is wired up
