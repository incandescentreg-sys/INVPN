#!/usr/bin/env bash
# =============================================================================
#  Bootstrap a fresh VPS (H1Cloud or any Debian/Ubuntu) for the VPN node.
#
#  Run as root:   bash bootstrap_server.sh
#
#  Installs Xray-core, opens the port, enables the service and prints the
#  host key fingerprint you must pin in SERVER_SSH_HOST_KEY_SHA256.
# =============================================================================
set -euo pipefail

VPN_PORT="${VPN_PORT:-443}"
REALITY_TARGET="${REALITY_TARGET:-www.microsoft.com:443}"
REALITY_SNI="${REALITY_SNI:-www.microsoft.com}"
XRAY_DIR="${XRAY_DIR:-/usr/local/share/xray}"
XRAY_BIN="${XRAY_BIN:-/usr/local/bin/xray}"
XRAY_CONFIG="${XRAY_CONFIG:-/usr/local/etc/xray/config.json}"
XRAY_SERVICE="${XRAY_SERVICE:-/etc/systemd/system/xray.service}"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Запускать от root"

# --------------------------------------------------------------------------- #
log "Обновление системы"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl ca-certificates unzip cron >/dev/null

# --------------------------------------------------------------------------- #
log "Установка Xray-core"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

ARCH="$(uname -m)"
case "$ARCH" in
    x86_64)  ASSET="Xray-linux-64.zip" ;;
    aarch64) ASSET="Xray-linux-arm64-v8a.zip" ;;
    *) die "Неподдерживаемая архитектура: $ARCH" ;;
esac

curl -fsSL -o "$TMP_DIR/xray.zip" \
    "https://github.com/XTLS/Xray-core/releases/latest/download/${ASSET}"
unzip -q "$TMP_DIR/xray.zip" -d "$TMP_DIR/xray"

install -m 755 "$TMP_DIR/xray/xray" "$XRAY_BIN"
install -d "$XRAY_DIR" "$(dirname "$XRAY_CONFIG")"

VERSION="$("$XRAY_BIN" version | head -1)"
log "Установлено: $VERSION"

# --------------------------------------------------------------------------- #
log "Генерация ключей REALITY"
KEYS="$("$XRAY_BIN" x25519)"
PRIVATE_KEY="$(printf '%s\n' "$KEYS" | grep -iE 'private ?key' | awk '{print $NF}')"
PUBLIC_KEY="$(printf '%s\n' "$KEYS" | grep -iE 'password|public ?key' | awk '{print $NF}')"
SHORT_ID="$(openssl rand -hex 8)"

[ -n "$PRIVATE_KEY" ] || die "Не удалось получить приватный ключ"
[ -n "$PUBLIC_KEY" ]  || die "Не удалось получить публичный ключ"

# --------------------------------------------------------------------------- #
log "Создание конфигурации"
# Каталог с ключами: доступ к PRIVATE_KEY нужен сервису, но не всем на сервере.
install -d -m 700 "$XRAY_DIR"
umask 077
cat > "$XRAY_DIR/config.json" <<JSON
{
  "log": {
    "loglevel": "warning",
    "access": "/var/log/xray/access.log",
    "error": "/var/log/xray/error.log"
  },
  "inbounds": [
    {
      "tag": "inbound-vless",
      "listen": "0.0.0.0",
      "port": ${VPN_PORT},
      "protocol": "vless",
      "settings": {
        "clients": [],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "target": "${REALITY_TARGET}",
          "xver": 0,
          "serverNames": ["${REALITY_SNI}"],
          "privateKey": "${PRIVATE_KEY}",
          "shortIds": ["${SHORT_ID}"],
          "spiderX": "/"
        }
      },
      "sniffing": {
        "enabled": true,
        "destOverride": ["http", "tls", "quic"]
      }
    }
  ],
  "outbounds": [
    { "protocol": "freedom", "tag": "direct" },
    { "protocol": "blackhole", "tag": "block" }
  ],
  "routing": {
    "rules": [
      {
        "type": "field",
        "inboundTag": ["inbound-vless"],
        "domain": ["geosite:category-ads-all"],
        "outboundTag": "block"
      }
    ]
  }
}
JSON
chmod 640 "$XRAY_DIR/config.json"

install -d -m 755 /var/log/xray

# --------------------------------------------------------------------------- #
log "Systemd-юнит"
cat > "$XRAY_SERVICE" <<UNIT
[Unit]
Description=Xray Service (VLESS + REALITY)
Documentation=https://xtls.github.io/
After=network-online.target nss-lookup.target
Wants=network-online.target

[Service]
User=nobody
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
NoNewPrivileges=true
ExecStart=${XRAY_BIN} run -c ${XRAY_DIR}/config.json
Restart=on-failure
RestartPreventExitStatus=23
LimitNPROC=10000
LimitNOFILE=1000000

[Install]
WantedBy=multi-user.target
UNIT

"$XRAY_BIN" run -test -c "$XRAY_DIR/config.json"
log "Конфигурация валидна"

systemctl daemon-reload
systemctl enable --now xray
systemctl reload xray 2>/dev/null || systemctl restart xray
sleep 1
systemctl is-active xray >/dev/null || die "Xray не запустился"

# --------------------------------------------------------------------------- #
log "Файрвол"
if command -v ufw >/dev/null 2>&1; then
    ufw allow "${VPN_PORT}/tcp" >/dev/null 2>&1 || true
fi

# --------------------------------------------------------------------------- #
# Переносим конфиг по пути из .env, чтобы приложение писало туда же.
if [ "$XRAY_CONFIG" != "$XRAY_DIR/config.json" ]; then
    log "Дублирую конфигурацию в $XRAY_CONFIG"
    install -m 640 "$XRAY_DIR/config.json" "$XRAY_CONFIG"
fi

HOST_KEY="$(ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub 2>/dev/null | awk '{print $2}')"

cat <<SUMMARY

============================================================================
  Готово. Скопируйте эти значения в .env вашего приложения:

  SERVER_HOST=<ip-сервера>
  SERVER_PORT=22
  SERVER_USER=root
  SERVER_SSH_KEY="-----BEGIN OPENSSH PRIVATE KEY-----\\n...\\n-----END OPENSSH PRIVATE KEY-----"
  SERVER_SSH_HOST_KEY_SHA256=${HOST_KEY}

  VPN_DOMAIN=${REALITY_SNI}
  VPN_PORT=${VPN_PORT}

  XRAY_CONFIG_PATH=${XRAY_DIR}/config.json
  XRAY_SERVICE_NAME=xray
  REALITY_TARGET=${REALITY_TARGET}
  REALITY_SERVER_NAMES=${REALITY_SNI}
  REALITY_SHORT_IDS=${SHORT_ID}

  # public key попадает в клиентскую ссылку, он уже сохранён в базе
  REALITY public key: ${PUBLIC_KEY}
  REALITY shortId:    ${SHORT_ID}
============================================================================

  Проверить состояние:  systemctl status xray
  Логи:                 journalctl -u xray -f
  Тест конфига:         ${XRAY_BIN} run -test -c ${XRAY_DIR}/config.json
SUMMARY
