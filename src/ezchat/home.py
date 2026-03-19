"""Resolve the ezchat data directory.

Defaults to ~/.ezchat/. Override with the EZCHAT_HOME environment variable:

    EZCHAT_HOME=~/.ezchat-alice ezchat --handle alice --listen 9000
    EZCHAT_HOME=~/.ezchat-bob   ezchat --handle bob   --connect localhost:9000
"""
import os
from pathlib import Path


def get_home() -> Path:
    """Return the ezchat data directory, expanding ~ if needed."""
    env = os.environ.get("EZCHAT_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".ezchat"
