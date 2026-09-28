"""Bot keyboards."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from app.config import telegram_settings

BTN_BUY = "🛒 Купить VPN"
BTN_VPN = "📱 Мой VPN"
BTN_PROFILE = "👤 Профиль"
BTN_PAY = "💳 Оплата"
BTN_HELP = "📖 Инструкция"
BTN_SUPPORT = "🆘 Поддержка"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_BUY), KeyboardButton(text=BTN_VPN)],
            [KeyboardButton(text=BTN_PROFILE), KeyboardButton(text=BTN_PAY)],
            [KeyboardButton(text=BTN_HELP), KeyboardButton(text=BTN_SUPPORT)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие 👇",
    )


def webapp_keyboard(button_text: str = "🚀 Открыть приложение") -> InlineKeyboardMarkup:
    if not telegram_settings.webapp_url:
        return InlineKeyboardMarkup(inline_keyboard=[])
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=button_text,
                    web_app=WebAppInfo(url=_webapp_url()),
                )
            ]
        ]
    )


def _webapp_url() -> str:
    url = telegram_settings.webapp_url.rstrip("/")
    if not telegram_settings.webapp_short_name or telegram_settings.webapp_short_name == "app":
        return url
    return f"{url}/{telegram_settings.webapp_short_name}"


def url_keyboard(text: str, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, url=url)]])


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🏠 Меню", callback_data="menu")]]
    )
