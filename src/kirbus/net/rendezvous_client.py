"""Rendezvous client — register, lookup, and keepalive.

All methods are async and designed to run inside the net_thread event loop.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

_log = logging.getLogger(__name__)

_KEEPALIVE_INTERVAL = 30   # seconds


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _post(url: str, payload: dict) -> dict:
    """Synchronous JSON POST (runs in executor)."""
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _get(url: str) -> dict:
    """Synchronous JSON GET (runs in executor)."""
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode())


class RendezvousClient:
    def __init__(self, server_url: str, identity) -> None:
        """
        server_url  — e.g. "http://1.2.3.4:8000"
        identity    — kirbus.crypto.keys.Identity
        """
        self.base    = server_url.rstrip("/")
        self.identity = identity
        self._keepalive_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def register(
        self,
        endpoint: str,
        su: bool = False,
        password: str = "",
    ) -> dict:
        """Register this identity's endpoint with the rendezvous server.

        Returns the server response dict (e.g. {"ok": True, "ttl": 60, "su": False})
        or {"ok": False, "error": "..."} on failure.
        """
        ts     = _now_ts()
        pubkey = _b64(self.identity.pub_bytes)
        handle = self.identity.handle
        sig    = _b64(self.identity.sign(
            ":".join([handle, pubkey, endpoint, ts]).encode()
        ))
        payload = {
            "handle":   handle,
            "pubkey":   pubkey,
            "endpoint": endpoint,
            "ts":       ts,
            "sig":      sig,
        }
        if su:
            payload["su"] = True
        if password:
            payload["password"] = password
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None, _post, f"{self.base}/register", payload
            )
            _log.debug("registered %s → %s: %s", handle, endpoint, result)
            return result
        except Exception as exc:
            _log.warning("register failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    async def lookup(self, handle: str) -> tuple[str, str] | None:
        """Look up a peer's endpoint.  Returns (endpoint, pubkey_b64) or None."""
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None, _get, f"{self.base}/lookup/{handle}"
            )
            return result["endpoint"], result["pubkey"]
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            _log.warning("lookup %s failed: %s", handle, exc)
            return None
        except Exception as exc:
            _log.warning("lookup %s failed: %s", handle, exc)
            return None

    async def peers(self) -> list[dict]:
        """Return all currently online peers (excluding self).

        Each entry: {"handle": str, "endpoint": str, "pubkey": str}
        """
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None, _get,
                f"{self.base}/peers?me={self.identity.handle}"
            )
            return result.get("peers", [])
        except Exception as exc:
            _log.warning("peers fetch failed: %s", exc)
            return []

    async def my_public_ip(self) -> str | None:
        """Ask the server what IP it sees us coming from."""
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, _get, f"{self.base}/myip")
            return result.get("ip")
        except Exception:
            return None

    async def server_info(self) -> dict:
        """Fetch server metadata (relay_port, etc.)."""
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, _get, f"{self.base}/info")
        except Exception:
            return {}

    async def register_agent_menu(self, handle: str, menu: dict) -> None:
        """Register an agent's menu with the server."""
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None, _post, f"{self.base}/agent-menu",
                {"handle": handle, "menu": menu},
            )
        except Exception as exc:
            _log.warning("failed to register agent menu: %s", exc)

    def start_keepalive(self, endpoint: str) -> None:
        """Start a background task that re-registers every 30 seconds."""
        if self._keepalive_task and not self._keepalive_task.done():
            return
        self._keepalive_task = asyncio.create_task(
            self._keepalive_loop(endpoint), name="rendezvous-keepalive"
        )

    def stop_keepalive(self) -> None:
        if self._keepalive_task:
            self._keepalive_task.cancel()
            self._keepalive_task = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    async def _keepalive_loop(self, endpoint: str) -> None:
        while True:
            await asyncio.sleep(_KEEPALIVE_INTERVAL)
            ts     = _now_ts()
            handle = self.identity.handle
            sig    = _b64(self.identity.sign(":".join([handle, ts]).encode()))
            payload = {"handle": handle, "ts": ts, "sig": sig}
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(
                    None, _post, f"{self.base}/keepalive", payload
                )
                _log.debug("keepalive ok: %s", handle)
            except Exception as exc:
                _log.debug("keepalive failed, re-registering: %s", exc)
                await self.register(endpoint)
