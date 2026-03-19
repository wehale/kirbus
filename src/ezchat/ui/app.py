"""Curses UI shell for ezchat — Phase 1.

Layout
------
┌────────────────────┬────────────────────────────────────────┐
│  PRESENCE  (20 ch) │  CHAT                                  │
│                    │                                        │
│  ● you             │  [12:34] system: Welcome to ezchat     │
│                    │  [12:34] you: hello                    │
├────────────────────┴────────────────────────────────────────┤
│  STATUS BAR                                                 │
├─────────────────────────────────────────────────────────────┤
│  > _                                                        │
└─────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import curses
import queue
import re
import textwrap
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ezchat.ui.theme import Theme, current_theme, list_themes, set_theme

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PRESENCE_W = 22   # columns for the presence panel (including its right border)
INPUT_H    = 3    # rows for the input box  (border-top + text + border-bottom)
STATUS_H   = 1    # rows for the status bar
MIN_COLS   = 60
MIN_ROWS   = 16

# Reserved internal peer key for the local scratch pad.
# The null-byte prefix makes it impossible for a real peer handle to collide —
# peer handles are validated to be printable ASCII/UTF-8 with no control chars.
SCRATCH_PEER    = "\x00scratch"
SCRATCH_LABEL   = "✦ scratch"
BACK_ENTRY      = "\x00.."          # sentinel for the ../ navigation row
RESERVED_HANDLES = frozenset({SCRATCH_PEER, "scratch", SCRATCH_LABEL,
                               "system", "direct"})
RESERVED_CHANNELS = frozenset({"scratch", "system", "direct", "..", "../"})


# ---------------------------------------------------------------------------
# Channel model
# ---------------------------------------------------------------------------
@dataclass
class Channel:
    name:    str
    members: list[str] = field(default_factory=list)  # peer handles in this channel

    @property
    def key(self) -> str:
        """Conversation key used in Message.peer — e.g. '#general'."""
        return f"#{self.name}"


# ---------------------------------------------------------------------------
# Message model
# ---------------------------------------------------------------------------
@dataclass
class Message:
    timestamp: str
    sender: str
    text: str
    kind: str = "chat"   # "chat" | "system" | "ai" | "error"
    peer: str = ""       # which conversation this belongs to; "" = system/global
    date: str = ""       # "YYYY-MM-DD" — used for date dividers


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
class UI:
    """Manages all curses windows and the main event loop."""

    def __init__(self, stdscr: curses.window, theme: Theme, handle: str = "you") -> None:
        self.stdscr  = stdscr
        self.theme   = theme
        self.handle  = handle

        self.messages: list[Message] = []
        self.scroll: int = 0          # lines scrolled up from the bottom

        self.input_buf: list[str] = []
        self.cursor: int = 0          # cursor position in input_buf

        # Command history (shell-style ↑/↓ navigation)
        self.history: list[str] = []
        self.history_idx: int = -1    # -1 = not browsing history
        self.history_draft: str = ""  # saved draft while browsing

        # Direct peers (not yourself, not scratch)
        self.peers: list[tuple[str, bool]] = []

        # Channels: name → Channel
        self.channels: dict[str, Channel] = {}

        # Presence panel state
        self.focus: str = "input"       # "input" | "presence"
        self.peer_cursor: int = 0       # highlighted row in presence panel
        self.active_peer: str = ""      # conversation key (SCRATCH_PEER, #channel, or handle)
        self.view: str = "top"          # "top" | channel name (when inside a channel)

        # Unread counts per peer handle
        self.unread: dict[str, int] = {}

        # Thread-safe queues bridging the curses loop and the asyncio network thread
        self.inbox:     queue.Queue[tuple[str, str]] = queue.Queue()   # (sender, text)
        self.outbox:    queue.Queue[tuple[str, str]] = queue.Queue()   # (peer, text)
        # Optional queue populated in test mode so sim peers can react to user messages
        self.sim_inbox: queue.Queue | None = None

        self._setup_curses()
        self._create_windows()
        self._post_init()

    # ------------------------------------------------------------------
    def _setup_curses(self) -> None:
        curses.curs_set(1)
        curses.start_color()
        curses.use_default_colors()
        self.theme.activate()
        self.stdscr.keypad(True)
        self.stdscr.timeout(100)     # non-blocking getch (100 ms)

    def _post_init(self) -> None:
        self._system("Welcome to ezchat  |  type /help for commands")

    # ------------------------------------------------------------------
    # Window geometry
    # ------------------------------------------------------------------
    def _create_windows(self) -> None:
        rows, cols = self.stdscr.getmaxyx()
        self.rows, self.cols = rows, cols

        pane_h = max(1, rows - INPUT_H - STATUS_H)
        chat_w = max(1, cols - PRESENCE_W)

        # Presence panel (left)
        self.pw = curses.newwin(pane_h, PRESENCE_W, 0, 0)
        # Chat panel (right of presence)
        self.cw = curses.newwin(pane_h, chat_w, 0, PRESENCE_W)
        # Status bar
        self.sw = curses.newwin(STATUS_H, cols, pane_h, 0)
        # Input box
        self.iw = curses.newwin(INPUT_H, cols, pane_h + STATUS_H, 0)

        self.chat_w    = chat_w
        self.chat_h    = pane_h
        self.pane_h    = pane_h

    def _resize(self) -> None:
        curses.update_lines_cols()
        rows, cols = curses.LINES, curses.COLS
        if rows == self.rows and cols == self.cols:
            return

        self.stdscr.clear()
        self.rows, self.cols = rows, cols

        pane_h = max(1, rows - INPUT_H - STATUS_H)
        chat_w = max(1, cols - PRESENCE_W)

        self.pw.resize(pane_h, PRESENCE_W)
        self.pw.mvwin(0, 0)

        self.cw.resize(pane_h, chat_w)
        self.cw.mvwin(0, PRESENCE_W)

        self.sw.resize(STATUS_H, cols)
        self.sw.mvwin(pane_h, 0)

        self.iw.resize(INPUT_H, cols)
        self.iw.mvwin(pane_h + STATUS_H, 0)

        self.chat_w = chat_w
        self.chat_h = pane_h
        self.pane_h = pane_h

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------
    _URL_RE = re.compile(
        r"(https?://[^\s\"'<>)\]]+|ftp://[^\s\"'<>)\]]+)"
    )

    def _split_urls(self, text: str) -> list[tuple[str, bool]]:
        """Split text into [(segment, is_url), ...] segments."""
        parts: list[tuple[str, bool]] = []
        last = 0
        for m in self._URL_RE.finditer(text):
            if m.start() > last:
                parts.append((text[last:m.start()], False))
            parts.append((m.group(), True))
            last = m.end()
        if last < len(text):
            parts.append((text[last:], False))
        return parts or [(text, False)]

    def _safe_addstr(self, win: curses.window, y: int, x: int,
                     text: str, attr: int = 0) -> None:
        """addstr that silently ignores out-of-bounds writes."""
        try:
            win.addstr(y, x, text, attr)
        except curses.error:
            pass

    def _addstr_with_urls(self, win: curses.window, y: int, x: int,
                          text: str, base_attr: int, max_w: int) -> None:
        """Render text, highlighting URLs with underline + accent color."""
        url_attr  = self.theme.accent | curses.A_UNDERLINE
        col       = x
        remaining = max_w
        for segment, is_url in self._split_urls(text):
            if remaining <= 0:
                break
            chunk = segment[:remaining]
            try:
                win.addstr(y, col, chunk, url_attr if is_url else base_attr)
            except curses.error:
                pass
            col       += len(chunk)
            remaining -= len(chunk)

    def _draw_border(self, win: curses.window, title: str = "",
                     attr: Optional[int] = None) -> None:
        b = self.theme.borders
        a = attr if attr is not None else self.theme.border
        h, w = win.getmaxyx()

        # Top row
        self._safe_addstr(win, 0, 0, b["tl"] + b["h"] * (w - 2) + b["tr"], a)
        # Bottom row
        self._safe_addstr(win, h - 1, 0, b["bl"] + b["h"] * (w - 2) + b["br"], a)
        # Sides
        for row in range(1, h - 1):
            self._safe_addstr(win, row, 0,     b["v"], a)
            self._safe_addstr(win, row, w - 1, b["v"], a)

        # Title
        if title and w > 4:
            label = f" {title} "[:w - 4]
            align = self.theme.title_align
            if align == "center":
                x = max(1, (w - len(label)) // 2)
            elif align == "right":
                x = max(1, w - len(label) - 1)
            else:
                x = 2
            self._safe_addstr(win, 0, x, label, a | curses.A_BOLD)

    # ------------------------------------------------------------------
    # Panel renderers
    # ------------------------------------------------------------------
    def _presence_rows(self) -> list[tuple[str, str, bool]]:
        """Return (key, display_label, online) rows for the current view."""
        if self.view != "top":
            # Channel view: ../ + members
            ch = self.channels.get(self.view)
            members = ch.members if ch else []
            rows = [(BACK_ENTRY, "../", True)]
            for handle in members:
                online = any(h == handle and on for h, on in self.peers)
                rows.append((handle, handle, online))
            return rows
        else:
            # Top-level view: scratch, channels section, direct section
            rows: list[tuple[str, str, bool]] = [(SCRATCH_PEER, SCRATCH_LABEL, True)]
            if self.channels:
                rows.append(("\x00ch_header", "── channels ──", False))
                for name, ch in sorted(self.channels.items()):
                    rows.append((ch.key, f"# {name}", True))
            if self.peers:
                rows.append(("\x00dm_header", "── direct ──", False))
                for handle, online in self.peers:
                    rows.append((handle, handle, online))
            return rows

    def _draw_presence(self) -> None:
        self.pw.erase()
        focused     = self.focus == "presence"
        border_attr = self.theme.accent if focused else self.theme.border
        panel_title = f"# {self.view}" if self.view != "top" else "peers"
        self._draw_border(self.pw, panel_title, attr=border_attr)
        h, w = self.pw.getmaxyx()
        inner_w = w - 4

        rows = self._presence_rows()
        # Clamp cursor
        selectable = [i for i, (k, _, _) in enumerate(rows)
                      if not k.startswith("\x00ch_") and not k.startswith("\x00dm_")]
        if selectable:
            if self.peer_cursor not in selectable:
                self.peer_cursor = selectable[0]
        else:
            self.peer_cursor = 0

        for i, (key, label, online) in enumerate(rows):
            row = i + 1
            if row >= h - 1:
                break

            is_header  = key in ("\x00ch_header", "\x00dm_header")
            is_cursor  = focused and i == self.peer_cursor and not is_header
            is_active  = key == self.active_peer
            is_back    = key == BACK_ENTRY
            is_scratch = key == SCRATCH_PEER

            if is_header:
                self._safe_addstr(self.pw, row, 2, label[:inner_w], self.theme.timestamp)
                continue

            if is_cursor:
                attr = self.theme.status
            elif is_active:
                attr = self.theme.accent | curses.A_BOLD
            elif is_back:
                attr = self.theme.system
            elif is_scratch:
                attr = self.theme.accent
            else:
                attr = self.theme.online if online else self.theme.offline

            badge    = f" [{self.unread[key]}]" if key in self.unread else ""
            dot      = "" if is_scratch or is_back else ("●" if online else "○")
            prefix   = f"{dot} " if dot else ""
            row_text = f"{prefix}{label}{badge}"[:inner_w]
            if is_cursor:
                row_text = row_text.ljust(inner_w)
            self._safe_addstr(self.pw, row, 2, row_text, attr)

            if badge and not is_cursor:
                badge_x = 2 + len(f"{prefix}{label}")
                self._safe_addstr(self.pw, row, badge_x, badge[:inner_w - badge_x + 2],
                                  self.theme.error | curses.A_BOLD)

        self.pw.noutrefresh()

    def _date_label(self, date: str) -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        from datetime import date as date_cls, timedelta
        yesterday = (date_cls.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        if date == today:
            return "today"
        if date == yesterday:
            return "yesterday"
        try:
            return datetime.strptime(date, "%Y-%m-%d").strftime("%a %b %-d")
        except ValueError:
            return date

    def _wrap_messages(self) -> list[tuple[Message | None, str, int]]:
        """Return [(msg_or_None, line_text, attr), ...] for the active conversation.
        msg is None for date divider rows.
        """
        inner_w = max(1, self.chat_w - 4)
        lines: list[tuple[Message | None, str, int]] = []
        last_date: str = ""

        for msg in self.messages:
            if self.active_peer:
                if msg.peer != self.active_peer:
                    continue
            else:
                if msg.peer != "":
                    continue

            # Date divider when the day changes
            if msg.date and msg.date != last_date:
                last_date = msg.date
                label    = self._date_label(msg.date)
                pad      = max(0, (inner_w - len(label) - 2) // 2)
                divider  = "─" * pad + f" {label} " + "─" * pad
                lines.append((None, divider[:inner_w], self.theme.timestamp))

            attr   = self._msg_attr(msg)
            prefix = f"[{msg.timestamp}] {msg.sender}: "
            first  = True
            for part in textwrap.wrap(prefix + msg.text, width=inner_w) or [prefix + msg.text]:
                lines.append((msg, part if first else "  " + part, attr))
                first = False

        return lines

    def _msg_attr(self, msg: Message) -> int:
        if msg.kind == "system": return self.theme.system
        if msg.kind == "ai":     return self.theme.ai
        if msg.kind == "error":  return self.theme.error
        # Distinguish own messages from incoming
        if msg.sender == self.handle: return self.theme.accent
        return self.theme.chat

    def _draw_chat(self) -> None:
        self.cw.erase()
        total_unread = sum(self.unread.values())
        if self.active_peer:
            chat_title = f"{self.active_peer} [{total_unread}]" if total_unread else self.active_peer
        else:
            chat_title = "chat — select a peer with Tab"
        chat_border = self.theme.error if total_unread else self.theme.border
        self._draw_border(self.cw, chat_title, attr=chat_border)
        inner_h = self.chat_h - 2   # minus top/bottom border
        inner_w = self.chat_w - 4

        lines = self._wrap_messages()
        total = len(lines)

        # Clamp scroll
        self.scroll = max(0, min(self.scroll, max(0, total - inner_h)))

        # Which lines to show
        start = max(0, total - inner_h - self.scroll)
        visible = lines[start: start + inner_h]

        for row_offset, (_, text, attr) in enumerate(visible):
            row = row_offset + 1   # +1 for top border
            self._addstr_with_urls(self.cw, row, 2, text[:inner_w], attr, inner_w)

        # Scroll indicator
        if self.scroll > 0:
            indicator = f" ↑ {self.scroll} more "
            self._safe_addstr(self.cw, 1, self.chat_w - len(indicator) - 2,
                              indicator, self.theme.system)

        self.cw.noutrefresh()

    def _draw_status(self) -> None:
        self.sw.erase()
        h, w = self.sw.getmaxyx()
        peer_count = sum(1 for _, on in self.peers if on)
        to_label = f"→ {self.active_peer}" if self.active_peer else "no peer selected"
        total_unread = sum(self.unread.values())
        unread_label = f"  │  ● {total_unread}" if total_unread else ""
        bar = f"  {self.handle}  │  {to_label}  │  online: {peer_count}{unread_label}  "
        bar = bar.ljust(w)[:w]
        self._safe_addstr(self.sw, 0, 0, bar, self.theme.status)
        self.sw.noutrefresh()

    def _draw_input(self) -> None:
        self.iw.erase()
        self._draw_border(self.iw)
        h, w = self.iw.getmaxyx()
        inner_w = w - 4

        prefix = f"→ {self.active_peer}: " if self.active_peer else "> "
        buf_str = "".join(self.input_buf)

        # Scroll view if cursor is beyond visible area
        visible_w = inner_w - len(prefix)
        view_start = max(0, self.cursor - visible_w + 1)
        visible    = buf_str[view_start: view_start + visible_w]

        self._safe_addstr(self.iw, 1, 2, prefix + visible, self.theme.input)

        # Place the cursor
        cursor_x = 2 + len(prefix) + (self.cursor - view_start)
        try:
            self.iw.move(1, min(cursor_x, w - 2))
        except curses.error:
            pass

        self.iw.noutrefresh()

    def draw_all(self) -> None:
        self._draw_presence()
        self._draw_chat()
        self._draw_status()
        self._draw_input()
        curses.doupdate()

    # ------------------------------------------------------------------
    # Message helpers
    # ------------------------------------------------------------------
    def _now(self) -> tuple[str, str]:
        """Return (HH:MM, YYYY-MM-DD)."""
        now = datetime.now()
        return now.strftime("%H:%M"), now.strftime("%Y-%m-%d")

    def _system(self, text: str) -> None:
        ts, date = self._now()
        self.messages.append(Message(ts, "system", text, "system", date=date))

    def _error(self, text: str) -> None:
        ts, date = self._now()
        self.messages.append(Message(ts, "system", text, "error", date=date))

    def _chat(self, sender: str, text: str, channel: str = "") -> None:
        ts, date = self._now()
        if channel:
            convo = f"#{channel}"
        else:
            convo = self.active_peer if sender == self.handle else sender
        self.messages.append(Message(ts, sender, text, "chat", peer=convo, date=date))
        if sender != self.handle and convo != self.active_peer:
            self.unread[convo] = self.unread.get(convo, 0) + 1
        # Let sim peers react to channel messages from the real user
        if channel and sender == self.handle and self.sim_inbox is not None:
            _log.debug("sim_inbox.put channel=%r text=%r", channel, text)
            self.sim_inbox.put((channel, text))

    # ------------------------------------------------------------------
    # Command router
    # ------------------------------------------------------------------
    _HELP = """\
