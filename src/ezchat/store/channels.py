"""Persist channel memberships to ~/.ezchat/channels.toml.

Format:
    [channels.general]
    members = ["alice", "bob"]
    created = "2026-03-19"
"""
from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path

from ezchat.home import get_home

_CHANNELS_PATH = get_home() / "channels.toml"


def load_channels() -> dict[str, list[str]]:
    """Return {channel_name: [member_handle, ...]}."""
    if not _CHANNELS_PATH.exists():
        return {}
    try:
        data = tomllib.loads(_CHANNELS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {
        name: attrs.get("members", [])
        for name, attrs in data.get("channels", {}).items()
    }


def save_channels(channels: dict[str, list[str]]) -> None:
    """Persist channel memberships to disk."""
    _CHANNELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    lines = ["# ezchat channels\n\n"]
    for name in sorted(channels):
        members = channels[name]
        members_toml = "[" + ", ".join(f'"{m}"' for m in members) + "]"
        lines.append(f"[channels.{name}]\n")
        lines.append(f"members = {members_toml}\n")
        lines.append(f'created = "{today}"\n\n')
    _CHANNELS_PATH.write_text("".join(lines), encoding="utf-8")
