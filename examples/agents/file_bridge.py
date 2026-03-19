"""
ezchat agent archetype: File Bridge
-------------------------------------
Lets trusted peers request files from a shared directory using the ezchat
file transfer protocol. Turns a headless machine into an accessible file
server — no shared drive, no VPN, no open ports required.

Run:
    ezchat --agent --script file_bridge.py --server https://chat.internal:8443

Config (~/.ezchat/config.toml):
    [agent]
    allowed_handles = ["@yourhandle", "@teammate"]
    description     = "File bridge — shared asset access"

Usage (from peer's chat window):
    list                    — show available files
    send report.pdf         — transfer report.pdf to the requesting peer
    send designs/mockup.png — subdirectories supported
"""

import os
import pathlib

TRUSTED    = {"@yourhandle", "@teammate"}
SHARE_DIR  = pathlib.Path("/path/to/shared/directory")   # set this


def on_message(sender: str, message: str) -> str | None:
    if sender not in TRUSTED:
        return None

    message = message.strip()

    # -----------------------------------------------------------------------
    # list — show available files
    # -----------------------------------------------------------------------
    if message.lower() == "list":
        files = sorted(
            str(p.relative_to(SHARE_DIR))
            for p in SHARE_DIR.rglob("*")
            if p.is_file()
        )
        if not files:
            return "No files available."
        return "Available files:\n" + "\n".join(f"  {f}" for f in files)

    # -----------------------------------------------------------------------
    # send <filename> — transfer a file to the requesting peer
    # -----------------------------------------------------------------------
    if message.lower().startswith("send "):
        filename = message[5:].strip()
        target   = (SHARE_DIR / filename).resolve()

        # Prevent path traversal outside SHARE_DIR
        if not str(target).startswith(str(SHARE_DIR.resolve())):
            return f"Access denied: {filename!r}"

        if not target.exists():
            return f"Not found: {filename!r} — try 'list' to see available files"

        # ezchat will call this handler's return value as a reply message
        # and separately initiate a file transfer to the requesting peer.
        # The send_file() call below is provided by the ezchat agent runtime.
        send_file(str(target))   # noqa: F821 — injected by ezchat agent runner
        return f"Sending {filename} ({target.stat().st_size // 1024} KB)..."

    return "Commands: 'list'  |  'send <filename>'"
