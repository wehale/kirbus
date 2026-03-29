"""Rendezvous HTTP API.

Endpoints
---------
POST /register
    Body: { "handle": "alice", "pubkey": "<base64>", "endpoint": "1.2.3.4:9000", "ts": "...", "sig": "<base64>" }
    Registers a peer with a 60-second TTL.  Signature verified against pubkey.

GET /lookup/{handle}
    Returns: { "endpoint": "1.2.3.4:9000", "pubkey": "<base64>" }
    404 if not found or expired.

GET /peers
    Returns: { "peers": [ { "handle": "alice", "endpoint": "...", "pubkey": "..." }, ... ] }
    All currently registered peers (excluding the caller's handle if provided via ?me=alice).

POST /keepalive
    Body: { "handle": "alice", "ts": "...", "sig": "<base64>" }
    Resets the TTL for an existing registration.

GET /myip
    Returns: { "ip": "1.2.3.4" }
    Useful for clients to discover their own public IP.
"""
from __future__ import annotations

import base64
import logging
import time
from typing import Any

from aiohttp import web
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_log = logging.getLogger(__name__)

# handle → {pubkey_b64, endpoint, ts, sig, expires}
_registry: dict[str, dict[str, Any]] = {}

# Agent menus: handle → menu JSON (title, entries)
_agent_menus: dict[str, dict] = {}


def _b64d(s: str) -> bytes:
    return base64.b64decode(s)


def _verify_sig(pubkey_b64: str, sig_b64: str, *parts: str) -> bool:
    """Verify Ed25519 sig over ':'.join(parts)."""
    try:
        pub = Ed25519PublicKey.from_public_bytes(_b64d(pubkey_b64))
        pub.verify(_b64d(sig_b64), ":".join(parts).encode())
        return True
    except Exception:
        return False


def _purge_expired() -> None:
    now = time.monotonic()
    expired = [h for h, v in _registry.items() if v["expires"] <= now]
    for h in expired:
        del _registry[h]
        _log.debug("expired: %s", h)