/help                        show this message
/theme <name>                switch theme
/themes                      list available themes
/clear                       clear chat history
/quit  (or /q)               exit ezchat
/channel create <name>       create a new channel
/channel join <name>         join an existing channel
/channel invite <peer> [ch]  invite a peer (channel inferred if inside one)
/channel leave <name>        leave a channel
---
Tab                 focus peer list  (↑/↓ navigate, Enter select, Esc cancel)
↑ / ↓              command history (when input focused)
PgUp / PgDn        scroll chat"""

    def _handle_command(self, raw: str) -> None:
        parts = raw.strip().split(maxsplit=1)
        cmd   = parts[0].lower()
        arg   = parts[1] if len(parts) > 1 else ""

        if cmd in ("/quit", "/q", "/exit"):
            raise SystemExit(0)

        elif cmd == "/help":
            for line in self._HELP.splitlines():
                self._system(line)

        elif cmd == "/themes":
            self._system("Available themes: " + "  ".join(list_themes()))

        elif cmd == "/theme":
            if not arg:
                self._error("Usage: /theme <name>")
                return
            try:
                self.theme = set_theme(arg)
                self.theme.activate()
                self._system(f"Theme changed to {self.theme.name}")
            except ValueError as exc:
                self._error(str(exc))

        elif cmd == "/channel":
            self._handle_channel_command(arg)

        elif cmd == "/clear":
            self.messages.clear()
            self.scroll = 0

        else:
            self._error(f"Unknown command: {cmd}  (type /help for commands)")

    def _handle_channel_command(self, arg: str) -> None:
        parts   = arg.strip().split(maxsplit=2)
        sub     = parts[0].lower() if parts else ""
        name    = parts[1] if len(parts) > 1 else ""
        extra   = parts[2] if len(parts) > 2 else ""

        if sub == "create":
            if not name:
                self._error("Usage: /channel create <name>")
                return
            if name.lower() in RESERVED_CHANNELS or name.startswith((".", "/")):
                self._error(f"'{name}' is a reserved name")
                return
            if name in self.channels:
                self._error(f"Channel #{name} already exists")
                return
            self.channels[name] = Channel(name=name, members=[self.handle])
            self._system(f"Created channel #{name}")

        elif sub == "join":
            if not name:
                self._error("Usage: /channel join <name>")
                return
            if name not in self.channels:
                self.channels[name] = Channel(name=name, members=[self.handle])
                self._system(f"Joined channel #{name}")
            else:
                ch = self.channels[name]
                if self.handle not in ch.members:
                    ch.members.append(self.handle)
                self._system(f"Already in #{name}")

        elif sub == "invite":
            if not name:
                self._error("Usage: /channel invite <peer> [channel]")
                return
            peer    = name
            # If no channel given, infer from current view
            ch_name = extra or (self.view if self.view != "top" else "")
            if not ch_name:
                self._error("Not in a channel — use: /channel invite <peer> <channel>")
                return
            if ch_name not in self.channels:
                self._error(f"Channel #{ch_name} does not exist")
                return
            ch = self.channels[ch_name]
            if peer not in ch.members:
                ch.members.append(peer)
            # Queue invite message for the network layer
            self.outbox.put((peer, f"\x00channel_invite\x00{ch_name}"))
            self._system(f"Invited {peer} to #{ch_name}")

        elif sub == "leave":
            if not name:
                self._error("Usage: /channel leave <name>")
                return
            if name not in self.channels:
                self._error(f"Not in channel #{name}")
                return
            ch = self.channels.pop(name)
            if self.active_peer == ch.key:
                self.active_peer = SCRATCH_PEER
                self.view = "top"
            self._system(f"Left channel #{name}")

        else:
            self._error("Usage: /channel create|join|invite|leave ...")

    # ------------------------------------------------------------------
    # Input helpers
    # ------------------------------------------------------------------
    def _set_input(self, text: str) -> None:
        """Replace the input buffer with text and place cursor at end."""
        self.input_buf = list(text)
        self.cursor = len(self.input_buf)

    # ------------------------------------------------------------------
    # Key handling
    # ------------------------------------------------------------------
    def _handle_key(self, ch: int) -> None:
        if ch == curses.KEY_RESIZE:
            self._resize()
            return

        # Tab — toggle focus between input and presence panel
        if ch == ord("\t"):
            if self.focus == "input":
                self.focus = "presence"
                self.peer_cursor = max(0, min(self.peer_cursor, len(self.peers) - 1))
                curses.curs_set(0)
            else:
                self.focus = "input"
                curses.curs_set(1)
            return

        # Escape — return focus to input from anywhere
        if ch == 27:
            self.focus = "input"
            curses.curs_set(1)
            return

        # --- Presence panel navigation ---
        if self.focus == "presence":
            rows      = self._presence_rows()
            selectable = [i for i, (k, _, _) in enumerate(rows)
                          if not k.startswith("\x00ch_") and not k.startswith("\x00dm_")]

            if ch == curses.KEY_UP:
                idx = selectable.index(self.peer_cursor) if self.peer_cursor in selectable else 0
                self.peer_cursor = selectable[max(0, idx - 1)]
            elif ch == curses.KEY_DOWN:
                idx = selectable.index(self.peer_cursor) if self.peer_cursor in selectable else 0
                self.peer_cursor = selectable[min(len(selectable) - 1, idx + 1)]
            elif ch in (curses.KEY_ENTER, ord("\n"), ord("\r")):
                if not rows or self.peer_cursor >= len(rows):
                    return
                key, label, _ = rows[self.peer_cursor]
                if key == BACK_ENTRY:
                    # ../ — go back to top view
                    self.view = "top"
                    self.peer_cursor = 0
                elif key.startswith("#"):
                    # Enter a channel
                    ch_name = key[1:]
                    self.view = ch_name
                    self.active_peer = key
                    self.unread.pop(key, None)
                    self.peer_cursor = 0
                    self.focus = "input"
                    curses.curs_set(1)
                else:
                    # Direct peer or scratch
                    self.active_peer = key
                    self.unread.pop(key, None)
                    if key != SCRATCH_PEER:
                        self._system(f"Now chatting with {label}")
                    self.focus = "input"
                    curses.curs_set(1)
            return

        # Enter — submit input
        elif ch in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            text = "".join(self.input_buf).strip()
            self.input_buf.clear()
            self.cursor = 0
            self.scroll = 0         # jump back to bottom on send
            self.history_idx = -1
            self.history_draft = ""
            if not text:
                return
            # Save to history (deduplicate consecutive identical entries)
            if not self.history or self.history[-1] != text:
                self.history.append(text)
            if text.startswith("/"):
                self._handle_command(text)
            else:
                channel = self.view if self.view != "top" else ""
                self._chat(self.handle, text, channel=channel)
                # Queue for the network thread — never for scratch
                if self.active_peer and self.active_peer != SCRATCH_PEER:
                    self.outbox.put((self.active_peer, text, channel))

        # Backspace
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            if self.cursor > 0:
                self.cursor -= 1
                del self.input_buf[self.cursor]

        # Delete
        elif ch == curses.KEY_DC:
            if self.cursor < len(self.input_buf):
                del self.input_buf[self.cursor]

        # Cursor movement
        elif ch == curses.KEY_LEFT:
            self.cursor = max(0, self.cursor - 1)
        elif ch == curses.KEY_RIGHT:
            self.cursor = min(len(self.input_buf), self.cursor + 1)
        elif ch == curses.KEY_HOME:
            self.cursor = 0
        elif ch == curses.KEY_END:
            self.cursor = len(self.input_buf)

        # History navigation (↑/↓ in input box)
        elif ch == curses.KEY_UP:
            if not self.history:
                pass
            elif self.history_idx == -1:
                # Start browsing — save current draft
                self.history_draft = "".join(self.input_buf)
                self.history_idx = len(self.history) - 1
                self._set_input(self.history[self.history_idx])
            elif self.history_idx > 0:
                self.history_idx -= 1
                self._set_input(self.history[self.history_idx])
        elif ch == curses.KEY_DOWN:
            if self.history_idx == -1:
                pass
            elif self.history_idx < len(self.history) - 1:
                self.history_idx += 1
                self._set_input(self.history[self.history_idx])
            else:
                # Back to draft
                self.history_idx = -1
                self._set_input(self.history_draft)
                self.history_draft = ""

        # Scroll chat (Page Up / Page Down)
        elif ch == curses.KEY_PPAGE:
            self.scroll += max(1, self.chat_h - 4)
        elif ch == curses.KEY_NPAGE:
            self.scroll = max(0, self.scroll - max(1, self.chat_h - 4))

        # Printable characters
        elif 32 <= ch <= 126:
            self.input_buf.insert(self.cursor, chr(ch))
            self.cursor += 1

    # ------------------------------------------------------------------
    # Main event loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        self.draw_all()
        while True:
            ch = self.stdscr.getch()
            if ch != -1:
                self._handle_key(ch)
            # Drain incoming messages from background threads
            try:
                while True:
                    item = self.inbox.get_nowait()
                    sender = item[0]
                    text   = item[1]
                    if sender == "system_event":
                        self._system(text)
                    elif sender == "__channel_join__":
                        ch_name = text
                        if ch_name not in self.channels:
                            self.channels[ch_name] = Channel(name=ch_name, members=[self.handle])
                    else:
                        channel = item[2] if len(item) > 2 else ""
                        # Reject reserved or navigation-looking channel names
                        if channel and (
                            channel.lower() in RESERVED_CHANNELS
                            or channel.startswith((".", "/"))
                        ):
                            continue
                        # Drop channel messages for channels we're not in
                        if channel and channel not in self.channels:
                            continue
                        self._chat(sender, text, channel=channel)
            except queue.Empty:
                pass
            self.draw_all()


# ---------------------------------------------------------------------------
# Entry points called from __main__.py
# ---------------------------------------------------------------------------
def _too_small(stdscr: curses.window) -> None:
    stdscr.clear()
    try:
        stdscr.addstr(0, 0, f"Terminal too small — need {MIN_COLS}x{MIN_ROWS}")
    except curses.error:
        pass
    stdscr.refresh()
    stdscr.getch()


def _net_thread(ui: UI, args, stop: threading.Event) -> None:
    """Asyncio network loop — runs in a background thread.

    Handles a single peer connection (client or server side).
    Bridges the asyncio world with the curses UI via inbox/outbox queues.
    """
    import asyncio
    from ezchat.crypto.keys import load_or_create_identity
    from ezchat.net.connection import connect_to_peer, accept_peer

    handle   = getattr(args, "handle", None) or "you"
    identity = load_or_create_identity(handle)

    async def _run() -> None:
        conn: object = None
        try:
            if getattr(args, "connect", None):
                # Client mode
                raw = args.connect
                host, _, port_s = raw.rpartition(":")
                host = host or "127.0.0.1"
                port = int(port_s) if port_s.isdigit() else 9000
                ui.inbox.put(("system_event", f"connecting to {host}:{port}…"))
                conn = await connect_to_peer(host, port, identity)
            elif getattr(args, "listen", None):
                # Server mode — wait for first peer
                port = args.listen
                ui.inbox.put(("system_event", f"listening on port {port}…"))
                future: asyncio.Future = asyncio.get_event_loop().create_future()

                async def _on_accept(r, w):
                    c = await accept_peer(r, w, identity)
                    future.set_result(c)

                server = await asyncio.start_server(_on_accept, "0.0.0.0", port)
                async with server:
                    conn = await future
            else:
                return  # no network args, nothing to do

            # Announce peer joined
            ui.inbox.put(("system_event", f"connected: {conn.peer_handle}"))
            ui.peers.append((conn.peer_handle, True))
            ui.active_peer = conn.peer_handle

            # Pump: send outbox messages, receive inbox messages
            async def _send_loop():
                loop = asyncio.get_event_loop()
                while not stop.is_set():
                    try:
                        item = await loop.run_in_executor(
                            None, lambda: ui.outbox.get(timeout=0.1)
                        )
                        peer, text = item[0], item[1]
                        channel    = item[2] if len(item) > 2 else ""
                        # For channel messages, only send to peers in that channel
                        if channel:
                            ch = ui.channels.get(channel)
                            if not ch or conn.peer_handle not in ch.members:
                                continue
                        await conn.send(text, channel=channel)
                    except Exception:
                        pass

            send_task = asyncio.create_task(_send_loop())
            try:
                while not stop.is_set():
                    frame = await conn.recv()
                    if frame is None:
                        break
                    text    = frame.get("text", "")
                    channel = frame.get("channel", "")
                    if text.startswith("\x00channel_invite\x00"):
                        ch_name = text.split("\x00")[2]
                        ui.inbox.put(("system_event", f"invited to #{ch_name} by {conn.peer_handle}"))
                        ui.inbox.put(("__channel_join__", ch_name))
                    else:
                        ui.inbox.put((conn.peer_handle, text, channel))
            finally:
                send_task.cancel()
                await conn.close()
                ui.inbox.put(("system_event", f"disconnected: {conn.peer_handle}"))
                ui.peers = [(h, False if h == conn.peer_handle else on)
                            for h, on in ui.peers]

        except Exception as exc:
            ui.inbox.put(("system_event", f"network error: {exc}"))

    asyncio.run(_run())


def _curses_main(stdscr: curses.window, args) -> None:  # noqa: ANN001
    rows, cols = stdscr.getmaxyx()
    if rows < MIN_ROWS or cols < MIN_COLS:
        _too_small(stdscr)
        return

    theme_name = getattr(args, "theme", None) or "phosphor_green"
    try:
        theme = set_theme(theme_name)
    except ValueError:
        theme = set_theme("phosphor_green")

    handle = getattr(args, "handle", None) or "you"
    ui = UI(stdscr, theme, handle=handle)

    # Start network thread if connect/listen args are present
    stop = threading.Event()
    if getattr(args, "connect", None) or getattr(args, "listen", None):
        net = threading.Thread(target=_net_thread, args=(ui, args, stop), daemon=True)
        net.start()

    try:
        ui.run()
    finally:
        stop.set()


def run(args) -> None:  # noqa: ANN001
    """Launch the full curses UI."""
    curses.wrapper(_curses_main, args)


_TEST_PEERS = ["alice", "bob", "carol", "dave"]

_TEST_MESSAGES = [
    "hey, you there?",
    "just pushed the new build",
    "anyone seen the latency numbers?",
    "lgtm, merging",
    "hold on, tests are still running",
    "can someone review my PR?",
    "coffee run, back in 10",
    "the staging deploy failed again 😤",
    "fixed it, bad env var",
    "who broke the CI??",
    "not me this time 🙋",
    "stand-up in 5",
    "can we push the meeting?",
    "sure, 30 min?",
    "works for me",
    "heads up — server reboot at noon",
    "ack",
    "on it",
    "ping",
    "pong",
    "this is fine 🔥",
    "new issue just dropped",
    "reproducing now",
    "confirmed, filing a bug",
    "got a sec to pair on this?",
    "almost done, 2 more tests to fix",
    "shipping it",
    "nice work everyone",
]


def _test_sim_thread(ui: UI, stop: threading.Event) -> None:
    """Background thread: fake peers come online, respond to invites, trade messages."""
    import random

    # Track which channels each sim peer has joined: {peer: {ch_name}}
    peer_channels: dict[str, set] = {name: set() for name in _TEST_PEERS}
    next_random_msg = time.monotonic() + random.uniform(4.0, 10.0)

    # Stagger peers coming online over the first few seconds
    for i, name in enumerate(_TEST_PEERS):
        if stop.is_set():
            return
        time.sleep(0.8 + i * 0.5)
        ui.peers.append((name, True))
        ui.inbox.put((name, f"hey {ui.handle} 👋"))

    # Short-tick main loop so we react quickly to invites and user messages
    while not stop.is_set():
        stop.wait(0.2)
        if stop.is_set():
            break

        # --- Drain outbox: handle channel invites ---
        drained = []
        try:
            while True:
                drained.append(ui.outbox.get_nowait())
        except queue.Empty:
            pass

        for item in drained:
            peer    = item[0]
            text    = item[1]
            channel = item[2] if len(item) > 2 else ""
            if text.startswith("\x00channel_invite\x00") and peer in peer_channels:
                ch_name = text.split("\x00")[2]
                peer_channels[peer].add(ch_name)
                if ch_name in ui.channels:
                    ch = ui.channels[ch_name]
                    if peer not in ch.members:
                        ch.members.append(peer)
                ui.inbox.put((peer, f"joined #{ch_name} 👋", ch_name))

        # --- Drain sim_inbox: ack user channel messages ---
        if ui.sim_inbox is not None:
            try:
                while True:
                    ch_name, user_text = ui.sim_inbox.get_nowait()
                    _log.debug("sim thread got sim_inbox ch=%r text=%r peer_channels=%r", ch_name, user_text, {p: list(c) for p,c in peer_channels.items()})
                    for peer, chans in peer_channels.items():
                        if ch_name in chans:
                            acks = [
                                f"[ack] {user_text}",
                                "👍",
                                "got it",
                                "noted",
                                "on it",
                                f"re: {user_text[:30]}",
                            ]
                            # Small stagger so peers don't all reply at once
                            delay = random.uniform(0.3, 1.5)
                            t = threading.Timer(
                                delay,
                                lambda p=peer, a=random.choice(acks), c=ch_name:
                                    ui.inbox.put((p, a, c))
                            )
                            t.daemon = True
                            t.start()
            except queue.Empty:
                pass

        # --- Periodic random message ---
        if time.monotonic() >= next_random_msg:
            next_random_msg = time.monotonic() + random.uniform(4.0, 10.0)
            sender = random.choice(_TEST_PEERS)
            text   = random.choice(_TEST_MESSAGES)
            my_channels = list(peer_channels[sender])
            if my_channels and random.random() < 0.6:
                ui.inbox.put((sender, text, random.choice(my_channels)))
            else:
                ui.inbox.put((sender, text, ""))


def _test_curses_main(stdscr: curses.window, args) -> None:  # noqa: ANN001
    import random

    rows, cols = stdscr.getmaxyx()
    if rows < MIN_ROWS or cols < MIN_COLS:
        _too_small(stdscr)
        return

    theme_name = getattr(args, "theme", None) or "phosphor_green"
    try:
        theme = set_theme(theme_name)
    except ValueError:
        theme = set_theme("phosphor_green")

    handle = getattr(args, "handle", None) or "you"
    ui = UI(stdscr, theme, handle=handle)
    ui._system("test mode — simulated peers will appear shortly")

    # Echo bot: reply to direct messages only (channel acks handled by sim peers)
    original_chat = ui._chat.__func__  # type: ignore[attr-defined]

    def _echo(self: UI, sender: str, text: str, channel: str = "") -> None:
        original_chat(self, sender, text, channel=channel)
        if sender == self.handle and self.active_peer and not channel:
            replies = [
                f"got it: \"{text}\"",
                "👍",
                "on it",
                "ack",
                "noted",
                f"re: {text[:30]} — sounds good",
            ]
            reply = random.choice(replies)
            self.inbox.put((self.active_peer, reply, ""))

    ui._chat = lambda sender, text, channel="": _echo(ui, sender, text, channel=channel)  # type: ignore[method-assign]

    ui.sim_inbox = queue.Queue()

    stop = threading.Event()
    sim  = threading.Thread(target=_test_sim_thread, args=(ui, stop), daemon=True)
    sim.start()

    try:
        ui.run()
    finally:
        stop.set()


def run_test_mode(args) -> None:  # noqa: ANN001
    """Run in loopback test mode with simulated peers."""
    curses.wrapper(_test_curses_main, args)
