"""Cryptographic handshake for ezchat peer connections.

Protocol (both sides run the same code)
----------------------------------------
1. Generate ephemeral X25519 keypair.
2. Send HELLO frame (plaintext JSON):
       { "handle":      "<display name>",
         "ed25519_pub": "<base64 raw>",
         "x25519_pub":  "<base64 raw>",
         "sig":         "<base64 Ed25519 signature of x25519_pub bytes>" }
3. Receive peer HELLO frame; verify signature.
4. X25519 ECDH → shared secret → HKDF → SessionKey.
5. Send READY frame (first encrypted frame):
       { "ok": true }
6. Receive peer READY frame and decrypt to confirm key agreement.

After step 6 both sides have a verified SessionKey and the peer's handle.
"""
from __future__ import annotations

import asyncio
import base64
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ezchat.crypto.keys import Identity, generate_ephemeral
from ezchat.crypto.session import SessionKey, derive_session_key
from ezchat.net.frame import read_frame, write_frame


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _unb64(s: str) -> bytes:
    return base64.b64decode(s)


async def do_handshake(
    reader:   asyncio.StreamReader,
    writer:   asyncio.StreamWriter,
    identity: Identity,
) -> tuple[SessionKey, str]:
    """Perform the ezchat handshake.

    Returns (session_key, peer_handle).
    Raises ValueError on verification failure.
    """
    ephemeral = generate_ephemeral()

    # --- Step 2: send our HELLO ---
    hello = {
        "handle":      identity.handle,
        "ed25519_pub": _b64(identity.pub_bytes),
        "x25519_pub":  _b64(ephemeral.pub_bytes),
        "sig":         _b64(identity.sign(ephemeral.pub_bytes)),
    }
    await write_frame(writer, json.dumps(hello).encode())

    # --- Step 3: receive peer HELLO ---
    raw = await read_frame(reader)
    peer = json.loads(raw.decode())

    peer_ed_pub_bytes  = _unb64(peer["ed25519_pub"])
    peer_x25519_bytes  = _unb64(peer["x25519_pub"])
    peer_sig           = _unb64(peer["sig"])
    peer_handle = peer["handle"]

    # Reject reserved handle names (prevents scratch-pad impersonation)
    _reserved = {"scratch", "\x00scratch", "✦ scratch", "system"}
    if peer_handle.lower() in {r.lower() for r in _reserved} or peer_handle.startswith("\x00"):
        raise ValueError(f"Peer attempted to use reserved handle: {peer_handle!r}")

    # Verify peer's Ed25519 signature over their X25519 public key
    peer_ed_pub = Ed25519PublicKey.from_public_bytes(peer_ed_pub_bytes)
    try:
        peer_ed_pub.verify(peer_sig, peer_x25519_bytes)
    except Exception as exc:
        raise ValueError(f"Handshake signature verification failed: {exc}") from exc

    # --- Step 4: derive session key ---
    shared_secret = ephemeral.exchange(peer_x25519_bytes)
    key_bytes     = derive_session_key(shared_secret, ephemeral.pub_bytes, peer_x25519_bytes)
    session       = SessionKey(key_bytes)

    # --- Steps 5 & 6: mutual READY confirmation ---
    ready_pt = json.dumps({"ok": True}).encode()
    await write_frame(writer, session.encrypt(ready_pt))

    peer_ready_enc = await read_frame(reader)
    peer_ready     = json.loads(session.decrypt(peer_ready_enc).decode())
    if not peer_ready.get("ok"):
        raise ValueError("Peer READY confirmation failed")

    return session, peer_handle
