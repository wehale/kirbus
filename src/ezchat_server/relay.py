"""TCP relay service.

Clients connect, send a single JSON line, then the server either queues
them as a "waiter" or pairs them with an existing waiter and pipes bytes
bidirectionally.

Protocol
--------
Client → server (one JSON line, newline-terminated):
    {"role": "wait",    "handle": "alice"}   # listener side
    {"role": "connect", "target": "alice"}   # connector side

Server → client (one JSON line):
    {"ok": true}              # paired (or queued — waiter receives this when paired)
    {"ok": false, "error": "not_found"}

After {"ok": true} both sides are in raw pipe mode.
The existing ezchat crypto handshake runs on top.
"""
from __future__ import annotations

import asyncio
import json
import logging

_log = logging.getLogger(__name__)

# handle → (reader, writer, future)
_waiting: dict[str, tuple[asyncio.StreamReader, asyncio.StreamWriter, asyncio.Future]] = {}

_RELAY_TIMEOUT = 120   # seconds a waiter will sit before being dropped


async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    """Copy bytes from src to dst until EOF or error."""
    try:
        while True:
            chunk = await src.read(4096)
            if not chunk:
                break
            dst.write(chunk)
            await dst.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            dst.close()
        except Exception:
            pass


async def handle_relay_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    peer = writer.get_extra_info("peername")
    try:
        line = await asyncio.wait_for(reader.readline(), timeout=10)
        msg  = json.loads(line.decode().strip())
    except Exception as exc:
        _log.debug("relay: bad hello from %s: %s", peer, exc)
        writer.close()
        return

    role = msg.get("role")

    if role == "wait":
        handle = msg.get("handle", "")
        if not handle:
            writer.close()
            return
        _log.info("relay: %s waiting as %r", peer, handle)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        _waiting[handle] = (reader, writer, fut)
        try:
            # Block until a connector arrives or timeout
            peer_reader, peer_writer = await asyncio.wait_for(fut, timeout=_RELAY_TIMEOUT)
        except asyncio.TimeoutError:
            _log.info("relay: waiter %r timed out", handle)
            _waiting.pop(handle, None)
            writer.close()
            return
        except asyncio.CancelledError:
            _waiting.pop(handle, None)
            writer.close()
            return

        # Notify waiter it's paired
        try:
            writer.write(b'{"ok":true}\n')
            await writer.drain()
        except Exception:
            peer_writer.close()
            writer.close()
            return

        _log.info("relay: piping %r ↔ %s", handle, peer_writer.get_extra_info("peername"))
        await asyncio.gather(
            _pipe(reader,      peer_writer),
            _pipe(peer_reader, writer),
        )

    elif role == "connect":
        target = msg.get("target", "")
        entry  = _waiting.pop(target, None)
        if not entry:
            _log.info("relay: %s wanted %r — not found", peer, target)
            try:
                writer.write(b'{"ok":false,"error":"not_found"}\n')
                await writer.drain()
            except Exception:
                pass
            writer.close()
            return

        wait_reader, wait_writer, fut = entry
        if fut.done():
            writer.close()
            return

        # Tell connector it's paired
        try:
            writer.write(b'{"ok":true}\n')
            await writer.drain()
        except Exception:
            fut.cancel()
            writer.close()
            return

        # Signal the waiter coroutine with our streams
        fut.set_result((reader, writer))
        _log.info("relay: paired %r ↔ %s", target, peer)
        # Waiter's coroutine now owns the piping for both sides

    else:
        _log.debug("relay: unknown role %r from %s", role, peer)
        writer.close()


async def start_relay_server(host: str, port: int) -> asyncio.Server:
    server = await asyncio.start_server(handle_relay_client, host, port)
    _log.info("relay: listening on %s:%d", host, port)
    return server
