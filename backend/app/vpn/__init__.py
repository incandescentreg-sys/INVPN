"""VPN control plane: SSH transport, Xray config manipulation, link building."""

from app.vpn.config import ClientSpec, XrayConfigError, dump_config, load_config
from app.vpn.link import LinkParams, build_vless_link
from app.vpn.manager import HealthReport, ServerEndpoint, SyncReport, XrayManager, build_manager
from app.vpn.reality import RealityKeypair, generate_keypair, generate_short_id

__all__ = [
    "ClientSpec",
    "HealthReport",
    "LinkParams",
    "RealityKeypair",
    "ServerEndpoint",
    "SyncReport",
    "XrayConfigError",
    "XrayManager",
    "build_manager",
    "build_vless_link",
    "dump_config",
    "generate_keypair",
    "generate_short_id",
    "load_config",
]
