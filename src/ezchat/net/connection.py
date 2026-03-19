"""Asyncio TCP connection: send/receive encrypted frames post-handshake.

A Connection wraps a (reader, writer) pair + a SessionKey and exposes:
    send(text)            — sign, encrypt, log, and send a chat message
    recv()                — receive and decrypt the next message; None on disconnect
    log_received(...)     — verify peer signature and append to message log
    close()               — tear down the TCP connection

Messages on the wire (post-handshake) are JSON:
    {
      "type":    "msg",
      "ts":      "YYYY-MM-DD HH:MM:SS",
      "text":    "<utf-8 string>",
      "channel": "<channel name or empty>",
      "ed_sig":  "<base64url Ed25519 signature of ts|sender|text>"
    }
    { "type": "bye" }
"""
from __future__ import annotations

import asyncio
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ezchat.crypto.session import SessionKey
from ezchat.net.frame import read_frame, write_frame


class Connection:
    def __init__(
        self,
        reader:             asyncio.StreamReader,
        writer:             asyncio.StreamWriter,
        session:            SessionKey,
        peer_handle:        str,
        identity,                        # ezchat.crypto.keys.Identity
        peer_ed_pub_bytes:  bytes,
    ) -> None:
        self.reader       = reader
        self.writer       = writer
        self.session      = session
        self.peer_handle  = peer_handle
        self.identity     = identity
        self.peer_ed_pub  = Ed25519PublicKey.from_public_bytes(peer_ed_pub_bytes)
        self._closed      = False

    async def send(self, text: str, channel: str = "") -> None:
        """Sign, encrypt, send, and log an outgoing message."""
        from ezchat.store import log as store_log
        ts  = store_log.now_ts()
        sig = store_log.sign_message(self.identity.private_key, ts, self.identity.handle, text)
        payload = json.dumps({
            "type":    "msg",
            "ts":      ts,
            "text":    text,
            "channel": channel,
            "ed_sig":  sig,
        }).encode()
        await write_frame(self.writer, self.session.encrypt(payload))
        try:
            conv_key = f"#{channel}" if channel else self.peer_handle
            store_log.append_message(conv_key, ts, self.identity.handle, text, sig)
        except Exception:
            pass

    async def recv(self) -> dict | None:
        """Return the next decrypted frame dict, or None if disconnected."""
        try:
            enc  = await read_frame(self.reader)
            data = json.loads(self.session.decrypt(enc).decode())
            if data.get("type") == "bye":
                return None
            return data
        except (EOFError, asyncio.IncompleteReadError, ConnectionResetError):
            return None

    def log_received(
        self,
        ts:      str,
        text:    str,
        channel: str,
        ed_sig:  str,
    ) -> bool:
        """Verify the peer's Ed25519 signature and append the message to the log.

        Returns True if the signature is valid.
        Unsigned or unverifiable messages are still logged, marked UNSIGNED/UNVERIFIED.
        """
        from ezchat.store import log as store_log
        conv_key = f"#{channel}" if channel else self.peer_handle
        if not ts:
            # Old client without ts — use current time, cannot sign
            ts = store_log.now_ts()
        if ed_sig and ed_sig not in ("UNSIGNED", "UNVERIFIED"):
            ok = store_log.verify_sig(ts, self.peer_handle, text, ed_sig, self.peer_ed_pub)
            sig_to_log = ed_sig if ok else "UNVERIFIED"
        else:
            ok, sig_to_log = False, "UNSIGNED"
        store_log.append_message(conv_key, ts, self.peer_handle, text, sig_to_log)
        return ok

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
    session, peer_handle, peer_ed_pub_bytes = await do_handshake(reader, writer, identity)
    return Connection(reader, writer, session, peer_handle, identity, peer_ed_pub_bytes)


async def accept_peer(
    reader:   asyncio.StreamReader,
    writer:   asyncio.StreamWriter,
    identity,           # ezchat.crypto.keys.Identity
) -> Connection:
    """Complete the handshake on an accepted server connection."""
    from ezchat.net.handshake import do_handshake
    session, peer_handle, peer_ed_pub_bytes = await do_handshake(reader, writer, identity)
    return Connection(reader, writer, session, peer_handle, identity, peer_ed_pub_bytes)
