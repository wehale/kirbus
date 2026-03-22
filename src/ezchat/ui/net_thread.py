"""Asyncio network loop — runs in a background thread.

Full-mesh P2P via rendezvous server
-------------------------------------
On startup (when --server is set):
  1. Register our endpoint with the rendezvous server
  2. Fetch the list of all currently online peers
  3. Connect to each of them (direct TCP or relay fallback)
  4. Open a relay waiter so new peers can find us
  5. Poll /peers periodically and connect to anyone who joins later

Direct (no --server):
  --listen PORT        accept TCP on 0.0.0.0:PORT
  --connect HOST:PORT  dial HOST:PORT
"""
from __future__ import annotations

import asyncio
import queue as _queue
import threading

from ezchat.crypto.keys import load_or_create_identity
from ezchat.net.connection import connect_to_peer, accept_peer

_RETRY_DELAY    = 5    # seconds between reconnect attempts
_DIRECT_TIMEOUT = 3    # seconds before falling back to relay
_POLL_INTERVAL  = 20   # seconds between peer-list polls


def net_thread(ui, args, stop: threading.Event) -> None:
    """Entry point for the background network thread."""
    handle   = getattr(args, "handle", None) or "you"
    identity = load_or_create_identity(handle)
    server   = getattr(args, "server", None) or ""

    # Track which handles we're already connected to (or connecting to)
    _connected: set[str] = set()
    _connected_lock = asyncio.Lock()

    # Per-connection send queues — keyed by peer handle.
    # A single dispatcher task reads from ui.outbox and routes items here
    # so that each connection only processes messages meant for it.
    _peer_queues: dict[str, _queue.Queue] = {}

    async def _dispatch_outbox() -> None:
        """Read from shared outbox, route each item to the right peer queue(s)."""
        loop = asyncio.get_running_loop()
        while not stop.is_set():
            try:
                item = await loop.run_in_executor(
                    None, lambda: ui.outbox.get(timeout=0.1)
                )
                recipient = item[0]   # peer handle or "#channel"
                channel   = item[2] if len(item) > 2 else ""
                if channel:
                    # Fan-out to every channel member that has an open connection
                    ch = ui.channels.get(channel)
                    if ch:
                        for member in list(ch.members):
                            q = _peer_queues.get(member)
                            if q:
                                q.put(item)
                else:
                    # Direct message — route only to the intended peer
                    q = _peer_queues.get(recipient)
                    if q:
                        q.put(item)
            except Exception:
                pass

    async def _handle_conn(conn) -> None:
        """Pump one established connection until it closes."""
        peer_q: _queue.Queue = _queue.Queue()
        _peer_queues[conn.peer_handle] = peer_q

        ui.inbox.put(("system_event", f"connected: {conn.peer_handle}"))
        try:
            from ezchat.store import upsert_peer
            upsert_peer(conn.peer_handle, conn.peer_ed_pub, ip_hint="")
        except Exception as exc:
            ui.inbox.put(("system_event", f"warning: could not save peer: {exc}"))

        ui.inbox.put(("__peer_online__", conn.peer_handle))

        async def _send_loop() -> None:
            loop = asyncio.get_running_loop()
            while not stop.is_set():
                try:
                    item    = await loop.run_in_executor(
                        None, lambda: peer_q.get(timeout=0.1)
                    )
                    text    = item[1]
                    channel = item[2] if len(item) > 2 else ""
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
                    ui.inbox.put(("__channel_join__", ch_name, conn.peer_handle))
                    ui.inbox.put(("__peer_is_agent__", conn.peer_handle))
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
            _peer_queues.pop(conn.peer_handle, None)
            async with _connected_lock:
                _connected.discard(conn.peer_handle)
            ui.inbox.put(("system_event", f"disconnected: {conn.peer_handle}"))
            ui.inbox.put(("__peer_offline__", conn.peer_handle))

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------
    async def _relay_connect(relay_host: str, relay_port: int, target: str):
        import json as _json
        reader, writer = await asyncio.open_connection(relay_host, relay_port)
        writer.write((_json.dumps({"role": "connect", "target": target}) + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=10)
        resp = _json.loads(line.decode().strip())
        if not resp.get("ok"):
            writer.close()
            raise ConnectionError(f"relay rejected: {resp.get('error', 'unknown')}")
        return reader, writer

    async def _relay_wait(relay_host: str, relay_port: int, my_handle: str):
        import json as _json
        reader, writer = await asyncio.open_connection(relay_host, relay_port)
        writer.write((_json.dumps({"role": "wait", "handle": my_handle}) + "\n").encode())
        await writer.drain()
        line = await reader.readline()
        resp = _json.loads(line.decode().strip())
        if not resp.get("ok"):
            writer.close()
            raise ConnectionError(f"relay wait failed: {resp.get('error', 'unknown')}")
        return reader, writer

    async def _connect_to_peer(peer_handle: str, endpoint: str | None,
                                rdv) -> None:
        """Try direct TCP, fall back to relay. Runs as a task."""
        async with _connected_lock:
            if peer_handle in _connected:
                return
            _connected.add(peer_handle)

        from urllib.parse import urlparse
        relay_host = urlparse(server).hostname or "127.0.0.1"
        relay_port = 9001

        conn = None
        if endpoint:
            host, _, port_s = endpoint.rpartition(":")
            host = host or "127.0.0.1"
            port = int(port_s) if port_s.isdigit() else 9000
            ui.inbox.put(("system_event",
                f"trying direct connection to {peer_handle} ({host}:{port})…"))
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
            try:
                ui.inbox.put(("system_event",
                    f"connecting via relay to {peer_handle}…"))
                r, w = await _relay_connect(relay_host, relay_port, peer_handle)
                from ezchat.net.handshake import do_handshake
                from ezchat.net.connection import Connection
                session, ph, pe = await do_handshake(r, w, identity)
                conn = Connection(r, w, session, ph, identity, pe)
            except Exception as exc:
                ui.inbox.put(("system_event",
                    f"relay connection to {peer_handle} failed: {exc}"))
                async with _connected_lock:
                    _connected.discard(peer_handle)
                return

        await _handle_conn(conn)

    # ------------------------------------------------------------------
    # Mesh mode (--server)
    # ------------------------------------------------------------------
    async def _run_mesh(listen_port: int | None) -> None:
        from ezchat.net.rendezvous_client import RendezvousClient
        from urllib.parse import urlparse

        rdv        = RendezvousClient(server, identity)
        relay_host = urlparse(server).hostname or "127.0.0.1"
        relay_port = 9001

        # Discover public IP and register
        pub_ip   = await rdv.my_public_ip() or "127.0.0.1"
        port     = listen_port or 9000
        endpoint = f"{pub_ip}:{port}"
        ok       = await rdv.register(endpoint)
        if ok:
            ui.inbox.put(("system_event",
                f"registered as {identity.handle} @ {endpoint}"))
            rdv.start_keepalive(endpoint)
        else:
            ui.inbox.put(("system_event",
                "warning: rendezvous registration failed"))

        conn_queue: asyncio.Queue = asyncio.Queue()

        # Direct TCP listener
        if listen_port:
            async def _on_accept(r, w) -> None:
                try:
                    c = await accept_peer(r, w, identity)
                    await conn_queue.put(c)
                except Exception as exc:
                    ui.inbox.put(("system_event", f"accept error: {exc}"))

            tcp_server = await asyncio.start_server(
                _on_accept, "0.0.0.0", listen_port
            )
            ui.inbox.put(("system_event", f"listening on port {listen_port}…"))
        else:
            tcp_server = None

        # Relay waiter loop (runs as background task)
        async def _relay_listen_loop() -> None:
            while not stop.is_set():
                try:
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

        relay_task = asyncio.create_task(_relay_listen_loop(), name="relay-listen")

        # Drain accepted connections as tasks
        async def _accept_loop() -> None:
            while not stop.is_set():
                try:
                    conn = await asyncio.wait_for(conn_queue.get(), timeout=1.0)
                    asyncio.create_task(_handle_conn(conn))
                except asyncio.TimeoutError:
                    pass

        accept_task = asyncio.create_task(_accept_loop(), name="accept-loop")

        # Connect to all currently online peers
        existing = await rdv.peers()
        for peer in existing:
            asyncio.create_task(
                _connect_to_peer(peer["handle"], peer.get("endpoint"), rdv),
                name=f"connect-{peer['handle']}",
            )

        # Poll for new peers periodically
        async def _poll_loop() -> None:
            known: set[str] = {p["handle"] for p in existing}
            known.add(identity.handle)
            while not stop.is_set():
                await asyncio.sleep(_POLL_INTERVAL)
                try:
                    current = await rdv.peers()
                    for peer in current:
                        ph = peer["handle"]
                        if ph not in known:
                            known.add(ph)
                            ui.inbox.put(("system_event",
                                f"{ph} came online"))
                            asyncio.create_task(
                                _connect_to_peer(ph, peer.get("endpoint"), rdv),
                                name=f"connect-{ph}",
                            )
                except Exception:
                    pass

        poll_task = asyncio.create_task(_poll_loop(), name="peer-poll")

        try:
            await asyncio.Event().wait() if not stop.is_set() else None
            while not stop.is_set():
                await asyncio.sleep(0.5)
        finally:
            relay_task.cancel()
            accept_task.cancel()
            poll_task.cancel()
            if tcp_server:
                tcp_server.close()
            rdv.stop_keepalive()

    # ------------------------------------------------------------------
    # Legacy direct mode (no --server)
    # ------------------------------------------------------------------
    async def _run_direct() -> None:
        connect_target = getattr(args, "connect", None)
        listen_port    = getattr(args, "listen",  None)

        if connect_target:
            raw  = connect_target
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

        elif listen_port:
            ui.inbox.put(("system_event", f"listening on port {listen_port}…"))
            conn_queue: asyncio.Queue = asyncio.Queue()

            async def _on_accept(r, w) -> None:
                try:
                    c = await accept_peer(r, w, identity)
                    await conn_queue.put(c)
                except Exception as exc:
                    ui.inbox.put(("system_event", f"accept error: {exc}"))

            tcp_server = await asyncio.start_server(_on_accept, "0.0.0.0", listen_port)
            try:
                while not stop.is_set():
                    try:
                        conn = await asyncio.wait_for(conn_queue.get(), timeout=1.0)
                        asyncio.create_task(_handle_conn(conn))
                    except asyncio.TimeoutError:
                        pass
            finally:
                tcp_server.close()

    # ------------------------------------------------------------------
    # Entry
    # ------------------------------------------------------------------
    async def _run() -> None:
        dispatch_task = asyncio.create_task(_dispatch_outbox(), name="outbox-dispatch")
        try:
            if server:
                listen_port = getattr(args, "listen", None)
                await _run_mesh(listen_port)
            else:
                await _run_direct()
        except Exception as exc:
            ui.inbox.put(("system_event", f"network error: {exc}"))
        finally:
            dispatch_task.cancel()

    asyncio.run(_run())
