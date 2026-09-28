# VPN Service — Telegram Mini App на VLESS + REALITY

Коммерческий VPN-сервис: Telegram-бот → Web App → API → PostgreSQL → управление
Xray по SSH → VPS. Пользователь оплачивает тариф и автоматически получает
персональный конфиг `vless://`; подписка продлевается, по истечении доступ
отключается, администратор управляет всем из Web App.

```
Telegram Bot ──► Telegram Web App ──► Backend API ──► PostgreSQL
                                              │
                                              ▼
                                    VPN Management (SSH)
                                              │
                                              ▼
                                    VPS / Xray-core
                                              │
                                              ▼
                                     VLESS + REALITY
                                              │
                                              ▼
                                           Интернет
```

## Что умеет

**Пользователь**
- регистрация по `/start` (создаётся в БД автоматически);
- тарифы с ценами из базы, оплата через платёжный шлюз;
- автоматическая выдача `vless://` конфига и QR-кода после оплаты;
- несколько устройств, перевыпуск конфига, отключение устройств;
- срок действия, остаток дней, прогресс-индикатор;
- уведомления об окончании подписки (за 3 дня, за 1 день, в день);
- история платежей, инструкция по установке, поддержка.

**Администратор** (раздел «Админ» в Web App, доступ по `ADMIN_TELEGRAM_IDS`)
- дашборд: выручка, пользователи, активные подписки, график продаж;
- пользователи: поиск, бан/разбан, выдача прав;
- тарифы: создание, изменение цены, отключение;
- платежи: список, возвраты;
- серверы: добавление, проверка, синхронизация Xray, пиннинг host key;
- подписки: продление, приостановка, выдача вручную.

## Стек

| Слой | Технологии |
|---|---|
| Backend | Python 3.12+, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2 |
| БД | PostgreSQL (SQLite — только для тестов) |
| Бот | aiogram 3 (webhook) |
| Платежи | `PaymentProvider` — `mock` и `rollypay` |
| VPN | Xray-core, VLESS + REALITY, asyncssh |
| Фронтенд | React 18, TypeScript, Vite, Telegram Web App SDK |
| Фоновые задачи | Vercel Cron (serverless) или APScheduler (self-hosted) |

## Структура

```
.
├── backend/
│   ├── app/
│   │   ├── main.py            # приложение FastAPI
│   │   ├── config.py          # вся конфигурация из .env
│   │   ├── database.py        # engine и сессии
│   │   ├── enums.py
│   │   ├── models/            # ORM: users, plans, subscriptions, payments, servers, clients
│   │   ├── schemas/           # Pydantic-контракты API
│   │   ├── api/v1/            # роутеры (+ admin/, cron.py, bot.py)
│   │   ├── repositories/      # доступ к данным
│   │   ├── services/          # бизнес-логика
│   │   ├── payments/          # base / mock / rollypay + registry
│   │   ├── vpn/               # ssh, config, reality, link, manager
│   │   ├── workers/           # фоновые задачи + APScheduler
│   │   ├── bot/               # aiogram: хендлеры, клавиатуры, middleware
│   │   └── utils/             # security, crypto, time, money, ids
│   ├── alembic/               # миграции
│   ├── tests/                 # 111 тестов
│   ├── api/index.py           # точка входа для Vercel (Mangum)
│   ├── vercel.json
│   └── Dockerfile
├── webapp/                    # React + TS (Telegram Mini App)
├── docs/                      # DEPLOY.md, ARCHITECTURE.md, XRAY.md, PAYMENTS.md
└── Makefile
```

## Быстрый старт (локально)

```bash
cp .env.example .env          # заполнить BOT_TOKEN, DATABASE_URL
make install                  # venv + pip, npm install
make migrate                  # alembic upgrade head
make dev                      # API :8000, Web App :5173
```

С тестовым платёжным шлюзом (`PAYMENT_PROVIDER=mock`) весь путь от оплаты до
выдачи конфига проходит локально без внешних сервисов.

## Деплой

Коротко: **два проекта на Vercel** — `backend` (serverless Python) и `webapp`
(Vite). Подробно — [docs/DEPLOY.md](docs/DEPLOY.md).

## Проверка

```bash
make test          # 111 тестов: юнит + сквозные сценарии API
make lint          # ruff + tsc --noEmit
make smoke         # быстрый прогон API без БД
```

## Важные документы

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — как устроены слои и поток покупки
- [docs/XRAY.md](docs/XRAY.md) — VLESS/REALITY, безопасный SSH, ключи
- [docs/PAYMENTS.md](docs/PAYMENTS.md) — интеграция Rollypay (раздел 9 ТЗ)
- [docs/DEPLOY.md](docs/DEPLOY.md) — Vercel, Vercel Cron, H1Cloud VPS
