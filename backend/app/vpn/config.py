"""Xray configuration manipulation — pure functions, no I/O.

Everything here is side-effect free so it can be unit tested without a VPS.
The manager reads the live config, merges the change and writes it back with an
atomic rename; unknown keys are always preserved so upgrades of Xray (or manual
edits by the operator) are never silently dropped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.vpn.reality import generate_short_id, is_valid_key, is_valid_short_id, split_target

VLESS_FLOW = "xtls-rprx-vision"


class XrayConfigError(ValueError):
    """Malformed config or a request we refuse to apply."""


@dataclass(frozen=True, slots=True)
class ClientSpec:
    """Desired state of one Xray client."""

    uuid: str
    email: str
    flow: str = VLESS_FLOW


def load_config(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        config = dict(raw)
    else:
        try:
            config = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise XrayConfigError(f"Конфигурация Xray не является валидным JSON: {exc}") from exc
    if not isinstance(config, dict):
        raise XrayConfigError("Корень конфигурации Xray должен быть объектом")
    config.setdefault("log", {"loglevel": "warning"})
    config.setdefault("inbounds", [])
    config.setdefault("outbounds", [{"protocol": "freedom", "tag": "direct"}])
    return config


def dump_config(config: dict[str, Any]) -> str:
    return json.dumps(config, indent=2, ensure_ascii=False) + "\n"


def find_inbound(config: dict[str, Any], tag: str) -> dict[str, Any] | None:
    for inbound in config.get("inbounds", []):
        if isinstance(inbound, dict) and inbound.get("tag") == tag:
            return inbound
    return None


def require_inbound(config: dict[str, Any], tag: str) -> dict[str, Any]:
    inbound = find_inbound(config, tag)
    if inbound is None:
        raise XrayConfigError(f"Inbound {tag!r} не найден в конфигурации Xray")
    return inbound


def build_inbound(
    *,
    tag: str,
    port: int,
    listen: str = "0.0.0.0",
    private_key: str,
    target: str,
    server_names: list[str],
    short_ids: list[str] | None = None,
) -> dict[str, Any]:
    """A minimal, correct VLESS + REALITY inbound."""
    if not is_valid_key(private_key):
        raise XrayConfigError("Некорректный приватный ключ REALITY")
    names = [n for n in server_names if n] or ["www.microsoft.com"]
    ids = [sid for sid in (short_ids or []) if is_valid_short_id(sid)] or [generate_short_id()]
    dest_host, dest_port = split_target(target)

    return {
        "tag": tag,
        "listen": listen,
        "port": port,
        "protocol": "vless",
        "settings": {"clients": [], "decryption": "none"},
        "streamSettings": {
            "network": "tcp",
            "security": "reality",
            "realitySettings": {
                "show": False,
                "target": target or f"{dest_host}:{dest_port}",
                "xver": 0,
                "serverNames": names,
                "privateKey": private_key,
                "shortIds": ids,
                "spiderX": "/",
            },
        },
        "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]},
    }


def ensure_inbound(
    config: dict[str, Any],
    *,
    tag: str,
    port: int,
    listen: str,
    private_key: str,
    target: str,
    server_names: list[str],
    short_ids: list[str] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Create the VLESS inbound if it is missing. Returns (config, changed)."""
    existing = find_inbound(config, tag)
    if existing is not None:
        return config, False
    inbound = build_inbound(
        tag=tag,
        port=port,
        listen=listen,
        private_key=private_key,
        target=target,
        server_names=server_names,
        short_ids=short_ids,
    )
    config.setdefault("inbounds", []).append(inbound)
    return config, True


def get_clients(config: dict[str, Any], tag: str) -> list[dict[str, Any]]:
    inbound = find_inbound(config, tag)
    if not inbound:
        return []
    clients = inbound.get("settings", {}).get("clients", [])
    return [c for c in clients if isinstance(c, dict)]


