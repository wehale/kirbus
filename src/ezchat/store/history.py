"""Persist shell-style command history to ~/.ezchat/command_history.txt."""
from __future__ import annotations

from pathlib import Path

from ezchat.home import get_home

def _history_path() -> Path:
    return get_home() / "command_history.txt"
_MAX_LINES = 1000


def load_cmd_history() -> list[str]:
    """Return saved command history (last _MAX_LINES entries)."""
    if not _history_path().exists():
        return []
    lines = _history_path().read_text(encoding="utf-8").splitlines()
    return [l for l in lines if l][-_MAX_LINES:]


def save_cmd_history(history: list[str]) -> None:
    """Write command history to disk, keeping last _MAX_LINES entries."""
    _history_path().parent.mkdir(parents=True, exist_ok=True)
    entries = [e for e in history if e][-_MAX_LINES:]
    _history_path().write_text(
        "\n".join(entries) + ("\n" if entries else ""),
        encoding="utf-8",
    )
