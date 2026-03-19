"""Session key derivation and AES-256-GCM message encryption.

Key derivation
--------------
shared_secret = X25519(my_ephemeral_priv, peer_ephemeral_pub)
session_key   = HKDF-SHA256(shared_secret, salt=sorted_concat(both_x25519_pubs), info=b"ezchat-v1")

Encryption (per message)
------------------------
nonce      = 12 random bytes
ciphertext = AES-256-GCM(key=session_key, nonce=nonce, plaintext=data)
wire       = nonce || ciphertext || tag   (tag is appended by GCM automatically)
"""
from __future__ import annotations

import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


_NONCE_LEN = 12
_KEY_LEN   = 32   # AES-256


def derive_session_key(
    shared_secret:   bytes,
    my_x25519_pub:   bytes,
    peer_x25519_pub: bytes,
) -> bytes:
    """Derive a 32-byte AES-256-GCM session key via HKDF-SHA256.

    The salt is the sorted concatenation of both X25519 public keys so that
    both sides arrive at the same key regardless of who connected first.
    """
    pubs = sorted([my_x25519_pub, peer_x25519_pub])
    salt = pubs[0] + pubs[1]

    hkdf = HKDF(
        algorithm = hashes.SHA256(),
        length    = _KEY_LEN,
        salt      = salt,
        info      = b"ezchat-v1",
    )
    return hkdf.derive(shared_secret)


class SessionKey:
    """AES-256-GCM encrypt/decrypt wrapper around a derived key."""

    def __init__(self, key: bytes) -> None:
        if len(key) != _KEY_LEN:
            raise ValueError(f"Session key must be {_KEY_LEN} bytes, got {len(key)}")
        self._aes = AESGCM(key)

    def encrypt(self, plaintext: bytes) -> bytes:
        """Return nonce || ciphertext+tag (ready to put on the wire)."""
        nonce = os.urandom(_NONCE_LEN)
        ct    = self._aes.encrypt(nonce, plaintext, associated_data=None)
        return nonce + ct

    def decrypt(self, data: bytes) -> bytes:
        """Decrypt nonce || ciphertext+tag; raises InvalidTag on tampering."""
        nonce = data[:_NONCE_LEN]
        ct    = data[_NONCE_LEN:]
        return self._aes.decrypt(nonce, ct, associated_data=None)
