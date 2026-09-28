# Xray, REALITY и безопасный SSH

## Почему VLESS + REALITY

VLESS не шифрует сам протокол (шифрование обеспечивает TLS/REALITY) и не тащит
за собой лишние зависимости. REALITY притворяется обычным TLS-соединением к
чужому сайту: DPI-оборудование видит валидный сертификат и не может отличить
наш трафик от HTTPS, поэтому блокировать его не за что.

| | Устаревший вариант | Используется здесь |
|---|---|---|
| Транспорт | VMess + WebSocket | VLESS + TCP + REALITY |
| Поток | без flow | `xtls-rprx-vision` |
| UUID на клиента | нет | уникальный на устройство |
| Приватность ключа | — | шифрование Fernet, ключ из `SECRET_KEY` |

## Конфигурация

Генерируется программно в `app/vpn/config.py`. Ручная правка на сервере
не нужна: всё, чего скрипт не знает, сохраняется как есть.

```json
{
  "tag": "inbound-vless",
  "listen": "0.0.0.0",
  "port": 443,
  "protocol": "vless",
  "settings": { "clients": [], "decryption": "none" },
  "streamSettings": {
    "network": "tcp",
    "security": "reality",
    "realitySettings": {
      "show": false,
      "target": "www.microsoft.com:443",
      "xver": 0,
      "serverNames": ["www.microsoft.com"],
      "privateKey": "<x25519, 43 символа base64url>",
      "shortIds": ["<8 байт hex>"],
      "spiderX": "/"
    }
  },
  "sniffing": { "enabled": true, "destOverride": ["http", "tls", "quic"] }
}
```

## Ключи REALITY

Генерируются **на стороне приложения** (`app/vpn/reality.py`) через
`cryptography` — на управляющей машине не нужен бинарник Xray:

- private/public — X25519, base64url без padding (43 символа), как ждёт Xray;
- `shortId` — 8 случайных байт в hex (16 символов), чётная длина;
- приватный ключ хранится в БД в зашифрованном виде и **никогда** не
  возвращается через API (проверяет тест `test_server_creation_encrypts_secrets`).

Резервный путь — команда `xray x25519` на сервере. Её вывод менялся между
релизами (`Public key:` → `Password:`), поэтому парсер принимает все известные
подписи.

> Смена приватного ключа ломает **все** клиентские ссылки. `bootstrap_from_env()`
> при обновлении конфигурации ключи не трогает.

## Клиентская ссылка

```
vless://UUID@host:443?type=tcp&security=reality&pbk=PUBLIC_KEY&fp=chrome
        &sni=www.microsoft.com&sid=SHORT_ID&flow=xtls-rprx-vision&spx=%2F#label
```

Собирается в `app/vpn/link.py`; там же deep-ссылки для Hiddify, Streisand,
v2rayNG и NekoRay. Валидация входа: UUID, `pbk`, чётная длина `sid`, непустой SNI.

## Безопасный SSH

Требования из ТЗ и как они реализованы:

| Требование | Реализация |
|---|---|
| Только ключевая аутентификация | `client_keys=[PEM]`; пароли и keyboard-interactive не используются |
| Защита от MITM | host key **обязателен**: `SERVER_SSH_HOST_KEY_SHA256` или `known_hosts`; без пиннинга соединение отклоняется |
| Никаких команд из пользовательского ввода | Команды формирует код; все пути и значения проходят `shlex.quote` |
| Ошибки без утечек | `safe_error()` вычищает PEM-блоки и `password=` из текста исключений |
| Таймауты | `login_timeout`, `keepalive`, повторы с backoff |

Особенность asyncssh: колбэк `validate_host_public_key` вызывается **только**
когда `known_hosts` не `None`. Поэтому для пиннинга отпечатка передаётся пустой
`SSHKnownHosts()` — список доверия остаётся пустым, и каждая проверка проходит
через наш колбэк (`app/vpn/ssh.py`).

Получить отпечаток:

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
# 256 SHA256:xxxxx... root@host (ED25519)
```

## Порядок применения изменений

```
read config ──► merge ──► backup ──► atomic write ──► xray -test ──► restart
                    │                                    │
                    └── clients reconciled                └── on failure:
                                                              restore + restart
```

`xray run -test` проверяет конфиг тем же бинарником, который потом его
загрузит. Сломанный конфиг физически не может попасть на работающий сервер.

## Управление клиентами

- один `VpnClient` = один UUID = одно устройство;
- `email` строится как `u<telegram_id>-<sub>-<username>` — стабильный, чтобы
  ссылка не менялась сама;
- смена UUID обновляет запись на месте (без дублей);
- `delete` помечает клиент `DISABLED`; из конфига он убирается при синхронизации;
- последнее активное устройство удалить нельзя — иначе пользователь останется
  без конфига (409).

## Проверка на сервере

```bash
systemctl status xray
journalctl -u xray -f | tail -50
xray run -test -c /usr/local/share/xray/config.json
ss -Hlnt | grep ':443'
```

Проверка из приложения: `GET /api/v1/vpn/health` (свой узел) или
`GET /api/v1/admin/servers/{id}/health` (любой узел, только для админа).
