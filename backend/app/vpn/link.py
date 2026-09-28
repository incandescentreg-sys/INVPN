"""Client link generation: vless:// links and per-app deep links.

Format (VLESS + REALITY + XTLS Vision)::

    vless://UUID@host:port?type=tcp&security=reality&pbk=PUBLIC_KEY
                 &fp=chrome&sni=SNI&sid=SHORT_ID&flow=xtls-rprx-vision
                 &spx=%2F#label
"""

from __future__ import annotations

import base64
import uuid as uuid_lib
from dataclasses import dataclass
from urllib.parse import quote, urlencode

from app.vpn.reality import is_valid_key


@dataclass(frozen=True, slots=True)
class LinkParams:
    client_uuid: str
    host: str
    port: int
    public_key: str
    server_name: str
    short_id: str
    fingerprint: str = "chrome"
    flow: str = "xtls-rprx-vision"
    network: str = "tcp"
    spider_x: str = "/"
    label: str = "VPN"


def _validate(params: LinkParams) -> None:
    try:
        uuid_lib.UUID(params.client_uuid)
    except ValueError as exc:
        raise ValueError(f"Некорректный UUID клиента: {params.client_uuid!r}") from exc
    if not is_valid_key(params.public_key):
        raise ValueError("Некорректный public key REALITY (pbk)")
    if not params.short_id or len(params.short_id) % 2:
        raise ValueError("shortId должен быть hex-строкой чётной длины")
    if not params.server_name:
        raise ValueError("Пустой SNI (serverName)")


def build_vless_link(params: LinkParams) -> str:
    _validate(params)
    query = urlencode(
        {
            "type": params.network,
            "security": "reality",
            "pbk": params.public_key,
            "fp": params.fingerprint,
            "sni": params.server_name,
            "sid": params.short_id,
            "flow": params.flow,
            "spx": params.spider_x,
            "alpn": "h3,h2,http/1.1",
        },
        quote_via=quote,
        safe="",
    )
    userinfo = params.client_uuid
    return f"vless://{userinfo}@{params.host}:{params.port}?{query}#{quote(params.label, safe='')}"


def base64_link(link: str) -> str:
    """Some clients expect a base64 blob instead of a raw vless:// URL."""
    return base64.b64encode(link.encode()).decode()


# --------------------------------------------------------------------------- #
# One-tap import deep links
# --------------------------------------------------------------------------- #
def hiddify_link(link: str) -> str:
    return f"hiddify://add/{quote(link, safe='')}"


def streisand_link(link: str) -> str:
    return f"streisand://import-profile/{quote(link, safe='')}"


def v2rayng_link(link: str) -> str:
    return f"v2rayng://install-sub?url={quote(link, safe='')}"


def nekoray_link(link: str) -> str:
    return f"nekoray://import/{quote(link, safe='')}"


def v2rayn_link(link: str) -> str:
    return f"v2rayN://install-config?url={quote(link, safe='')}"


def shadowrocket_link(link: str) -> str:
    return f"shadowrocket://add/sub://{quote(base64_link(link), safe='')}"


DEEP_LINKS = {
    "Hiddify": hiddify_link,
    "Streisand": streisand_link,
    "v2rayNG": v2rayng_link,
    "NekoRay": nekoray_link,
}