def list_client_ids(config: dict[str, Any], tag: str) -> list[str]:
    return [str(c.get("id", "")) for c in get_clients(config, tag) if c.get("id")]


def list_client_emails(config: dict[str, Any], tag: str) -> list[str]:
    return [str(c.get("email", "")) for c in get_clients(config, tag) if c.get("email")]


def _client_entry(spec: ClientSpec) -> dict[str, Any]:
    return {"id": spec.uuid, "flow": spec.flow, "email": spec.email}


def apply_clients(
    config: dict[str, Any], tag: str, desired: list[ClientSpec]
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Reconcile the inbound's client list with `desired`.

    Returns (config, report) where report lists added/updated/removed emails.
    Additive, idempotent and order-preserving: an Xray restart is not required
    for anything except removals, and we only reload once per call anyway.
    """
    inbound = require_inbound(config, tag)
    if inbound.get("protocol") != "vless":
        raise XrayConfigError(f"Inbound {tag!r} имеет protocol={inbound.get('protocol')!r}, ожидался 'vless'")

    stream = inbound.setdefault("streamSettings", {})
    if stream.get("security") != "reality":
        raise XrayConfigError(
            f"Inbound {tag!r} использует security={stream.get('security')!r}; сервис управляет только REALITY"
        )

    current: list[dict[str, Any]] = list(inbound.get("settings", {}).get("clients", []))
    by_email: dict[str, dict[str, Any]] = {
        str(c["email"]): c for c in current if c.get("email")
    }
    wanted: dict[str, ClientSpec] = {spec.email: spec for spec in desired}

    added: list[str] = []
    updated: list[str] = []
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    # keep original order for existing entries, append the new ones at the end
    for entry in current:
        email = str(entry.get("email", ""))
        if email not in wanted:
            continue
        if email in seen:  # duplicate email in the source config — drop it
            continue
        seen.add(email)
        spec = wanted[email]
        desired_entry = _client_entry(spec)
        if {k: entry.get(k) for k in desired_entry} != desired_entry:
            entry = desired_entry
            updated.append(email)
        merged.append(entry)

    for email, spec in wanted.items():
        if email in seen:
            continue
        merged.append(_client_entry(spec))
        added.append(email)

    removed = [email for email in by_email if email not in wanted]

    if added or updated or removed or len(merged) != len(current):
        inbound.setdefault("settings", {})["clients"] = merged

    return config, {"added": added, "updated": updated, "removed": removed}


def set_reality(
    config: dict[str, Any],
    tag: str,
    *,
    private_key: str,
    target: str,
    server_names: list[str],
    short_ids: list[str] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Write REALITY parameters into an existing inbound."""
    if not is_valid_key(private_key):
        raise XrayConfigError("Некорректный приватный ключ REALITY")
    inbound = require_inbound(config, tag)
    stream = inbound.setdefault("streamSettings", {})
    reality = stream.setdefault("realitySettings", {})
    new_values = {
        "show": False,
        "target": target,
        "xver": 0,
        "serverNames": [n for n in server_names if n] or ["www.microsoft.com"],
        "privateKey": private_key,
        "shortIds": [sid for sid in (short_ids or []) if is_valid_short_id(sid)] or [generate_short_id()],
        "spiderX": "/",
    }
    changed = any(reality.get(k) != v for k, v in new_values.items())
    if changed:
        stream["security"] = "reality"
        stream["network"] = stream.get("network") or "tcp"
        reality.update(new_values)
    return config, changed


def public_view(config: dict[str, Any], tag: str) -> dict[str, Any]:
    """Config with private keys stripped — safe to return over the API."""
    safe: dict[str, Any] = json.loads(json.dumps(config))
    for inbound in safe.get("inbounds", []):
        reality = inbound.get("streamSettings", {}).get("realitySettings")
        if isinstance(reality, dict):
            reality.pop("privateKey", None)
        for client in inbound.get("settings", {}).get("clients", []) or []:
            if isinstance(client, dict):
                client.pop("id", None)
    return safe
