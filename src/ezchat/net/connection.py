"""Asyncio TCP connection: send/receive encrypted frames post-handshake.

A Connection wraps a (reader, writer) pair + a SessionKey and exposes:
    send(text)        — encrypt and send a chat message
    recv()            — receive and decrypt the next message; None on disconnect
    close()           — tear down the TCP connection

Messages on the wire (post-handshake) are JSON:
    { "type": "msg",  "text": "<utf-8 string>" }
    { "type": "bye" }
"""
from __future__ import annotations

import asyncio
import json

from ezchat.crypto.session import SessionKey
from ezchat.net.frame import read_frame, write_frame


class Connection:
    def __init__(
        self,
        reader:       asyncio.StreamReader,
        writer:       asyncio.StreamWriter,
        session:      SessionKey,
        peer_handle:  str,
    ) -> None:
        self.reader      = reader
        self.writer      = writer
        self.session     = session
        self.peer_handle = peer_handle
        self._closed     = False

    async def send(self, text: str, channel: str = "") -> None:
        payload = json.dumps({"type": "msg", "text": text, "channel": channel}).encode()
        await write_frame(self.writer, self.session.encrypt(payload))

    async def recv(self) -> dict | None:
        """Return the next decrypted frame dict, or None if disconnected.

        Frame dict keys: type, text, channel (optional).
        """
        try:
            enc  = await read_frame(self.reader)
            data = json.loads(self.session.decrypt(enc).decode())
            if data.get("type") == "bye":
                return None
            return data
        except (EOFError, asyncio.IncompleteReadError, ConnectionResetError):
            return None

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            bye = json.dumps({"type": "bye"}).encode()
            await write_frame(self.writer, self.session.encrypt(bye))
        except Exception:
            pass
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except Exception:
            pass


async def connect_to_peer(
    host:     str,
    port:     int,
    identity,           # ezchat.crypto.keys.Identity
) -> Connection:
    """Open a TCP connection to host:port and complete the handshake."""
    from ezchat.net.handshake import do_handshake
    reader, writer = await asyncio.open_connection(host, port)
    session, peer_handle = await do_handshake(reader, writer, identity)
    return Connection(reader, writer, session, peer_handle)


async def accept_peer(
    reader:   asyncio.StreamReader,
    writer:   asyncio.StreamWriter,
    identity,           # ezchat.crypto.keys.Identity
) -> Connection:
    """Complete the handshake on an accepted server connection."""
    from ezchat.net.handshake import do_handshake
    session, peer_handle = await do_handshake(reader, writer, identity)
    return Connection(reader, writer, session, peer_handle)
