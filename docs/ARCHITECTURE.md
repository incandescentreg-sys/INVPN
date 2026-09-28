# Архитектура

## Слои

```
api/          HTTP-слой: Depends, роутеры, схемы. Без бизнес-правил.
services/     Бизнес-логика: покупка, продление, выдача конфигов, статистика.
repositories/ Доступ к данным. Только запросы к БД.
models/       ORM. Единственное место, где описана структура данных.
payments/     Абстракция платёжного шлюза (PaymentProvider).
vpn/          Управление Xray: SSH, конфиг, ключи REALITY, ссылки.
workers/      Фоновые задачи (общие для Vercel Cron и APScheduler).
bot/          aiogram: хендлеры, клавиатуры, middleware.
```

Правило зависимостей: `api → services → repositories → models`.
`vpn` и `payments` — «внешние» порты, которые знают только сервисы.

## Поток покупки

```
1. Web App           POST /api/v1/payments {plan_id}
2. PaymentService    проверяет тариф, ищет существующий заказ по idempotency_key,
                     создаёт Subscription(status=PENDING), затем вызывает
                     PaymentProvider.create_payment()
3. PaymentProvider   возвращает provider_payment_id + confirmation_url
4. Web App           открывает confirmation_url (страница шлюза)
5. Шлюз              POST /api/v1/webhooks/{provider}
6. PaymentService    проверяет подпись, сверяет сумму, в transaction:
                       payment.status = succeeded
                       subscription → active (+дни к тарифу)
                       назначает VPN-сервер
7. VpnService        выпускает UUID, пишет VpnClient(status=PENDING)
8. XrayManager       один SSH-сеанс: read → merge → `xray -test` → atomic
                     write → restart; затем статус клиента → active
```

Ключевые свойства:

- **Идемпотентность.** `PaymentService.confirm_payment()` берёт `SELECT ... FOR
  UPDATE` и выходит, если платёж уже `succeeded`. Повторный вебхук безопасен.
- **Сверка суммы.** Сумма из вебхука сверяется с суммой заказа; расхождение
  → `failed`, доступ не выдаётся.
- **Устойчивость к недоступности Xray.** Ошибка SSH не отменяет оплату:
  подписка активна, клиент остаётся `PENDING`, задача `sync-xray` его применит.
- **Повторная синхронизация.** `VpnService.sync_server()` делает БД → Xray
  reconcile и пишет результат обратно. Работает и по вебхуку, и по крону.

## Синхронизация Xray

`XrayManager.apply_sync(desired)` выполняет в **одном** SSH-сеансе:

1. `ensure_inbound()` — создаёт inbound, если его нет;
2. `set_reality()` — ключи, SNI, shortId;
3. `apply_clients()` — сверяет список клиентов (добавление / обновление /
   удаление), сохраняя порядок и неизвестные ключи конфига;
4. `backup_config()` — копия перед записью;
5. атомарная запись (temp + `mv`);
6. `xray run -test -c ...` — Xray сам валидирует конфиг;
7. при ошибке — откат из бэкапа и рестарт;
8. `systemctl restart xray`.

Проверка перед записью — ключевая деталь: сломанный конфиг никогда не
попадёт на работающий сервер.

## Слои данных

| Таблица | Назначение |
|---|---|
| `users` | Telegram-аккаунты, модерация |
| `plans` | Тарифы: дни, цена, признаки |
| `vpn_servers` | Узлы: SSH, Xray, REALITY, здоровье |
| `subscriptions` | Оплаченный доступ: статус, сроки, сервер |
| `vpn_clients` | По одному VLESS-UUID на устройство |
| `payments` | Заказы, внешние id, статусы, возвраты |
| `payment_events` | Сырые события шлюза (аудит, отладка) |
| `notifications` | Лента уведомлений в приложении |
| `expiry_reminders` | Дедупликация напоминаний (уникальность подписка+дни) |
| `subscription_events` | Аудит переходов статусов |

## Деньги

Везде целые копейки. `price_kopeks`, `amount_kopeks`, `refunded_kopeks`.
Форматирование — только на границе (`app/utils/money.py`).

## Время

Все `DateTime(timezone=True)` проходят через `TZDateTime`, который всегда
возвращает aware-значение в UTC. Это важно: часть драйверов (и SQLite в
тестах) отдаёт naive-даты, и сравнение с `now(UTC)` падает.

## Авторизация

```
Web App → initData → POST /auth/telegram → проверка HMAC → JWT (12 ч)
```

- `verify_init_data()` реализует алгоритм Telegram: `secret = HMAC_SHA256(
  bot_token, "WebAppData")`, затем `hash = HMAC_SHA256(secret,
  data_check_string)`. Плюс проверка `auth_date`.
- API принимает и JWT (`Authorization: Bearer`), и сырой `initData`
  (`X-Telegram-Init-Data`) — удобно для первых запросов из браузера.
- `/auth/me` доступен забаненным (чтобы показать причину), остальные
  эндпоинты — нет.
- Админ проверяется по `ADMIN_TELEGRAM_IDS`; флаг в БД синхронизируется при
  каждом входе.
- Фоновые задачи — `Authorization: Bearer $CRON_SECRET`.

## Расширение

- **Второй VPS:** «Админ → Серверы → Добавить». Сервис сам выбирает наименее
  загруженный узел, либо тариф можно закрепить за конкретным сервером.
- **Новый тариф:** админка или `SEED_PLANS_ON_STARTUP`; коды в БД.
- **Новый шлюз:** наследник `PaymentProvider` + запись в `app/payments/`.
- **Celery вместо APScheduler:** задачи в `workers/tasks.py` уже асинхронные
  и не открывают сессий — достаточно обернуть их в таски.
