# Деплой на Vercel — пошаговая инструкция

Важно сначала: **это два разных приложения в двух разных проектах Vercel.**

| | Проект «backend» | Проект «webapp» |
|---|---|---|
| Что это | Python-функция (API + бот) | Статический сайт (React) |
| Папка в репозитории | `backend/` | `webapp/` |
| Домен | `api.example.com` | `vpn.example.com` |
| Что собирает | `@vercel/python` читает `backend/requirements.txt` | `npm run build` → `dist/` |

Секреты (`BOT_TOKEN`, `PAYMENT_TOKEN`, `SERVER_SSH_KEY`, `DATABASE_URL`) живут
**только** в backend-проекте. Во фронтенде их нет и быть не должно.

---

## Шаг 0. Что нужно заранее

- [ ] Аккаунт Vercel
- [ ] Репозиторий в GitHub/GitLab/Bitbucket
- [ ] PostgreSQL (Neon / Supabase / любой managed)
- [ ] VPS с Xray (см. шаг 5) — можно позже, для проверки интерфейса хватит
- [ ] Токен бота от @BotFather

---

## Шаг 1. База данных

Возьмите Neon (бесплатного хватает для старта) и скопируйте **Connection
string**. Нужен драйвер `asyncpg`:

```
postgresql+asyncpg://user:password@ep-xxx.neon.tech/vpn?sslmode=require
```

Примените миграции **локально** — Vercel не запускает Alembic при деплое:

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt
set DATABASE_URL=postgresql+asyncpg://...
alembic upgrade head
```

Успех выглядит так: `Running upgrade  -> 75babc34341d, initial schema`.

---

## Шаг 2. Проект «backend» на Vercel

1. Vercel Dashboard → **Add New → Project** → импортируйте репозиторий.
2. **Root Directory**: `backend`
3. **Framework Preset**: `FastAPI` (если нет — `Other`)
4. **Build & Output Settings**: оставьте как есть, `vercel.json` уже всё задаёт.
   - Install Command: `pip install -r requirements.txt`
5. Environment Variables (Production + Preview):

```
APP_ENV=production
SECRET_KEY=<openssl rand -hex 32>
CRON_SECRET=<openssl rand -hex 32>
DATABASE_URL=postgresql+asyncpg://...

BOT_TOKEN=123456:AA...
WEBAPP_URL=https://vpn.example.com
API_PUBLIC_URL=https://api.example.com
ADMIN_TELEGRAM_IDS=11111111

PAYMENT_PROVIDER=rollypay
PAYMENT_TOKEN=...
PAYMENT_RETURN_URL=https://vpn.example.com/

CORS_ORIGINS=https://vpn.example.com
```

> `CRON_SECRET` Vercel сгенерирует сам, если задан в `vercel.json`? Нет —
> задайте явно: Vercel подставит его в заголовок `Authorization` к cron-запросам.

6. **Deploy**. Запишите выданный домен (`https://backend-xxx.vercel.app`).
7. Проверьте:

```bash
curl https://api.example.com/health
# {"status":"ok","database":"up",...}
```

Если `database: down` — неверная строка подключения.

---

## Шаг 3. Проект «webapp» на Vercel

1. **Add New → Project**, тот же репозиторий.
2. **Root Directory**: `webapp`
3. **Framework Preset**: `Vite`
4. Environment Variables:

```
VITE_API_URL=https://api.example.com/api/v1
```

5. **Deploy**, затем в **Settings → Domains** добавьте `vpn.example.com`.
6. Обновите в backend-проекте `WEBAPP_URL`, `CORS_ORIGINS`,
   `PAYMENT_RETURN_URL` на этот домен и задеплойте снова.

> `VITE_API_URL` вшивается в бандл **на этапе сборки**. Поменяли переменную —
> нужен редеплой, просто Save недостаточно.

---

## Шаг 4. Telegram

1. `@BotFather` → `/newbot` → получите токен → в `BOT_TOKEN` backend-проекта.
2. `@BotFather` → `/setmenubutton` → `https://vpn.example.com`
3. `ADMIN_TELEGRAM_IDS` — узнать свой ID через `@userinfobot`.
4. Вебхук ставится автоматически при старте backend. Проверьте:

```bash
curl https://api.example.com/api/v1/bot/webhook-info
```

Ожидаемый вид: `expected_url` = `https://api.example.com/api/v1/bot/webhook`,
в `remote.pending_update_count` — 0.

> **Важно:** `API_PUBLIC_URL` и `WEBAPP_URL` — это **разные** домены.
> Первый — куда Telegram шлёт апдейты, второй — что открывает пользователь.
> Если указать один вместо другого, бот будет получать `index.html` вместо
> апдейтов. Тест `tests/test_bot_webhook.py` закрывает эту ошибку.

