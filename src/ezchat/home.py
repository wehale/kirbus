"""Resolve the ezchat data directory.

Priority order:
1. EZCHAT_HOME environment variable (full override)
2. Handle-based: ~/.ezchat-{handle}/  (when set via set_handle())
3. Default: ~/.ezchat/
"""
import os
from pathlib import Path

_handle: str | None = None


def set_handle(handle: str) -> None:
    """Set the handle used to derive the data directory.

    Call this early in startup, before anything imports get_home().
    Has no effect when EZCHAT_HOME is set.
    """
    global _handle
    _handle = handle


def get_home() -> Path:
    """Return the ezchat data directory, expanding ~ if needed."""
    env = os.environ.get("EZCHAT_HOME")
    if env:
        return Path(env).expanduser()
    if _handle:
        return Path.home() / f".ezchat-{_handle}"
    return Path.home() / ".ezchat"
