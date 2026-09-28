"""User-facing profile, notifications, support and instructions."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import ActiveUser, NotificationSvc, PaymentSvc, SubscriptionSvc
from app.config import telegram_settings
from app.schemas.common import Message
from app.schemas.notification import (
    InstructionsRead,
    NotificationRead,
    SupportInfoRead,
    SupportMessageCreate,
)
from app.schemas.payment import PaymentRead
from app.schemas.subscription import SubscriptionListRead, SubscriptionRead
from app.utils.exceptions import NotFoundError
from app.utils.ids import to_uuid

router = APIRouter(tags=["user"])

@router.get("/profile")
async def profile(user: ActiveUser, subscriptions: SubscriptionSvc) -> dict:
    subscription = await subscriptions.current(user.id)
    return {
        "user": {
            "id": str(user.id),
            "telegram_id": user.telegram_id,
            "username": user.username,
            "display_name": user.display_name,
            "is_admin": user.is_admin,
            "created_at": user.created_at.isoformat(),
            "last_seen_at": user.last_seen_at.isoformat() if user.last_seen_at else None,
        },
        "subscription": subscriptions.summary(subscription) if subscription else None,
        "support_username": telegram_settings.support_username or None,
    }

@router.get("/subscriptions", response_model=SubscriptionListRead)
async def my_subscriptions(
    user: ActiveUser, subscriptions: SubscriptionSvc
) -> SubscriptionListRead:
    history = await subscriptions.list_for_user(user.id)
    return SubscriptionListRead(
        current=SubscriptionRead.from_model(history[0]) if history else None,
        history=[SubscriptionRead.from_model(s) for s in history],
    )

@router.get("/payments", response_model=list[PaymentRead])
async def payment_history(user: ActiveUser, payments: PaymentSvc) -> list[PaymentRead]:
    rows = await payments.list_for_user(user.id)
    return [PaymentRead.from_model(p) for p in rows]

@router.get("/notifications", response_model=list[NotificationRead])
async def notifications(user: ActiveUser, notifications_svc: NotificationSvc) -> list[NotificationRead]:
    rows = await notifications_svc.list_for_user(user.id)
    return [NotificationRead.model_validate(r) for r in rows]

@router.get("/notifications/unread-count", response_model=dict)
async def unread_count(user: ActiveUser, notifications_svc: NotificationSvc) -> dict:
    return {"count": await notifications_svc.unread_count(user.id)}

@router.post("/notifications/{notification_id}/read", response_model=Message)
async def mark_read(
    notification_id: str, user: ActiveUser, notifications_svc: NotificationSvc
) -> Message:
    try:
        nid = to_uuid(notification_id)
    except ValueError as exc:
        raise NotFoundError("Уведомление не найдено") from exc
    await notifications_svc.mark_read(user.id, nid)
    return Message(detail="Прочитано")

@router.post("/notifications/read-all", response_model=Message)
async def mark_all_read(user: ActiveUser, notifications_svc: NotificationSvc) -> Message:
    count = await notifications_svc.mark_all_read(user.id)
    return Message(detail=f"Отмечено прочитанными: {count}")

@router.get("/support", response_model=SupportInfoRead)
async def support_info(user: ActiveUser) -> SupportInfoRead:
    username = telegram_settings.support_username
    url = f"https://t.me/{username.lstrip('@')}" if username else None
    return SupportInfoRead(username=username, url=url)

@router.post("/support", response_model=Message)
async def contact_support(
    payload: SupportMessageCreate, user: ActiveUser, request: Request
) -> Message:
    """Forwards a support message to the operator's Telegram chat."""
    from app.logging_config import get_logger

    log = get_logger(__name__)
    bot = getattr(request.app.state, "bot", None)
    username = telegram_settings.support_username
    text = (
        f"🆘 <b>Обращение из приложения</b>\n\n"
        f"Пользователь: {user.display_name} (<code>{user.telegram_id}</code>)\n"
        f"Сообщение: {payload.text}"
    )
    if bot is not None:
        try:
            if username:
                await bot.send_message(username.lstrip("@"), text, parse_mode="HTML")
            else:
                log.info("support.message_no_chat", user_id=str(user.id), text=payload.text[:500])
        except Exception as exc:
            log.warning("support.send_failed", error=str(exc)[:200])
            raise
    return Message(detail="Сообщение отправлено в поддержку")

@router.get("/instructions", response_model=InstructionsRead)
async def instructions(user: ActiveUser) -> InstructionsRead:
    """Supported clients + short setup notes (copy lives here, not in the UI)."""
    apps = [
        {
            "id": "android",
            "name": "Hiddify",
            "platforms": ["android"],
            "store_url": "https://play.google.com/store/apps/details?id=com.hiddify.hiddify",
            "howto": [
                "Установите приложение из Google Play",
                "Нажмите «Добавить из буфера» или «Открыть ссылку»",
                "Вставьте скопированную ссылку vless:// и сохраните",
                "Включите подключение",
            ],
        },
        {
            "id": "ios",
            "name": "Streisand",
            "platforms": ["ios"],
            "store_url": "https://apps.apple.com/app/streisand/id6458861207",
            "howto": [
                "Установите Streisand из App Store",
                "Нажмите «Import from clipboard»",
                "Вставьте ссылку vless:// и нажмите Import",
                "Выберите сервер и включите VPN",
            ],
        },
        {
            "id": "windows",
            "name": "Hiddify Next",
            "platforms": ["windows", "macos", "linux"],
            "store_url": "https://hiddify.com/",
            "howto": [
                "Скачайте Hiddify Next",
                "Откройте ссылку из приложения — конфигурация добавится сама",
                "Или вставьте ссылку вручную: + → Add from clipboard",
                "Подключитесь к серверу",
            ],
        },
        {
            "id": "android-alt",
            "name": "v2rayNG",
            "platforms": ["android"],
            "store_url": "https://github.com/2dust/v2rayNG",
            "howto": [
                "Установите v2rayNG",
                "Нажмите «+» → Import config from clipboard",
                "Сохраните и включите",
            ],
        },
        {
            "id": "desktop",
            "name": "NekoRay",
            "platforms": ["windows", "linux", "macos"],
            "store_url": "https://github.com/MatsuriDayo/nekoray",
            "howto": ["Скачайте NekoRay", "Импортируйте ссылку из буфера", "Включите подключение"],
        },
    ]
    notes = [
        "Не устанавливайте приложение без нашего конфига — доступ выдаётся только по подписке.",
        "Если приложение не подключается, переключите сервер в разделе «Мой VPN».",
        "Не публикуйте свою ссылку vless:// — по ней может подключиться кто-то ещё.",
    ]
    faq = [
        {
            "q": "Как проверить, что VPN работает?",
            "a": "Откройте https://ipinfo.io или любой сервис проверки IP — должен показаться IP сервера.",
        },
        {
            "q": "Что делать, если не подключается?",
            "a": "Попробуйте другой сервер, переустановите конфиг (кнопка «Обновить конфиг») или напишите в поддержку.",
        },
        {
            "q": "Сколько устройств можно подключить?",
            "a": "Столько, сколько нужно: каждый конфиг — отдельное устройство, старые можно отключать.",
        },
        {
            "q": "Что такое REALITY?",
            "a": "Технология маскировки трафика: сайт выглядит как обычный HTTPS, поэтому его сложно заблокировать.",
        },
    ]
    return InstructionsRead(apps=apps, notes=notes, faq=faq)  # type: ignore[arg-type]