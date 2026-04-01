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

# Agent message handlers: agent_handle → callable(sender, text) → list of {to, text}
_agent_handlers: dict[str, Any] = {}

# Notification queue for push events (device events, alerts, etc.)
# List of dicts: {"text": str, "ts": float}
import asyncio as _asyncio
_notification_queue: list[dict] = []
_notification_waiters: list[_asyncio.Event] = []

# Metrics
_metrics = {
    "total_connections": 0,
    "unique_handles": set(),
    "unique_ips": set(),
    "failed_auth": 0,
}
_connection_log: list[dict] = []  # kept in memory, also written to file


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
        if h in _agent_menus:
            del _agent_menus[h]
            _log.debug("expired agent menu: %s", h)
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
        _metrics["failed_auth"] += 1
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
                _metrics["failed_auth"] += 1
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

    # Track metrics
    peer = request.transport.get_extra_info("peername")
    ip = peer[0] if peer else "unknown"
    _metrics["total_connections"] += 1
    _metrics["unique_handles"].add(handle)
    _metrics["unique_ips"].add(ip)
    import datetime as _dt
    entry = {
        "time": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "handle": handle,
        "ip": ip,
        "endpoint": endpoint,
    }
    _connection_log.append(entry)
    # Append to log file
    log_path = request.app.get("metrics_log")
    if log_path:
        try:
            with open(log_path, "a") as f:
                f.write(f"{entry['time']}  {handle:20s}  {ip:15s}  {endpoint}\n")
        except Exception:
            pass

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


async def handle_stats(request: web.Request) -> web.Response:
    """Return server metrics."""
    _purge_expired()
    resp = web.json_response({
        "total_connections": _metrics["total_connections"],
        "unique_handles": len(_metrics["unique_handles"]),
        "unique_ips": len(_metrics["unique_ips"]),
        "failed_auth": _metrics["failed_auth"],
        "currently_online": len(_registry),
        "recent": _connection_log[-50:],  # last 50 connections
    })
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


def register_agent_handler(handle: str, handler) -> None:
    """Register an in-process agent message handler.

    handler(sender: str, text: str) -> list[dict] where each dict is {"to": str, "text": str}
    """
    _agent_handlers[handle] = handler
    _log.info("agent handler registered: %s", handle)


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


async def handle_agent_send(request: web.Request) -> web.Response:
    """Client sends a message to an agent. Server processes it and returns the response."""
    try:
        body = await request.json()
        agent_handle = body["to"]
        sender = body["from"]
        text = body["text"]
    except (KeyError, ValueError):
        return web.json_response({"error": "bad request"}, status=400)

    handler = _agent_handlers.get(agent_handle)
    if not handler:
        return web.json_response({"error": "agent not found"}, status=404)

    # Process the message synchronously and return the response
    try:
        responses = handler(sender, text)
        return web.json_response({"ok": True, "replies": responses})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_device_event(request: web.Request) -> web.Response:
    """Accept events from external devices (e.g. E84 baby-cry firmware).

    POST /device/event
    Body: {"event": "baby_cry", "state": true, "confidence": 0.99, ...}
    """
    try:
        body = await request.json()
    except ValueError:
        return web.json_response({"error": "invalid JSON"}, status=400)

    event = body.get("event")
    if not event:
        return web.json_response({"error": "missing 'event' field"}, status=400)

    handler = request.app.get("device_event_handler")
    if not handler:
        _log.warning("device event received but no handler registered")
        return web.json_response({"error": "no handler"}, status=503)

    try:
        result = handler(body)
        _log.info("device event: %s state=%s → %s", event, body.get("state"), result)
        # Push notification to waiting clients
        _push_notification(body, result)
        return web.json_response({"ok": True, "result": result})
    except Exception as e:
        _log.error("device event handler error: %s", e)
        return web.json_response({"error": str(e)}, status=500)


def _push_notification(body: dict, result: str) -> None:
    """Add a notification and wake all long-poll waiters."""
    entry = {"body": body, "result": result, "ts": time.time()}
    _notification_queue.append(entry)
    # Keep last 100 notifications
    if len(_notification_queue) > 100:
        _notification_queue[:] = _notification_queue[-100:]
    # Wake all waiting clients
    for evt in _notification_waiters:
        evt.set()


async def handle_notifications(request: web.Request) -> web.Response:
    """Long-poll for device event notifications.

    GET /agent/notifications?since=<timestamp>
    Returns queued notifications since the given timestamp.
    Blocks up to 30s if none are available yet.
    """
    since = float(request.query.get("since", "0"))

    # Check for already-queued notifications
    pending = [n for n in _notification_queue if n["ts"] > since]
    if pending:
        return web.json_response({"notifications": pending})

    # Long-poll: wait up to 30s for a new notification
    evt = _asyncio.Event()
    _notification_waiters.append(evt)
    try:
        try:
            await _asyncio.wait_for(evt.wait(), timeout=30.0)
        except _asyncio.TimeoutError:
            pass
        pending = [n for n in _notification_queue if n["ts"] > since]
        return web.json_response({"notifications": pending})
    finally:
        _notification_waiters.remove(evt)


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
    metrics_log: str = "",
) -> web.Application:
    app = web.Application()
    app["ttl"] = ttl
    app["auth_mode"] = auth_mode
    app["auth_password"] = auth_password
    app["allowlist"] = allowlist
    app["relay_port"] = relay_port
    app["welcome"] = welcome
    app["secret_message"] = secret_message
    app["metrics_log"] = metrics_log
    app.router.add_post("/register",         handle_register)
    app.router.add_get( "/lookup/{handle}",  handle_lookup)
    app.router.add_get( "/peers",            handle_peers)
    app.router.add_post("/keepalive",        handle_keepalive)
    app.router.add_get( "/myip",             handle_myip)
    app.router.add_get( "/info",             handle_info)
    app.router.add_get( "/stats",            handle_stats)
    app.router.add_post("/agent-menu",       handle_agent_menu)
    app.router.add_post("/agent/send",       handle_agent_send)
    app.router.add_post("/device/event",      handle_device_event)
    app.router.add_get( "/agent/notifications", handle_notifications)
    return app
