"""Asyncio network loop — runs in a background thread.

Handles client (--connect) and server (--listen) peer connections.
Bridges the asyncio world with the curses UI via inbox/outbox queues.

Connection modes
----------------
Direct (no --server):
    --listen PORT        accept TCP on 0.0.0.0:PORT
    --connect HOST:PORT  dial HOST:PORT directly

Via rendezvous server (--server URL):
    --listen PORT        register endpoint, also open relay waiter
    --connect @handle    look up handle, try direct TCP, fall back to relay
    --connect HOST:PORT  still works — skips rendezvous
"""
from __future__ import annotations

import asyncio
import threading

from ezchat.crypto.keys import load_or_create_identity
from ezchat.net.connection import connect_to_peer, accept_peer

_RETRY_DELAY  = 5    # seconds between reconnect attempts (client mode)
_DIRECT_TIMEOUT = 3  # seconds to wait for a direct TCP connection before trying relay


def net_thread(ui, args, stop: threading.Event) -> None:
    """Entry point for the background network thread."""
    handle   = getattr(args, "handle", None) or "you"
    identity = load_or_create_identity(handle)
    server   = getattr(args, "server", None) or ""

    async def _handle_conn(conn) -> None:
        """Pump one established connection until it closes."""
        ui.inbox.put(("system_event", f"connected: {conn.peer_handle}"))
        try:
            from ezchat.store import upsert_peer
            ip_hint = getattr(args, "connect", None) or ""
            if ip_hint.startswith("@"):
                ip_hint = ""
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

    # ------------------------------------------------------------------
    # Relay helper
    # ------------------------------------------------------------------
    async def _relay_connect(relay_host: str, relay_port: int, target: str):
        """Connect to the relay server and request pairing with target."""
        reader, writer = await asyncio.open_connection(relay_host, relay_port)
        import json
        writer.write((json.dumps({"role": "connect", "target": target}) + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=10)
        resp = json.loads(line.decode().strip())
        if not resp.get("ok"):
            writer.close()
            raise ConnectionError(f"relay rejected: {resp.get('error', 'unknown')}")
        return reader, writer

    async def _relay_wait(relay_host: str, relay_port: int, my_handle: str):
        """Open a relay waiter connection. Returns (reader, writer)."""
        import json
        reader, writer = await asyncio.open_connection(relay_host, relay_port)
        writer.write((json.dumps({"role": "wait", "handle": my_handle}) + "\n").encode())
        await writer.drain()
        # Block until paired (server sends {"ok":true} when a connector arrives)
        line = await reader.readline()
        resp = json.loads(line.decode().strip())
        if not resp.get("ok"):
            writer.close()
            raise ConnectionError(f"relay wait failed: {resp.get('error', 'unknown')}")
        return reader, writer

    # ------------------------------------------------------------------
    # Connect mode
    # ------------------------------------------------------------------
    async def _connect_direct_or_relay(target: str) -> None:
        """Connect to @handle or host:port, retrying on disconnect."""
        from ezchat.net.rendezvous_client import RendezvousClient
        rdv = RendezvousClient(server, identity) if server else None

        while not stop.is_set():
            try:
                if target.startswith("@"):
                    peer_handle = target[1:]
                    if not rdv:
                        ui.inbox.put(("system_event",
                            "error: --server required to connect by @handle"))
                        return

                    ui.inbox.put(("system_event", f"looking up {target}…"))
                    entry = await rdv.lookup(peer_handle)

                    conn = None
                    if entry:
                        endpoint, _pubkey = entry
                        host, _, port_s = endpoint.rpartition(":")
                        host = host or "127.0.0.1"
                        port = int(port_s) if port_s.isdigit() else 9000
                        ui.inbox.put(("system_event",
                            f"trying direct connection to {host}:{port}…"))
                        try:
                            r, w = await asyncio.wait_for(
                                asyncio.open_connection(host, port),
                                timeout=_DIRECT_TIMEOUT,
                            )
                            from ezchat.net.handshake import do_handshake
                            from ezchat.net.connection import Connection
                            session, ph, pe = await do_handshake(r, w, identity)
                            conn = Connection(r, w, session, ph, identity, pe)
                        except Exception as exc:
                            ui.inbox.put(("system_event",
                                f"direct failed ({exc}), trying relay…"))

                    if conn is None:
                        # Fall back to relay
                        from urllib.parse import urlparse
                        parsed     = urlparse(server)
                        relay_host = parsed.hostname or "127.0.0.1"
                        relay_port = 9001
                        ui.inbox.put(("system_event",
                            f"connecting via relay to {peer_handle}…"))
                        r, w = await _relay_connect(relay_host, relay_port, peer_handle)
                        from ezchat.net.handshake import do_handshake
                        from ezchat.net.connection import Connection
                        session, ph, pe = await do_handshake(r, w, identity)
                        conn = Connection(r, w, session, ph, identity, pe)

                else:
                    # Direct host:port (legacy / LAN)
                    raw  = target
                    host, _, port_s = raw.rpartition(":")
                    host = host or "127.0.0.1"
                    port = int(port_s) if port_s.isdigit() else 9000
                    ui.inbox.put(("system_event", f"connecting to {host}:{port}…"))
                    conn = await connect_to_peer(host, port, identity)

                await _handle_conn(conn)

            except Exception as exc:
                ui.inbox.put(("system_event", f"connection failed: {exc}"))

            if stop.is_set():
                break
            ui.inbox.put(("system_event", f"retrying in {_RETRY_DELAY}s…"))
            await asyncio.sleep(_RETRY_DELAY)

    # ------------------------------------------------------------------
    # Listen mode
    # ------------------------------------------------------------------
    async def _listen(port: int) -> None:
        from ezchat.net.rendezvous_client import RendezvousClient
        rdv = RendezvousClient(server, identity) if server else None

        if rdv:
            # Discover public IP and register
            pub_ip = await rdv.my_public_ip() or "127.0.0.1"
            endpoint = f"{pub_ip}:{port}"
            ok = await rdv.register(endpoint)
            if ok:
                ui.inbox.put(("system_event",
                    f"registered with rendezvous as {identity.handle} @ {endpoint}"))
                rdv.start_keepalive(endpoint)
            else:
                ui.inbox.put(("system_event",
                    "warning: rendezvous registration failed — relay only"))

        ui.inbox.put(("system_event", f"listening on port {port}…"))
        conn_queue: asyncio.Queue = asyncio.Queue()

        async def _on_accept(r, w) -> None:
            try:
                c = await accept_peer(r, w, identity)
                await conn_queue.put(c)
            except Exception as exc:
                ui.inbox.put(("system_event", f"accept error: {exc}"))

        tcp_server = await asyncio.start_server(_on_accept, "0.0.0.0", port)

        # Also open a relay waiter if server is configured
        relay_task = None
        if rdv:
            relay_task = asyncio.create_task(
                _relay_listen_loop(rdv, conn_queue),
                name="relay-listen",
            )

        try:
            while not stop.is_set():
                conn = await conn_queue.get()
                asyncio.create_task(_handle_conn(conn))
                ui.inbox.put(("system_event", f"listening on port {port}…"))
        finally:
            tcp_server.close()
            if relay_task:
                relay_task.cancel()
            if rdv:
                rdv.stop_keepalive()

    async def _relay_listen_loop(rdv, conn_queue: asyncio.Queue) -> None:
        """Keep a relay waiter open; funnel accepted relay connections into conn_queue."""
        from urllib.parse import urlparse
        parsed     = urlparse(server)
        relay_host = parsed.hostname or "127.0.0.1"
        relay_port = 9001

        while not stop.is_set():
            try:
                ui.inbox.put(("system_event", "relay: waiting for connections…"))
                r, w = await _relay_wait(relay_host, relay_port, identity.handle)
                try:
                    conn = await accept_peer(r, w, identity)
                    await conn_queue.put(conn)
                except Exception as exc:
                    ui.inbox.put(("system_event", f"relay accept error: {exc}"))
                    try:
                        w.close()
                    except Exception:
                        pass
            except asyncio.CancelledError:
                return
            except Exception as exc:
                ui.inbox.put(("system_event", f"relay error: {exc}"))
                await asyncio.sleep(_RETRY_DELAY)

    # ------------------------------------------------------------------
    # Entry
    # ------------------------------------------------------------------
    async def _run() -> None:
        try:
            connect_target = getattr(args, "connect", None)
            listen_port    = getattr(args, "listen",  None)

            if connect_target:
                await _connect_direct_or_relay(connect_target)
            elif listen_port:
                await _listen(listen_port)
        except Exception as exc:
            ui.inbox.put(("system_event", f"network error: {exc}"))

    asyncio.run(_run())
