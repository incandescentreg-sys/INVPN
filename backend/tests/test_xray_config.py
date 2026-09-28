"""Xray config generation and REALITY helpers (pure logic, no I/O)."""

from __future__ import annotations

import base64
import json
import uuid

import pytest

from app.vpn.config import (
    ClientSpec,
    XrayConfigError,
    apply_clients,
    build_inbound,
    dump_config,
    ensure_inbound,
    get_clients,
    list_client_emails,
    load_config,
    public_view,
    set_reality,
)
from app.vpn.link import LinkParams, build_vless_link
from app.vpn.reality import (
    generate_keypair,
    generate_short_id,
    is_valid_key,
    is_valid_short_id,
    parse_xray_x25519_output,
    public_key_from_private,
    split_target,
)

PRIVATE = generate_keypair().private_key
PUBLIC = public_key_from_private(PRIVATE)
SHORT_ID = generate_short_id()


@pytest.fixture
def config() -> dict:
    return build_inbound(
        tag="inbound-vless",
        port=443,
        private_key=PRIVATE,
        target="www.microsoft.com:443",
        server_names=["www.microsoft.com"],
        short_ids=[SHORT_ID],
    )


def _as_config(inbound: dict) -> dict:
    return {"log": {"loglevel": "warning"}, "inbounds": [inbound], "outbounds": []}


# --------------------------------------------------------------------------- #
# REALITY primitives
# --------------------------------------------------------------------------- #
def test_generated_keys_are_xray_compatible() -> None:
    pair = generate_keypair()
    assert is_valid_key(pair.private_key)
    assert is_valid_key(pair.public_key)
    assert len(pair.private_key) == 43  # base64url of 32 bytes, no padding
    assert "=" not in pair.public_key
    # the public key is derivable from the private one
    assert public_key_from_private(pair.private_key) == pair.public_key


def test_keys_are_unique_per_call() -> None:
    assert generate_keypair().private_key != generate_keypair().private_key


def test_short_id_format() -> None:
    sid = generate_short_id()
    assert is_valid_short_id(sid)
    assert len(sid) == 16  # 8 bytes
    assert not is_valid_short_id("abc")  # odd length
    assert not is_valid_short_id("zz")
    assert not is_valid_short_id("")


def test_split_target() -> None:
    assert split_target("www.microsoft.com:443") == ("www.microsoft.com", 443)
    assert split_target("example.org") == ("example.org", 443)


def test_parse_xray_output_variants() -> None:
    """Xray renamed `Public key:` to `Password:` — both must parse."""
    old = f"Private key: {PRIVATE}\nPublic key: {PUBLIC}\n"
    new = f"PrivateKey: {PRIVATE}\nPassword: {PUBLIC}\n"
    for raw in (old, new):
        pair = parse_xray_x25519_output(raw)
        assert pair.private_key == PRIVATE
        assert pair.public_key == PUBLIC


def test_parse_xray_output_without_public_key() -> None:
    pair = parse_xray_x25519_output(f"Private key: {PRIVATE}")
    assert pair.public_key == PUBLIC


def test_parse_xray_output_garbage() -> None:
    with pytest.raises(ValueError):
        parse_xray_x25519_output("something else entirely")


# --------------------------------------------------------------------------- #
# Config manipulation
# --------------------------------------------------------------------------- #
def test_build_inbound_shape(config: dict) -> None:
    assert config["protocol"] == "vless"
    assert config["settings"]["decryption"] == "none"
    stream = config["streamSettings"]
    assert stream["security"] == "reality"
    reality = stream["realitySettings"]
    assert reality["privateKey"] == PRIVATE
    assert reality["serverNames"] == ["www.microsoft.com"]
    assert reality["shortIds"] == [SHORT_ID]
    assert reality["show"] is False
    assert config["settings"]["clients"] == []


def test_load_config_rejects_garbage() -> None:
    with pytest.raises(XrayConfigError):
        load_config("{not json")
    with pytest.raises(XrayConfigError):
        load_config("[1,2,3]")


def test_load_config_adds_defaults() -> None:
    cfg = load_config("{}")
    assert "inbounds" in cfg and "outbounds" in cfg and "log" in cfg


