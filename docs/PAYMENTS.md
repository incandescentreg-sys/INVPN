# Платежи (раздел 9 ТЗ)

## Абстракция

Бизнес-логика не знает ни одного шлюза. Контракт — `app/payments/base.py`:

```python
class PaymentProvider(abc.ABC):
    name: ClassVar[str]

    async def create_payment(self, request: CreatePaymentRequest) -> PaymentIntent: ...
    async def get_status(self, provider_payment_id: str) -> PaymentIntent: ...
    async def refund(self, provider_payment_id: str, amount_kopeks: int | None = None) -> RefundResult: ...
    async def verify_webhook(self, payload: bytes, headers: Mapping[str, str]) -> WebhookEvent: ...
    async def health(self) -> bool: ...
```

Реализации: `MockPaymentProvider` (локально и в тестах) и `RollypayProvider`.
Выбор — переменная `PAYMENT_PROVIDER`, регистрация — в `app/payments/__init__.py`.

## Статусы

Шлюзы описывают состояние по-разному, поэтому всё приводится к одному перечислению
функцией `normalize_status()`:

| Наш статус | Что значит |
|---|---|
| `pending` | создан, ждём оплаты |
| `succeeded` | оплата получена, доступ выдан |
| `failed` | отказ банка / шлюза |
| `cancelled` | отменён пользователем или истёк |
| `refunded` / `partially_refunded` | возврат |

## Суммы

`to_kopeks()` — явное правило, потому что формат у шлюзов разный:

- строка и float — **основные единицы** («299.00» и «299» → 29900 копеек);
- int — уже минорные единицы, возвращается как есть;
- нечитаемое значение → `None`, сумма считается неизвестной, а не угаданной.

## Webhook

`POST /api/v1/webhooks/{provider}`

1. `verify_webhook()` проверяет подпись (HMAC-SHA256 по сырому телу).
2. Ответ `event` попадает в `payment_events` — для аудита.
3. `succeeded` → `confirm_payment()`: блокировка строки, сверка суммы,
   активация подписки, выдача конфига.
4. Неизвестный платёж или повтор → **200 OK**: иначе шлюз будет ретраить
   бесконечно.

Возвраты инициируются из админки:
`POST /api/v1/admin/payments/{id}/refund?amount_kopeks=...`

Дополнительно `POST /api/v1/internal/cron/reconcile-payments` спрашивает шлюз
обо всех незакрытых платежах — страховка, если вебхук потерялся.

---

## Rollypay

> **Важно.** При написании кода публичная документация Rollypay была
> недоступна: `rollypay.com` отдаёт парковочную страницу, а
> `api.rollypay.com` не проходит проверку сертификата. Поэтому точный контракт
> нужно сверить с их документацией. Всё остальное — нормализация статусов,
> идемпотентность, подписи, возвраты, обработка вебхуков — реализовано полностью
> и от формы запросов не зависит.

### Что проверить/поправить

Две точки, которые правятся без изменения архитектуры:

**1. Пути эндпоинтов** — `.env` (или `app/config.py`):

```
ROLLYPAY_API_URL=https://api.rollypay.com/v1
ROLLYPAY_CREATE_PATH=/goods/create
ROLLYPAY_STATUS_PATH=/goods/info
ROLLYPAY_REFUND_PATH=/goods/refund
ROLLYPAY_WEBHOOK_PATH=/hook/rollypay
```

**2. Тело запроса** — `RollypayProvider._build_create_payload()` в
`app/payments/rollypay.py`. Сейчас используется YooKassa-подобная схема, которую
Rollypay наследует:

```json
{
  "amount": { "value": "299.00", "currency": "RUB" },
  "capture": true,
  "confirmation": { "type": "redirect", "return_url": "https://…" },
  "description": "VPN 30 дней",
  "metadata": { "user_id": "…", "plan_code": "vpn_30d", "payment_id": "…" }
}
```

Если у Rollypay имена отличаются — правьте только этот метод.

### Разбор ответа

`_extract()` устойчив к форме ответа: ищет `id` / `payment_id` / `paymentId` /
`uuid` / `order_id`, статус в `status` / `state` / `payment_status`, сумму в
`amount` / `amount_value` / `total`, ссылку в `confirmation_url` /
`confirmationUrl` / `redirect_url` / `url` / `pay_url`, в том числе во вложенных
объектах `payment`, `data`, `result`, `order`, `goods`, `response`.

### Подпись вебхука

HMAC-SHA256 от сырого тела запроса. Принимаются формы `hex`,
`sha256=<hex>` и base64; заголовок задаётся `ROLLYPAY_SIGNATURE_HEADER`.
Запрос без подписи отклоняется, если проверка включена.

### Ошибки

- сетевые/HTTP-ошибки → `PaymentError` (HTTP 402), платёж остаётся `pending`;
- нечитаемый ответ → `PaymentError` с текстом ответа (секретов там нет);
- расхождение суммы → платёж переводится в `failed`, доступ не выдаётся.

### Проверка без реальных денег

```bash
PAYMENT_PROVIDER=mock MOCK_PAYMENT_AUTO_CONFIRM=true make dev
```

Далее: Web App → «Тарифы» → «Оплатить» → оплата подтверждается сразу, конфиг
выдаётся. С `MOCK_PAYMENT_AUTO_CONFIRM=false` платёж висит в `pending`, пока
вебхук не придёт:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/webhooks/mock \
  -H 'Content-Type: application/json' \
  -d '{"mock_id":"mock_...","mock_status":"succeeded","amount":"299.00"}'
```

---

## Добавление нового шлюза

1. Создать `app/payments/<name>.py` с наследником `PaymentProvider`.
2. Зарегистрировать в `_PROVIDERS` (`app/payments/__init__.py`).
3. Добавить блок настроек в `PaymentSettings` и переменные в `.env.example`.
4. Покрыть тестами: `tests/test_payments.py` (нормализация, подпись, разбор
   ответа) и добавить сценарий в `tests/test_api_flow.py`.

Логика выдачи доступа не меняется — она живёт в `PaymentService`.
