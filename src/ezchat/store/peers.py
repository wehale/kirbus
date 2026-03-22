"""Persist known peers to ~/.ezchat/peers.toml.

Format:
    [peers.alice]
    ed25519_pub = "<base64 raw bytes>"
    last_seen   = "2026-03-19T14:23:01"
    ip_hint     = "192.168.1.5"
"""
from __future__ import annotations

import base64
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ezchat.home import get_home

def _peers_path() -> Path:
    return get_home() / "peers.toml"


@dataclass
class PeerRecord:
    handle:         str
    ed25519_pub_b64: str  # base64 raw Ed25519 public key bytes
    last_seen:      str = ""
    ip_hint:        str = ""


def _pub_to_b64(pub: Ed25519PublicKey) -> str:
    raw = pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def _b64_to_pub(s: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(s))


def load_peers() -> dict[str, PeerRecord]:
    """Load peers.toml; returns {} if not found or unparseable."""
    if not _peers_path().exists():
        return {}
    try:
        data = tomllib.loads(_peers_path().read_text(encoding="utf-8"))
    except Exception:
        return {}
    result = {}
    for handle, attrs in data.get("peers", {}).items():
        result[handle] = PeerRecord(
            handle          = handle,
            ed25519_pub_b64 = attrs.get("ed25519_pub", ""),
            last_seen       = attrs.get("last_seen", ""),
            ip_hint         = attrs.get("ip_hint", ""),
        )
    return result


def _write_peers(peers: dict[str, PeerRecord]) -> None:
    _peers_path().parent.mkdir(parents=True, exist_ok=True)
    lines = ["# ezchat known peers\n\n"]
    for handle in sorted(peers):
        rec = peers[handle]
        lines.append(f"[peers.{handle}]\n")
        if rec.ed25519_pub_b64:
            lines.append(f'ed25519_pub = "{rec.ed25519_pub_b64}"\n')
        if rec.last_seen:
            lines.append(f'last_seen = "{rec.last_seen}"\n')
        if rec.ip_hint:
            lines.append(f'ip_hint = "{rec.ip_hint}"\n')
        lines.append("\n")
    _peers_path().write_text("".join(lines), encoding="utf-8")


def upsert_peer(
    handle:   str,
    pub:      Ed25519PublicKey,
    ip_hint:  str = "",
) -> None:
    """Add or update a peer record and save immediately."""
    peers = load_peers()
    peers[handle] = PeerRecord(
        handle          = handle,
        ed25519_pub_b64 = _pub_to_b64(pub),
        last_seen       = datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        ip_hint         = ip_hint,
    )
    _write_peers(peers)


def get_pubkeys(
    peers: dict[str, PeerRecord] | None = None,
) -> dict[str, Ed25519PublicKey]:
    """Return {handle: Ed25519PublicKey} for all peers with a stored pubkey."""
    if peers is None:
        peers = load_peers()
    result: dict[str, Ed25519PublicKey] = {}
    for handle, rec in peers.items():
        if rec.ed25519_pub_b64:
            try:
                result[handle] = _b64_to_pub(rec.ed25519_pub_b64)
            except Exception:
                pass
    return result