async def handle_register(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        handle   = body["handle"]
        pubkey   = body["pubkey"]
        endpoint = body["endpoint"]
        ts       = body["ts"]
        sig      = body["sig"]
    except (KeyError, ValueError):
        return web.json_response({"error": "bad request"}, status=400)

    # Verify the signature is valid for the submitted pubkey
    if not _verify_sig(pubkey, sig, handle, pubkey, endpoint, ts):
        return web.json_response({"error": "invalid signature"}, status=403)

    # --- access control ---
    auth_mode = request.app.get("auth_mode", "open")
    allowlist = request.app.get("allowlist")

    if auth_mode != "open" and allowlist:
        if allowlist.is_allowed(pubkey):
            pass  # known key, access granted
        elif auth_mode == "password":
            password = body.get("password", "")
            if not password:
                return web.json_response(
                    {"error": "password_required", "reason": "password_required"},
                    status=403,
                )
            if password != request.app.get("auth_password", ""):
                return web.json_response({"error": "invalid password"}, status=403)
            # Password correct — add to allowlist for future connections
            allowlist.add(handle, pubkey, via="password")
            _log.info("added %s to allowlist via password", handle)
        elif auth_mode == "allowlist":
            return web.json_response({"error": "not in allowlist"}, status=403)

    _purge_expired()

    # If this handle is already claimed by a different key, reject the attempt.
    # The legitimate owner can always re-register because their sig verifies
    # against their own (matching) pubkey above.
    existing = _registry.get(handle)
    if existing and existing["pubkey"] != pubkey:
        _log.warning("handle conflict: %s tried to re-register as %r", pubkey[:12], handle)
        return web.json_response({"error": "handle already claimed"}, status=409)

    # Track su status
    su = body.get("su", False)
    is_su = False
    if su:
        peer = request.transport.get_extra_info("peername")
        if peer and peer[0] in ("127.0.0.1", "::1"):
            is_su = True
            _log.info("su access granted to %s", handle)

    ttl = request.app["ttl"]
    _registry[handle] = {
        "pubkey":   pubkey,
        "endpoint": endpoint,
        "ts":       ts,
        "sig":      sig,
        "expires":  time.monotonic() + ttl,
        "su":       is_su,
    }
    _log.info("registered %s → %s", handle, endpoint)
    resp = {"ok": True, "ttl": ttl, "su": is_su}
    secret = request.app.get("secret_message", "")
    if secret:
        resp["secret_message"] = secret
    return web.json_response(resp)


async def handle_lookup(request: web.Request) -> web.Response:
    _purge_expired()
    handle = request.match_info["handle"]
    entry  = _registry.get(handle)
    if not entry:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response({"endpoint": entry["endpoint"], "pubkey": entry["pubkey"]})


async def handle_keepalive(request: web.Request) -> web.Response:
    try:
        body   = await request.json()
        handle = body["handle"]
        ts     = body["ts"]
        sig    = body["sig"]
    except (KeyError, ValueError):
        return web.json_response({"error": "bad request"}, status=400)

    entry = _registry.get(handle)
    if not entry:
        return web.json_response({"error": "not registered"}, status=404)

    if not _verify_sig(entry["pubkey"], sig, handle, ts):
        return web.json_response({"error": "invalid signature"}, status=403)

    ttl = request.app["ttl"]
    entry["expires"] = time.monotonic() + ttl
    return web.json_response({"ok": True, "ttl": ttl})


async def handle_peers(request: web.Request) -> web.Response:
    _purge_expired()
    me    = request.rel_url.query.get("me", "")
    peers = [
        {"handle": h, "endpoint": v["endpoint"], "pubkey": v["pubkey"]}
        for h, v in _registry.items()
        if h != me
    ]
    return web.json_response({"peers": peers})


async def handle_myip(request: web.Request) -> web.Response:
    peer = request.transport.get_extra_info("peername")
    ip   = peer[0] if peer else "unknown"
    return web.json_response({"ip": ip})


def online_count() -> int:
    """Return the number of currently registered (non-expired) peers."""
    _purge_expired()
    return len(_registry)


async def handle_agent_menu(request: web.Request) -> web.Response:
    """Register or update an agent's menu."""
    try:
        body = await request.json()
        handle = body["handle"]
        menu = body["menu"]  # {title, entries: [{key, label, type}]}
    except (KeyError, ValueError):
        return web.json_response({"error": "bad request"}, status=400)
    _agent_menus[handle] = menu
    _log.info("agent menu registered: %s (%d entries)", handle, len(menu.get("entries", [])))
    return web.json_response({"ok": True})


async def handle_info(request: web.Request) -> web.Response:
    """Return server metadata (relay port, welcome message, agent menus)."""
    data = {"relay_port": request.app["relay_port"]}
    welcome = request.app.get("welcome", "")
    if welcome:
        data["welcome"] = welcome
    if _agent_menus:
        data["agent_menus"] = {h: m for h, m in _agent_menus.items()}
    return web.json_response(data)


def make_app(
    ttl: int = 60,
    auth_mode: str = "open",
    auth_password: str = "",
    allowlist=None,
    relay_port: int = 9001,
    welcome: str = "",
    secret_message: str = "",
) -> web.Application:
    app = web.Application()
    app["ttl"] = ttl
    app["auth_mode"] = auth_mode
    app["auth_password"] = auth_password
    app["allowlist"] = allowlist
    app["relay_port"] = relay_port
    app["welcome"] = welcome
    app["secret_message"] = secret_message
    app.router.add_post("/register",         handle_register)
    app.router.add_get( "/lookup/{handle}",  handle_lookup)
    app.router.add_get( "/peers",            handle_peers)
    app.router.add_post("/keepalive",        handle_keepalive)
    app.router.add_get( "/myip",             handle_myip)
    app.router.add_get( "/info",             handle_info)
    app.router.add_post("/agent-menu",       handle_agent_menu)
    return app
