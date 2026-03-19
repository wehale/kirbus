"""Identity and ephemeral keypairs for ezchat.

Identity  — Ed25519 signing keypair, persisted to ~/.ezchat/identity.json
Ephemeral — X25519 key exchange keypair, generated fresh per connection
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from ezchat.home import get_home

_IDENTITY_PATH = get_home() / "identity.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _unb64(s: str) -> bytes:
    return base64.b64decode(s)


def _ed_pub_bytes(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(Encoding.Raw, PublicFormat.Raw)


def _x25519_pub_bytes(key: X25519PublicKey) -> bytes:
    return key.public_bytes(Encoding.Raw, PublicFormat.Raw)


# ---------------------------------------------------------------------------
# Identity keypair (Ed25519 — signing / verification)
# ---------------------------------------------------------------------------
@dataclass
class Identity:
    handle:      str
    private_key: Ed25519PrivateKey
    public_key:  Ed25519PublicKey

    @property
    def pub_bytes(self) -> bytes:
        return _ed_pub_bytes(self.public_key)

    def sign(self, data: bytes) -> bytes:
        return self.private_key.sign(data)

    def to_dict(self) -> dict:
        priv_bytes = self.private_key.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption()
        )
        return {
            "handle":      self.handle,
            "ed25519_priv": _b64(priv_bytes),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Identity":
        priv = Ed25519PrivateKey.from_private_bytes(_unb64(d["ed25519_priv"]))
        return cls(
            handle      = d["handle"],
            private_key = priv,
            public_key  = priv.public_key(),
        )

    def save(self, path: Path = _IDENTITY_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path = _IDENTITY_PATH) -> "Identity":
        return cls.from_dict(json.loads(path.read_text()))


def generate_identity(handle: str) -> Identity:
    priv = Ed25519PrivateKey.generate()
    return Identity(handle=handle, private_key=priv, public_key=priv.public_key())


def load_or_create_identity(handle: str, path: Path = _IDENTITY_PATH) -> Identity:
    """Load identity from disk, creating and saving a new one if absent."""
    if path.exists():
        identity = Identity.load(path)
        # Update handle if it changed on the command line
        if handle and identity.handle != handle:
            identity = Identity(
                handle      = handle,
                private_key = identity.private_key,
                public_key  = identity.public_key,
            )
            identity.save(path)
        return identity
    identity = generate_identity(handle)
    identity.save(path)
    return identity


# ---------------------------------------------------------------------------
# Ephemeral keypair (X25519 — key exchange)
# ---------------------------------------------------------------------------
@dataclass
class EphemeralKeypair:
    private_key: X25519PrivateKey
    public_key:  X25519PublicKey

    @property
    def pub_bytes(self) -> bytes:
        return _x25519_pub_bytes(self.public_key)

    def exchange(self, peer_pub_bytes: bytes) -> bytes:
        """Perform X25519 ECDH; returns raw shared secret bytes."""
        peer_pub = X25519PublicKey.from_public_bytes(peer_pub_bytes)
        return self.private_key.exchange(peer_pub)


def generate_ephemeral() -> EphemeralKeypair:
    priv = X25519PrivateKey.generate()
    return EphemeralKeypair(private_key=priv, public_key=priv.public_key())
