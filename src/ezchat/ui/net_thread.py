"""Asyncio network loop — runs in a background thread.

Handles client (--connect) and server (--listen) peer connections.
Bridges the asyncio world with the curses UI via inbox/outbox queues.
"""
from __future__ import annotations

import asyncio
import threading

from ezchat.crypto.keys import load_or_create_identity
from ezchat.net.connection import connect_to_peer, accept_peer

_RETRY_DELAY = 5   # seconds between reconnect attempts (client mode)


def net_thread(ui, args, stop: threading.Event) -> None:
    """Entry point for the background network thread."""
    handle   = getattr(args, "handle", None) or "you"
    identity = load_or_create_identity(handle)

    async def _handle_conn(conn) -> None:
        """Pump one established connection until it closes."""
        ui.inbox.put(("system_event", f"connected: {conn.peer_handle}"))
        try:
            from ezchat.store import upsert_peer
            ip_hint = getattr(args, "connect", None) or ""
            upsert_peer(conn.peer_handle, conn.peer_ed_pub,
                        ip_hint=ip_hint.split(":")[0] if ip_hint else "")
        except Exception as exc:
            ui.inbox.put(("system_event", f"warning: could not save peer: {exc}"))

        ui.inbox.put(("__peer_online__", conn.peer_handle))

        async def _send_loop() -> None:
            loop = asyncio.get_running_loop()
            while not stop.is_set():
                try:
                    item    = await loop.run_in_executor(
                        None, lambda: ui.outbox.get(timeout=0.1)
                    )
                    text    = item[1]
                    channel = item[2] if len(item) > 2 else ""
                    if channel:
                        ch = ui.channels.get(channel)
                        if not ch or conn.peer_handle not in ch.members:
                            continue
                    await conn.send(text, channel=channel)
                except Exception:
                    pass

        send_task = asyncio.create_task(_send_loop())
        try:
            while not stop.is_set():
                frame = await conn.recv()
                if frame is None:
                    break
                text    = frame.get("text", "")
                channel = frame.get("channel", "")
                if text.startswith("\x00channel_invite\x00"):
                    ch_name = text.split("\x00")[2]
                    ui.inbox.put(("system_event",
                                  f"invited to #{ch_name} by {conn.peer_handle}"))
                    ui.inbox.put(("__channel_join__", ch_name))
                else:
                    ts     = frame.get("ts", "")
                    ed_sig = frame.get("ed_sig", "")
                    # Don't log raw AI wire frames — they contain null bytes
                    # and will be logged decoded by the UI layer
                    if not text.startswith(("\x00ai:q\x00", "\x00ai:a\x00")):
                        try:
                            conn.log_received(ts, text, channel, ed_sig)
                        except Exception:
                            pass
                    ui.inbox.put((conn.peer_handle, text, channel))
        finally:
            send_task.cancel()
            await conn.close()
            ui.inbox.put(("system_event", f"disconnected: {conn.peer_handle}"))
            ui.inbox.put(("__peer_offline__", conn.peer_handle))

    async def _run() -> None:
        try:
            if getattr(args, "connect", None):
                raw  = args.connect
                host, _, port_s = raw.rpartition(":")
                host = host or "127.0.0.1"
                port = int(port_s) if port_s.isdigit() else 9000
                while not stop.is_set():
                    try:
                        ui.inbox.put(("system_event", f"connecting to {host}:{port}…"))
                        conn = await connect_to_peer(host, port, identity)
                        await _handle_conn(conn)
                    except Exception as exc:
                        ui.inbox.put(("system_event", f"connection failed: {exc}"))
                    if stop.is_set():
                        break
                    ui.inbox.put(("system_event", f"retrying in {_RETRY_DELAY}s…"))
                    await asyncio.sleep(_RETRY_DELAY)

            elif getattr(args, "listen", None):
                port = args.listen
                ui.inbox.put(("system_event", f"listening on port {port}…"))
                conn_queue: asyncio.Queue = asyncio.Queue()

                async def _on_accept(r, w) -> None:
                    try:
                        c = await accept_peer(r, w, identity)
                        await conn_queue.put(c)
                    except Exception as exc:
                        ui.inbox.put(("system_event", f"accept error: {exc}"))

                server = await asyncio.start_server(_on_accept, "0.0.0.0", port)
                try:
                    while not stop.is_set():
                        conn = await conn_queue.get()
                        await _handle_conn(conn)
                        ui.inbox.put(("system_event", f"listening on port {port}…"))
                finally:
                    server.close()

        except Exception as exc:
            ui.inbox.put(("system_event", f"network error: {exc}"))

    asyncio.run(_run())
