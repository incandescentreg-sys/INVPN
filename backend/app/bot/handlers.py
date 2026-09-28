"""Bot handlers: /start /help /profile /vpn /buy /status /support + menu buttons."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import (
    BTN_BUY,
    BTN_HELP,
    BTN_PAY,
    BTN_PROFILE,
    BTN_SUPPORT,
    BTN_VPN,
    back_to_menu,
    main_menu,
    url_keyboard,
    webapp_keyboard,
)
from app.config import telegram_settings
from app.enums import ClientStatus, SubscriptionStatus
from app.utils.money import format_money

router = Router(name="main")

DATE_FMT = "%d.%m.%Y"


def _fmt(value: datetime | None) -> str:
    return value.strftime(DATE_FMT) if value else "—"


# --------------------------------------------------------------------------- #
# /start and menu
# --------------------------------------------------------------------------- #
@router.message(CommandStart())
async def cmd_start(
    message: Message, current_user: Any, is_new_user: bool, notifications: Any
) -> None:
    if is_new_user:
        # Push the welcome message to the in-app feed as well.
        await notifications.welcome(current_user)
        greeting = (
            f"👋 Привет, {current_user.first_name or 'друг'}!\n\n"
            "Это VPN-сервис с защитой от блокировок (VLESS + REALITY).\n\n"
            "Как начать:\n"
            "1. Нажмите «🛒 Купить VPN»\n"
            "2. Выберите тариф и оплатите\n"
            "3. Конфигурация появится автоматически в разделе «📱 Мой VPN»\n\n"
            "Оплата один раз — доступ навсегда до конца подписки."
        )
    else:
        greeting = (
            f"С возвращением, {current_user.first_name or 'друг'}!\n\n"
            "Выберите действие в меню 👇"
        )

    await message.answer(greeting, reply_markup=main_menu())
    await message.answer(
        "Открыть приложение:",
        reply_markup=webapp_keyboard("🚀 Открыть VPN-приложение"),
    )


@router.message(Command("help"))
@router.message(F.text == BTN_HELP)
async def cmd_help(message: Message) -> None:
    text = (
        "📖 <b>Инструкция</b>\n\n"
        "<b>1. Оплата</b>\nНажмите «🛒 Купить VPN», выберите тариф и оплатите.\n\n"
        "<b>2. Получение конфига</b>\nПосле оплаты в разделе «📱 Мой VPN» появится ссылка "
        "вида <code>vless://…</code> и QR-код.\n\n"
        "<b>3. Установка</b>\n"
        "• Android — Hiddify или v2rayNG\n"
        "• iOS — Streisand\n"
        "• Windows / macOS / Linux — Hiddify Next или NekoRay\n\n"
        "<b>4. Подключение</b>\nВставьте ссылку в приложение, сохраните и включите подключение.\n\n"
        "<b>5. Продление</b>\nТариф продлевается на ту же длительность; срок суммируется.\n\n"
        "⚠️ Не публикуйте свою ссылку — по ней может подключиться кто-то ещё."
    )
    await message.answer(text, reply_markup=main_menu(), parse_mode="HTML")


@router.message(Command("profile"))
@router.message(F.text == BTN_PROFILE)
async def cmd_profile(message: Message, current_user: Any, subscriptions: Any) -> None:
    subscription = await subscriptions.current(current_user.id)
    lines = [
        "👤 <b>Профиль</b>",
        "",
        f"Имя: {current_user.display_name}",
        f"Username: @{current_user.username}" if current_user.username else "Username: —",
        f"ID: <code>{current_user.telegram_id}</code>",
        f"Регистрация: {_fmt(current_user.created_at)}",
    ]
    if subscription is not None:
        lines += [
            "",
            f"Тариф: {subscription.plan.title}",
            f"Статус: {subscription.status.value}",
            f"Действует до: {_fmt(subscription.expires_at)}",
            f"Осталось дней: {subscription.days_left}",
        ]
    else:
        lines += ["", "Активной подписки пока нет. Нажмите «🛒 Купить VPN»."]

    await message.answer("\n".join(lines), reply_markup=main_menu(), parse_mode="HTML")


@router.message(Command("vpn"))
@router.message(F.text == BTN_VPN)
async def cmd_vpn(message: Message, current_user: Any, subscriptions: Any, vpn: Any) -> None:
    subscription = await subscriptions.current(current_user.id)

    if subscription is None:
        await message.answer(
            "У вас пока нет подписки 🙁\n\nНажмите кнопку ниже, чтобы выбрать тариф.",
            reply_markup=webapp_keyboard("🛒 Выбрать тариф"),
        )
        return

    if not subscription.is_usable:
        await message.answer(
            f"⏳ Подписка «{subscription.plan.title}» истекла "
            f"({_fmt(subscription.expires_at)}).\n\nПродлите её, чтобы вернуть доступ.",
            reply_markup=webapp_keyboard("🔄 Продлить подписку"),
        )
        return

    clients = [c for c in subscription.clients if c.status == ClientStatus.ACTIVE]
    header = [
        "📱 <b>Мой VPN</b>",
        "",
        f"Тариф: {subscription.plan.title}",
        f"Действует до: {_fmt(subscription.expires_at)}",
        f"Осталось: {subscription.days_left} дн.",
        f"Устройств: {len(clients)}" + (
            f"/{subscription.device_limit}" if subscription.device_limit else ""
        ),
    ]
    await message.answer("\n".join(header), parse_mode="HTML")

    if not clients:
        await message.answer(
            "Конфигурация ещё не выпущена — откройте приложение, чтобы выпустить её.",
            reply_markup=webapp_keyboard("📱 Выпустить конфиг"),
        )
        return

    # Show the config in the app, and a truncated preview in chat.
    primary = next((c for c in clients if c.is_primary), clients[0])
    links = await vpn.build_links(primary)
    await message.answer(
        "Полная конфигурация, QR-код и управление устройствами — в приложении:",
        reply_markup=webapp_keyboard("📱 Открыть конфигурацию"),
    )
    await message.answer(
        f"Ссылка (скопируйте целиком):\n\n<code>{links.link}</code>",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(Command("buy"))
@router.message(F.text == BTN_BUY)
async def cmd_buy(message: Message) -> None:
    if not telegram_settings.webapp_url:
        await message.answer("Приложение пока не настроено. Попробуйте позже.")
        return
    await message.answer(
        "🛒 <b>Выбор тарифа</b>\n\nОплата проходит в защищённом окне, конфигурация "
        "выдаётся автоматически сразу после оплаты.",
        reply_markup=webapp_keyboard("🛒 Перейти к оплате"),
        parse_mode="HTML",
    )


@router.message(Command("status"))
async def cmd_status(message: Message, current_user: Any, subscriptions: Any) -> None:
    subscription = await subscriptions.current(current_user.id)
    if subscription is None:
        await message.answer("Нет подписок. Выберите тариф: /buy", reply_markup=main_menu())
        return

    status_emoji = {
        SubscriptionStatus.ACTIVE: "✅",
        SubscriptionStatus.EXPIRED: "⌛️",
        SubscriptionStatus.PENDING: "⏳",
        SubscriptionStatus.SUSPENDED: "⛔️",
        SubscriptionStatus.CANCELLED: "🚫",
    }
    paid = subscription.price_paid_kopeks or 0
    text = (
        f"{status_emoji.get(subscription.status, 'ℹ️')} <b>Статус подписки</b>\n\n"
        f"Тариф: {subscription.plan.title}\n"
        f"Состояние: {subscription.status.value}\n"
        f"Оплачено: {format_money(paid, subscription.plan.currency) if paid else '—'}\n"
        f"Начало: {_fmt(subscription.started_at)}\n"
        f"Действует до: {_fmt(subscription.expires_at)}\n"
        f"Осталось: {subscription.days_left} дн."
    )
    keyboard = main_menu() if subscription.is_usable else webapp_keyboard("🔄 Продлить")
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.message(Command("pay"))
@router.message(F.text == BTN_PAY)
async def cmd_pay(message: Message, current_user: Any, payments: Any) -> None:
    rows = await payments.list_for_user(current_user.id, limit=5)
    if not rows:
        await message.answer(
            "Платежей пока нет. Выберите тариф, чтобы начать:",
            reply_markup=webapp_keyboard("🛒 Купить VPN"),
        )
        return

    lines = ["💳 <b>История платежей</b>", ""]
    for payment in rows:
        mark = {"succeeded": "✅", "pending": "⏳", "failed": "❌", "refunded": "↩️"}.get(
            payment.status.value, "•"
        )
        lines.append(
            f"{mark} {format_money(payment.amount_kopeks, payment.currency)} — "
            f"{payment.description or payment.provider} ({_fmt(payment.created_at)})"
        )
    await message.answer("\n".join(lines), reply_markup=main_menu(), parse_mode="HTML")


@router.message(Command("support"))
@router.message(F.text == BTN_SUPPORT)
async def cmd_support(message: Message) -> None:
    username = telegram_settings.support_username
    if username:
        text = (
            "🆘 <b>Поддержка</b>\n\nНе работает подключение? Напишите нам — "
            "обычно отвечаем в течение нескольких минут."
        )
        await message.answer(
            text,
            reply_markup=url_keyboard("✉️ Написать в поддержку", f"https://t.me/{username.lstrip('@')}"),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "🆘 Поддержка\n\nОпишите проблему прямо здесь — мы ответим в этом чате.",
            reply_markup=main_menu(),
        )


# --------------------------------------------------------------------------- #
# Inline callbacks
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery) -> None:
    await callback.message.answer("Главное меню:", reply_markup=main_menu())  # type: ignore[union-attr]
    await callback.answer()


@router.callback_query(F.data == "close")
async def cb_close(callback: CallbackQuery) -> None:
    if callback.message is not None and hasattr(callback.message, "edit_text"):
        await callback.message.edit_text("Готово ✅")
    await callback.answer()


@router.message(F.text == "/start")
async def fallback_start(message: Message) -> None:
    await message.answer("Используйте кнопки в меню 👇", reply_markup=main_menu())


__all__ = ["back_to_menu", "router"]