---

## Шаг 5. VPS с Xray (H1Cloud)

```bash
scp backend/scripts/bootstrap_server.sh root@<ip>:/root/
ssh root@<ip> 'bash /root/bootstrap_server.sh'
```

Скрипт поставит Xray, сгенерирует ключи REALITY, включит systemd-юнит и
напечатает готовые значения `.env`, включая `SERVER_SSH_HOST_KEY_SHA256`.

Откройте порт 443 в панели H1Cloud и на сервере:

```bash
ufw allow 443/tcp
```

Перенесите напечатанные значения в backend-проект на Vercel:

```
SERVER_HOST=<ip>
SERVER_USER=root
SERVER_SSH_KEY="-----BEGIN OPENSSH PRIVATE KEY-----\n...\n-----END OPENSSH PRIVATE KEY-----"
SERVER_SSH_HOST_KEY_SHA256=SHA256:xxxx
VPN_DOMAIN=vpn.example.com
VPN_PORT=443
XRAY_CONFIG_PATH=/usr/local/share/xray/config.json
REALITY_TARGET=www.microsoft.com:443
REALITY_SERVER_NAMES=www.microsoft.com
```

> `SERVER_SSH_HOST_KEY_SHA256` обязателен: без него приложение **откажется**
> подключаться (защита от MITM). Значение можно взять из вывода скрипта или
> командой `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`.

---

## Шаг 6. Проверка

По порядку, каждый шаг должен пройти:

```bash
# 1. API жив, БД доступна
curl https://api.example.com/health

# 2. Каталог тарифов
curl https://api.example.com/api/v1/plans

# 3. Cron отрабатывает (нужен ваш CRON_SECRET)
curl -H "Authorization: Bearer $CRON_SECRET" \
     https://api.example.com/api/v1/internal/cron/all

# 4. Вебхук бота указывает на backend
curl https://api.example.com/api/v1/bot/webhook-info
```

Дальше — ручная проверка в Telegram:

1. Откройте бота → `/start` (должна появиться регистрация).
2. Нажмите «🛒 Купить VPN» → откроется Web App.
3. Оплатите (для теста: `PAYMENT_PROVIDER=mock` + `MOCK_PAYMENT_AUTO_CONFIRM=true`).
4. В разделе «📱 Мой VPN» должен появиться `vless://`-конфиг и QR-код.

Если конфиг не появился — смотрите `xray_synced_at` в админке: скорее всего,
Xray недоступен по SSH (проверьте `SERVER_SSH_HOST_KEY_SHA256`).

---

## Vercel Cron

Расписание уже в `backend/vercel.json`:

| Задача | Расписание |
|---|---|
| `expire` — отключение просроченных | каждые 10 мин |
| `sync-xray` — сверка БД с Xray | каждые 15 мин |
| `notify` — напоминания об окончании | ежечасно |
| `reconcile-payments` — подстраховка вебхуков | каждые 5 мин |

**Тариф Hobby ограничивает cron одним запуском в сутки** — при таком тарифе
Vercel не примет расписание чаще. Оставьте только один путь:

```json
"crons": [{ "path": "/api/v1/internal/cron/all", "schedule": "0 3 * * *" }]
```

`/all` выполняет все задачи по очереди. Для коммерческой эксплуатации
нужен **Pro**.

---

## Если хочется одного домена

Когда фронтенд и API на одном имени (например, `vpn.example.com`), в корневом
`vercel.json` добавьте проксирование:

```json
{
  "rewrites": [
    { "source": "/api/:path*", "destination": "https://api.example.com/api/:path*" }
  ]
}
```

Тогда `VITE_API_URL` можно не задавать (клиент возьмёт свой origin), а
`API_PUBLIC_URL` оставить пустым — приложение возьмёт `WEBAPP_URL`.

---

## Типичные ошибки

| Симптом | Причина |
|---|---|
| `ModuleNotFoundError` при деплое | Проверьте, что Root Directory = `backend` |
| `{"status":"degraded"}` в `/health` | Неверный `DATABASE_URL` |
| Бот не отвечает, в логах `webhook_insecure_url` | `API_PUBLIC_URL` пустой или не https |
| Интерфейс грузится, запросы 401 | `VITE_API_URL` вшит в старый бандл → редеплой webapp |
| CORS-ошибки в консоли | `CORS_ORIGINS` не содержит домен фронтенда |
| Конфиг не выдаётся после оплаты | Проверьте SSH: `SERVER_SSH_HOST_KEY_SHA256` |
| Тарифы пустые | `SEED_PLANS_ON_STARTUP=true` и миграции применены |
