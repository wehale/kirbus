"""Built-in echo agent — reflects every message back with an [ack] prefix.

This is the simplest headless agent and serves as the Phase 2 test target.
Run with:
    uv run ezchat --echo-server --listen 9000
"""
from __future__ import annotations

import asyncio
import logging

from ezchat.crypto.keys import Identity, load_or_create_identity
from ezchat.net.connection import Connection, accept_peer

log = logging.getLogger(__name__)


async def _handle(conn: Connection) -> None:
    log.info("echo-server: %s connected", conn.peer_handle)
    try:
        while True:
            frame = await conn.recv()
            if frame is None:
                break
            text    = frame.get("text", "")
            channel = frame.get("channel", "")
            # Don't echo channel messages — echo-bot has no channel membership
            if channel:
                continue
            reply = f"[ack] {text}"
            await conn.send(reply)
            log.info("echo-server: %s → %r", conn.peer_handle, text)
    finally:
        await conn.close()
        log.info("echo-server: %s disconnected", conn.peer_handle)


async def run_echo_server(host: str, port: int, identity: Identity) -> None:
    """Start the echo server and serve connections forever."""

    async def _on_connect(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            conn = await accept_peer(reader, writer, identity)
            await _handle(conn)
        except Exception as exc:
            log.warning("echo-server: handshake/session error: %s", exc)

    server = await asyncio.start_server(_on_connect, host, port)
    addr   = server.sockets[0].getsockname()
    print(f"ezchat echo-server listening on {addr[0]}:{addr[1]}")
    print(f"  identity: {identity.handle}")
    print("  press Ctrl+C to stop")

    async with server:
        await server.serve_forever()
