# Деплой

Проект рассчитан на **два независимых приложения Vercel** (backend и Web App)
и **один VPS с Xray**. Ниже — пошаговая инструкция.

---

## 0. Схема

```
Vercel (backend)  ────  Neon / Postgres  ◄──── VPS с Xray (по SSH)
      │                                              ▲
      └──── Vercel (webapp, static)  ────────────────┘
                    ▲
                 Telegram
```

Приложение (Web App) и бот живут на **одном домене**: `https://vpn.example.com`.
На нём же работает вебхук бота, поэтому `WEBAPP_URL` указывает на корень
фронтенда.

---

## 1. База данных

1. Создайте PostgreSQL (Vercel Postgres устарел — берите Neon, Supabase или
   любой managed-Postgres).
2. Скопируйте строку подключения. Нужен **asyncpg**:

   ```
   postgresql+asyncpg://user:password@host/db?sslmode=require
   ```

3. Прогоните миграции локально (Vercel не запускает Alembic при деплое):

   ```bash
   cd backend
   pip install -r requirements.txt
   DATABASE_URL="postgresql+asyncpg://..." alembic upgrade head
   ```

---

## 2. Backend на Vercel

1. `vercel link` в каталоге `backend/`, Framework Preset — **FastAPI**
   (или Other), Root Directory — `backend`.
2. Переменные окружения (Settings → Environment Variables):

   ```
   APP_ENV=production
   SECRET_KEY=<openssl rand -hex 32>
   DATABASE_URL=postgresql+asyncpg://...
   CRON_SECRET=<openssl rand -hex 32>      # Vercel подставит в cron-запросы
   BOT_TOKEN=123456:AA...
   WEBAPP_URL=https://vpn.example.com        # домен ФРОНТЕНДА
   API_PUBLIC_URL=https://api.example.com    # домен БЭКЕНДА (вебхук бота)
   ADMIN_TELEGRAM_IDS=11111111,22222222
   PAYMENT_PROVIDER=rollypay
   PAYMENT_TOKEN=...
   PAYMENT_RETURN_URL=https://vpn.example.com/
   SERVER_HOST=<ip-vps>
   SERVER_USER=root
   SERVER_SSH_KEY="-----BEGIN OPENSSH PRIVATE KEY-----\n...\n-----END OPENSSH PRIVATE KEY-----"
   SERVER_SSH_HOST_KEY_SHA256=SHA256:xxxx
   VPN_DOMAIN=vpn.example.com
   VPN_PORT=443
   XRAY_CONFIG_PATH=/usr/local/share/xray/config.json
   REALITY_TARGET=www.microsoft.com:443
   REALITY_SERVER_NAMES=www.microsoft.com
   CORS_ORIGINS=https://vpn.example.com
   ```

3. `vercel deploy --prod`

### Ограничения serverless, о которых нужно помнить

| Ограничение | Как мы его обходим |
|---|---|
| Нет долгоживущих процессов | Бот работает на вебхуке, задачи — через Vercel Cron |
| Заморозка после ответа | Все операции выполняются внутри одного запроса |
| Таймаут (60 с Hobby / до 300 с Pro) | Синхронизация Xray идёт в **одном** SSH-сеансе; `maxDuration` настраивается в `vercel.json` |
| Нет общего состояния | Кэш в Redis (опционально), источник истины — PostgreSQL |
| Read-only FS | Файлы Xray пишутся только по SSH на VPS |

Для коммерческой эксплуатации нужен **тариф Pro**: только там cron запускается
чаще одного раза в сутки.

---

## 3. Vercel Cron

`backend/vercel.json` уже содержит расписание:

| Задача | Расписание | Что делает |
|---|---|---|
| `/api/v1/internal/cron/expire` | каждые 10 мин | отключает просроченных |
| `/api/v1/internal/cron/sync-xray` | каждые 15 мин | сверяет БД с Xray |
| `/api/v1/internal/cron/notify` | ежечасно | напоминания об окончании |
| `/api/v1/internal/cron/reconcile-payments` | каждые 5 мин | подстраховка вебхуков |

