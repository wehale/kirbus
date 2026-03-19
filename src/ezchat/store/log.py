"""Append-only, Ed25519-signed message logs.

Line format:
    [YYYY-MM-DD HH:MM:SS] sender: text  sig:<base64url>

The signature covers: "{ts}|{sender}|{text}" (UTF-8) signed with the
sender's Ed25519 identity private key.  Recipients verify using the
sender's public key stored in peers.toml.

Log files live in ~/.ezchat/history/
    scratch.log    — ✦ scratch pad (local-only, signed by self)
    @alice.log     — DM with alice
    #general.log   — channel #general
"""
from __future__ import annotations

import base64
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from ezchat.home import get_home

_HISTORY_DIR = get_home() / "history"

# Per-path write locks so UI thread (scratch) and net thread (peers) don't race.
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _get_lock(path: Path) -> threading.Lock:
    key = str(path)
    with _locks_guard:
        if key not in _locks:
            _locks[key] = threading.Lock()
        return _locks[key]


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def conv_path(conv_key: str) -> Path:
    """Map a conversation key to its log file path.

    "\x00scratch"  → history/scratch.log
    "#general"     → history/#general.log
    "alice"        → history/alice.log
    """
    if conv_key.startswith("\x00"):
        name = "scratch"
    else:
        name = conv_key.replace("/", "_").replace("\\", "_").replace("\x00", "_")
    return _HISTORY_DIR / f"{name}.log"


def now_ts() -> str:
    """Return current timestamp as 'YYYY-MM-DD HH:MM:SS'."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Signing helpers
# ---------------------------------------------------------------------------

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s)


def sig_payload(ts: str, sender: str, text: str) -> bytes:
    """Bytes that are signed/verified: '{ts}|{sender}|{text}' UTF-8."""
    return f"{ts}|{sender}|{text}".encode("utf-8")


def sign_message(private_key: Ed25519PrivateKey, ts: str, sender: str, text: str) -> str:
    """Return base64url Ed25519 signature for a log entry."""
    return _b64(private_key.sign(sig_payload(ts, sender, text)))


def verify_sig(
    ts: str,
    sender: str,
    text: str,
    sig: str,
    pubkey: Ed25519PublicKey,
) -> bool:
    """Return True if sig is a valid Ed25519 signature over ts|sender|text."""
    try:
        pubkey.verify(_unb64(sig), sig_payload(ts, sender, text))
        return True
    except (InvalidSignature, Exception):
        return False


# ---------------------------------------------------------------------------
# Append
# ---------------------------------------------------------------------------

def append_message(
    conv_key: str,
    ts: str,
    sender: str,
    text: str,
    sig: str,
) -> None:
    """Append a signed message line to the conversation log. Thread-safe."""
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = conv_path(conv_key)
    line = f"[{ts}] {sender}: {text}  sig:{sig}\n"
    lock = _get_lock(path)
    with lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def _parse_line(line: str) -> Optional[tuple[str, str, str, str, str]]:
    """Parse a log line into (full_ts, hhmm, sender, text, sig).

    Returns None if the line cannot be parsed.
    """
    line = line.rstrip()
    if not line.startswith("["):
        return None
    try:
        ts_end = line.index("]")
        full_ts = line[1:ts_end]             # "YYYY-MM-DD HH:MM:SS"
        rest    = line[ts_end + 2:]          # "sender: text  sig:..."
        if "  sig:" in rest:
            body, _, sig = rest.rpartition("  sig:")
        else:
            body, sig = rest, ""
        sender, _, text = body.partition(": ")
        hhmm = full_ts[11:16]               # "HH:MM"
        date = full_ts[:10]                 # "YYYY-MM-DD"
        return full_ts, hhmm, sender, text, sig
    except (ValueError, IndexError):
        return None


def read_recent(
    conv_key: str,
    n: int = 500,
) -> list[tuple[str, str, str, str, str]]:
    """Return the last n log entries as (full_ts, hhmm, sender, text, sig)."""
    path = conv_path(conv_key)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    result = []
    for line in lines[-n:]:
        entry = _parse_line(line)
        if entry:
            result.append(entry)
    return result


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

def verify_log(
    conv_key: str,
    pubkeys: dict[str, Ed25519PublicKey],
) -> list[tuple[int, bool, str, str]]:
    """Verify all signatures in a log file.

    Returns list of (line_number, ok, sender, raw_line).
    ok=True means signature verified; False means invalid, missing, or unknown sender.
    """
    path = conv_path(conv_key)
    if not path.exists():
        return []
    results = []
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        entry = _parse_line(raw)
        if entry is None:
            results.append((i, False, "", raw))
            continue
        full_ts, _hhmm, sender, text, sig = entry
        pub = pubkeys.get(sender)
        if not pub:
            results.append((i, False, sender, raw))
            continue
        if not sig or sig in ("UNSIGNED", "UNVERIFIED"):
            results.append((i, False, sender, raw))
            continue
        ok = verify_sig(full_ts, sender, text, sig, pub)
        results.append((i, ok, sender, raw))
    return results