def test_ensure_inbound_is_idempotent(config: dict) -> None:
    cfg = _as_config(config)
    _, changed = ensure_inbound(
        cfg, tag="inbound-vless", port=443, listen="0.0.0.0",
        private_key=PRIVATE, target="www.microsoft.com:443", server_names=["www.microsoft.com"],
    )
    assert changed is False
    assert len(cfg["inbounds"]) == 1


def test_ensure_inbound_creates_missing(config: dict) -> None:
    cfg = {"inbounds": []}
    _, changed = ensure_inbound(
        cfg, tag="inbound-vless", port=8443, listen="0.0.0.0",
        private_key=PRIVATE, target="www.microsoft.com:443", server_names=["www.microsoft.com"],
    )
    assert changed is True
    assert cfg["inbounds"][0]["port"] == 8443
    assert cfg["inbounds"][0]["streamSettings"]["realitySettings"]["shortIds"]


def test_apply_clients_adds_clients(config: dict) -> None:
    cfg = _as_config(config)
    spec = ClientSpec(uuid=str(uuid.uuid4()), email="u1-abc-user")
    _, report = apply_clients(cfg, "inbound-vless", [spec])
    assert report["added"] == ["u1-abc-user"]
    assert report["removed"] == []
    assert get_clients(cfg, "inbound-vless")[0]["flow"] == "xtls-rprx-vision"


def test_apply_clients_is_idempotent(config: dict) -> None:
    cfg = _as_config(config)
    spec = ClientSpec(uuid=str(uuid.uuid4()), email="u1-abc")
    apply_clients(cfg, "inbound-vless", [spec])
    _, second = apply_clients(cfg, "inbound-vless", [spec])
    assert second == {"added": [], "updated": [], "removed": []}
    assert len(get_clients(cfg, "inbound-vless")) == 1


def test_apply_clients_rotates_uuid_without_touching_email(config: dict) -> None:
    """Changing a UUID must update in place, not duplicate the entry."""
    cfg = _as_config(config)
    email = "u1-abc"
    apply_clients(cfg, "inbound-vless", [ClientSpec(uuid=str(uuid.uuid4()), email=email)])
    rotated = str(uuid.uuid4())
    _, report = apply_clients(cfg, "inbound-vless", [ClientSpec(uuid=rotated, email=email)])
    assert report["updated"] == [email]
    assert report["added"] == []
    clients = get_clients(cfg, "inbound-vless")
    assert len(clients) == 1 and clients[0]["id"] == rotated


def test_apply_clients_removes_absent(config: dict) -> None:
    cfg = _as_config(config)
    keep, drop = "u1-keep", "u1-drop"
    apply_clients(
        cfg,
        "inbound-vless",
        [ClientSpec(uuid=str(uuid.uuid4()), email=keep), ClientSpec(uuid=str(uuid.uuid4()), email=drop)],
    )
    _, report = apply_clients(cfg, "inbound-vless", [ClientSpec(uuid="x", email=keep)])
    assert report["removed"] == [drop]
    assert list_client_emails(cfg, "inbound-vless") == [keep]


def test_apply_clients_preserves_order_and_unknown_keys(config: dict) -> None:
    cfg = _as_config(config)
    cfg["inbounds"][0]["streamSettings"]["realitySettings"]["extraCustom"] = "keep-me"
    cfg["log"]["access"] = "/var/log/xray.log"
    specs = [ClientSpec(uuid=str(uuid.uuid4()), email=f"u{i}") for i in range(3)]
    apply_clients(cfg, "inbound-vless", specs)
    cfg2, _ = apply_clients(cfg, "inbound-vless", specs)
    assert list_client_emails(cfg2, "inbound-vless") == ["u0", "u1", "u2"]
    assert cfg2["inbounds"][0]["streamSettings"]["realitySettings"]["extraCustom"] == "keep-me"
    assert cfg2["log"]["access"] == "/var/log/xray.log"


def test_apply_clients_drops_duplicate_emails(config: dict) -> None:
    cfg = _as_config(config)
    email = "dup"
    apply_clients(cfg, "inbound-vless", [ClientSpec(uuid=str(uuid.uuid4()), email=email)])
    cfg["inbounds"][0]["settings"]["clients"].append(
        {"id": str(uuid.uuid4()), "email": email, "flow": "xtls-rprx-vision"}
    )
    cfg, _ = apply_clients(cfg, "inbound-vless", [ClientSpec(uuid=str(uuid.uuid4()), email=email)])
    assert list_client_emails(cfg, "inbound-vless") == [email]