Vercel отправляет `Authorization: Bearer $CRON_SECRET` — эндпоинты проверяют его.
Проверить вручную:

```bash
curl -H "Authorization: Bearer $CRON_SECRET" https://api.example.com/api/v1/internal/cron/all
```

На Hobby (cron раз в сутки) оставьте **только** `/all` — он выполняет все задачи
последовательно.

---

## 4. Web App на Vercel

1. Отдельный проект, Root Directory — `webapp`, Framework — **Vite**.
2. Build-аргумент:

   ```
   VITE_API_URL=https://api.example.com/api/v1
   ```

   Значение вшивается на этапе сборки — поменяете в Vercel, пересоберёте деплой.
3. Домен: `vpn.example.com` (тот же, что в `WEBAPP_URL`).

Пошаговая версия со всеми проверками — [VERCEL_DEPLOY.md](VERCEL_DEPLOY.md).

### Проксирование (вариант без второго проекта)

Если хотите один домен и один Vercel-проект, добавьте в корневой
`vercel.json` редирект:

```json
{
  "rewrites": [
    { "source": "/api/(.*)", "destination": "https://api.example.com/api/$1" }
  ]
}
```

Тогда `VITE_API_URL` можно не задавать — клиент возьмёт текущий origin.

---

## 5. VPS с Xray (H1Cloud)

```bash
scp backend/scripts/bootstrap_server.sh root@<ip>:/root/
ssh root@<ip> 'bash /root/bootstrap_server.sh'
```

Скрипт установит Xray, сгенерирует ключи REALITY, включит systemd-юнит и
напечатает готовые значения для `.env`, включая `SERVER_SSH_HOST_KEY_SHA256`.

Обязательно откройте порт в панели H1Cloud и на файрволе:

```bash
ufw allow 443/tcp
```

### Проверка ключа вручную (второй раз, для контроля)

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
# 256 SHA256:xxxx... root@hostname (ED25519)
```

Значение должно совпадать с `SERVER_SSH_HOST_KEY_SHA256`. Приложение **откажется**
подключаться при несовпадении.

---

## 6. Telegram

1. `@BotFather` → `/newbot` → получите `BOT_TOKEN`.
2. `/setmenubutton` → укажите `https://vpn.example.com`.
3. `ADMIN_TELEGRAM_IDS` — ID администраторов (узнать: `@userinfobot`).
4. Вебхук ставится автоматически при старте приложения
   (`WEBAPP_URL + /api/v1/bot/webhook`). Проверить:

   ```bash
   curl https://api.example.com/api/v1/bot/webhook-info
   ```

---

## 7. Каталог тарифов

Цена не зашита в код. При первом запуске создаётся тариф из `SEED_PLAN_30D_*`.
Дальше меняйте в админке: «Админ → Тарифы».

Все суммы хранятся в **копейках** (`29900` = 299 ₽) — float не используется.

---

## 8. Альтернатива: self-hosted

Docker Compose поднимает всё на одном сервере, включая фоновые задачи:

```bash
cp .env.example .env && docker compose up -d --build
docker compose exec api alembic upgrade head
```

Фоновые задачи запускаются отдельным процессом:

```bash
docker compose exec api python -m app.workers.scheduler
```

---

## 9. Чек-лист перед запуском

- [ ] `SECRET_KEY` и `CRON_SECRET` — случайные значения
- [ ] `APP_ENV=production` (иначе включаются `/docs`)
- [ ] `SERVER_SSH_HOST_KEY_SHA256` задан и совпадает
- [ ] `ADMIN_TELEGRAM_IDS` не пуст
- [ ] `PAYMENT_PROVIDER=rollypay` + `PAYMENT_TOKEN`, пути сверены с документацией
- [ ] `CORS_ORIGINS` содержит домен Web App
- [ ] Миграции применены
- [ ] `/health` возвращает `status: ok`
- [ ] Тестовая покупка проходит от `/plans` до выдачи `vless://`
- [ ] На VPS `systemctl is-active xray` → `active`
