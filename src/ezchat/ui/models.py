"""Data classes and constants shared across the ezchat UI."""
from __future__ import annotations

import curses
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
PRESENCE_W = 22   # columns for the presence panel (including its right border)
INPUT_H    = 3    # rows for the input box  (border-top + text + border-bottom)
STATUS_H   = 1    # rows for the status bar
MIN_COLS   = 60
MIN_ROWS   = 16

# Reserved internal peer key for the local scratch pad.
# The null-byte prefix makes it impossible for a real peer handle to collide.
SCRATCH_PEER     = "\x00scratch"
SCRATCH_LABEL    = "✦ scratch"
BACK_ENTRY       = "\x00.."          # sentinel for the ../ navigation row
RESERVED_HANDLES  = frozenset({SCRATCH_PEER, "scratch", SCRATCH_LABEL,
                                "system", "direct"})
RESERVED_CHANNELS = frozenset({"scratch", "system", "direct", "..", "../"})


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass
class Channel:
    name:    str
    members: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        """Conversation key used in Message.peer — e.g. '#general'."""
        return f"#{self.name}"


@dataclass
class Message:
    timestamp: str
    sender:    str
    text:      str
    kind:      str = "chat"   # "chat" | "system" | "error"
    peer:      str = ""       # which conversation this belongs to; "" = system/global
    date:      str = ""       # "YYYY-MM-DD" — used for date dividers


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------
def too_small(stdscr: curses.window) -> None:
    """Display a 'terminal too small' message and wait for a key."""
    stdscr.clear()
    try:
        stdscr.addstr(0, 0, f"Terminal too small — need {MIN_COLS}x{MIN_ROWS}")
    except curses.error:
        pass
    stdscr.refresh()
    stdscr.getch()