def test_apply_clients_refuses_foreign_protocol(config: dict) -> None:
    cfg = _as_config(config)
    cfg["inbounds"][0]["protocol"] = "vmess"
    with pytest.raises(XrayConfigError, match="vless"):
        apply_clients(cfg, "inbound-vless", [])


def test_apply_clients_refuses_non_reality(config: dict) -> None:
    cfg = _as_config(config)
    cfg["inbounds"][0]["streamSettings"]["security"] = "tls"
    with pytest.raises(XrayConfigError, match="REALITY"):
        apply_clients(cfg, "inbound-vless", [])


def test_set_reality_reports_change(config: dict) -> None:
    cfg = _as_config(config)
    _, changed = set_reality(
        cfg,
        "inbound-vless",
        private_key=PRIVATE,
        target="www.microsoft.com:443",
        server_names=["www.microsoft.com"],
        short_ids=[SHORT_ID],
    )
    assert changed is False

    new_pair = generate_keypair()
    _, changed = set_reality(
        cfg,
        "inbound-vless",
        private_key=new_pair.private_key,
        target="www.microsoft.com:443",
        server_names=["www.microsoft.com"],
        short_ids=[SHORT_ID],
    )
    assert changed is True
    assert cfg["inbounds"][0]["streamSettings"]["realitySettings"]["privateKey"] == new_pair.private_key


def test_public_view_strips_secrets(config: dict) -> None:
    cfg = _as_config(config)
    uid = str(uuid.uuid4())
    apply_clients(cfg, "inbound-vless", [ClientSpec(uuid=uid, email="u1")])
    safe = public_view(cfg, "inbound-vless")
    raw = json.dumps(safe)
    assert PRIVATE not in raw
    assert uid not in raw
    # the original is untouched
    assert uid in json.dumps(cfg)


def test_dump_is_valid_json_and_stable(config: dict) -> None:
    cfg = _as_config(config)
    text = dump_config(cfg)
    assert json.loads(text) == cfg
    assert text.endswith("\n")


# --------------------------------------------------------------------------- #
# Client links
# --------------------------------------------------------------------------- #
def test_build_vless_link() -> None:
    link = build_vless_link(
        LinkParams(
            client_uuid=str(uuid.uuid4()),
            host="vpn.example.com",
            port=443,
            public_key=PUBLIC,
            server_name="www.microsoft.com",
            short_id=SHORT_ID,
            label="VPN · Тест",
        )
    )
    assert link.startswith("vless://")
    assert "vpn.example.com:443" in link
    for fragment in ("type=tcp", "security=reality", f"pbk={PUBLIC}", "flow=xtls-rprx-vision",
                     f"sid={SHORT_ID}", "sni=www.microsoft.com", "fp=chrome", "spx=%2F"):
        assert fragment in link
    assert link.endswith("#VPN%20%C2%B7%20%D0%A2%D0%B5%D1%81%D1%82")


def test_link_rejects_bad_inputs() -> None:
    base = {
        "client_uuid": str(uuid.uuid4()),
        "host": "h",
        "port": 443,
        "public_key": PUBLIC,
        "server_name": "s",
        "short_id": SHORT_ID,
    }
    with pytest.raises(ValueError, match="UUID"):
        build_vless_link(LinkParams(**{**base, "client_uuid": "not-a-uuid"}))
    with pytest.raises(ValueError, match="public key"):
        build_vless_link(LinkParams(**{**base, "public_key": "nope"}))
    with pytest.raises(ValueError, match="shortId"):
        build_vless_link(LinkParams(**{**base, "short_id": "abc"}))
    with pytest.raises(ValueError, match="SNI"):
        build_vless_link(LinkParams(**{**base, "server_name": ""}))


def test_base64_link_is_reversible() -> None:
    from app.vpn.link import base64_link

    link = build_vless_link(
        LinkParams(
            client_uuid=str(uuid.uuid4()), host="h", port=443, public_key=PUBLIC,
            server_name="s", short_id=SHORT_ID,
        )
    )
    assert base64.b64decode(base64_link(link)).decode() == link
