"""ezchat curses UI — orchestrator.

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
import logging
import queue
import threading
from datetime import datetime

from ezchat import store as _store
from ezchat.ui.draw import DrawMixin
from ezchat.ui.input_handler import InputMixin
from ezchat.ui.models import (
    PRESENCE_W, INPUT_H, STATUS_H, MIN_COLS, MIN_ROWS,
    SCRATCH_PEER, RESERVED_CHANNELS,
    Channel, Message, too_small,
)
from ezchat.ui.net_thread import net_thread
from ezchat.ui.theme import Theme, set_theme
from ezchat.ui.test_sim import run_test_mode  # re-export for __main__

_log = logging.getLogger(__name__)

__all__ = ["UI", "run", "run_test_mode"]


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
class UI(DrawMixin, InputMixin):
    """Manages all curses windows and the main event loop."""

    def __init__(
        self,
        stdscr:   curses.window,
        theme:    Theme,
        handle:   str = "you",
        identity  = None,   # ezchat.crypto.keys.Identity | None
    ) -> None:
        self.stdscr   = stdscr
        self.theme    = theme
        self.handle   = handle
        self.identity = identity

        self.messages:  list[Message]              = []
        self.scroll:    int                        = 0
        self.input_buf: list[str]                  = []
        self.cursor:    int                        = 0

        self.history:       list[str] = []
        self.history_idx:   int       = -1
        self.history_draft: str       = ""

        self.peers:    list[tuple[str, bool]] = []
        self.channels: dict[str, Channel]     = {}

        self.focus:       str = "input"
        self.peer_cursor: int = 0
        self.active_peer: str = ""
        self.view:        str = "top"

        self.unread: dict[str, int] = {}
        # Per-conversation AI message history for multi-turn context
        self._ai_history: dict[str, list[dict]] = {}

        self.inbox:     queue.Queue = queue.Queue()
        self.outbox:    queue.Queue = queue.Queue()
        self.sim_inbox: queue.Queue | None = None

        self._setup_curses()
        self._create_windows()
        self._post_init()

    # ------------------------------------------------------------------
    # Curses setup
    # ------------------------------------------------------------------
    def _setup_curses(self) -> None:
        curses.curs_set(1)
        curses.start_color()
        curses.use_default_colors()
        self.theme.activate()
        self.stdscr.keypad(True)
        self.stdscr.timeout(100)
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)

    def _post_init(self) -> None:
        self._load_state()
        self._system("Welcome to ezchat  |  type /help for commands")

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------
    def _load_state(self) -> None:
        for ch_name, members in _store.load_channels().items():
            self.channels[ch_name] = Channel(name=ch_name, members=list(members))

        for handle in _store.load_peers():
            if handle == self.handle:
                continue
            if not any(h == handle for h, _ in self.peers):
                self.peers.append((handle, False))

        saved = _store.load_cmd_history()
        if saved:
            self.history = saved


    def save_state(self) -> None:
        _store.save_channels({name: ch.members for name, ch in self.channels.items()})
        _store.save_cmd_history(self.history)

    # ------------------------------------------------------------------
    # Window geometry
    # ------------------------------------------------------------------
    def _create_windows(self) -> None:
        rows, cols = self.stdscr.getmaxyx()
        self.rows, self.cols = rows, cols
        pane_h = max(1, rows - INPUT_H - STATUS_H)
        chat_w = max(1, cols - PRESENCE_W)
        self.pw = curses.newwin(pane_h, PRESENCE_W, 0, 0)
        self.cw = curses.newwin(pane_h, chat_w,     0, PRESENCE_W)
        self.sw = curses.newwin(STATUS_H, cols,     pane_h, 0)
        self.iw = curses.newwin(INPUT_H,  cols,     pane_h + STATUS_H, 0)
        self.chat_w = chat_w
        self.chat_h = pane_h
        self.pane_h = pane_h

    def _resize(self) -> None:
        curses.update_lines_cols()
        rows, cols = curses.LINES, curses.COLS
        if rows == self.rows and cols == self.cols:
            return
        self.stdscr.clear()
        self.rows, self.cols = rows, cols
        pane_h = max(1, rows - INPUT_H - STATUS_H)
        chat_w = max(1, cols - PRESENCE_W)
        self.pw.resize(pane_h, PRESENCE_W); self.pw.mvwin(0, 0)
        self.cw.resize(pane_h, chat_w);     self.cw.mvwin(0, PRESENCE_W)
        self.sw.resize(STATUS_H, cols);     self.sw.mvwin(pane_h, 0)
        self.iw.resize(INPUT_H, cols);      self.iw.mvwin(pane_h + STATUS_H, 0)
        self.chat_w = chat_w
        self.chat_h = pane_h
        self.pane_h = pane_h

    # ------------------------------------------------------------------
    # Message helpers
    # ------------------------------------------------------------------
    def _now(self) -> tuple[str, str]:
        now = datetime.now()
        return now.strftime("%H:%M"), now.strftime("%Y-%m-%d")

    def _system(self, text: str) -> None:
        ts, date = self._now()
        self.messages.append(Message(ts, "system", text, "system", date=date))

    def _error(self, text: str) -> None:
        ts, date = self._now()
        self.messages.append(Message(ts, "system", text, "error", date=date))

    def _chat(self, sender: str, text: str, channel: str = "", convo: str = "") -> None:
        ts, date = self._now()
        if not convo:
            convo = f"#{channel}" if channel else (
                self.active_peer if sender == self.handle else sender
            )
        self.messages.append(Message(ts, sender, text, "chat", peer=convo, date=date))
        if sender != self.handle and convo != self.active_peer:
            self.unread[convo] = self.unread.get(convo, 0) + 1
        if sender == self.handle and convo == SCRATCH_PEER and self.identity:
            full_ts = _store.now_ts()
            sig = _store.sign_message(self.identity.private_key, full_ts, sender, text)
            _store.append_message(SCRATCH_PEER, full_ts, sender, text, sig)
        if channel and sender == self.handle and self.sim_inbox is not None:
            _log.debug("sim_inbox.put channel=%r text=%r", channel, text)
            self.sim_inbox.put((channel, text))

    # ------------------------------------------------------------------
    # Main event loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        self.draw_all()
        while True:
            ch = self.stdscr.getch()
            if ch != -1:
                self._handle_key(ch)
            self._drain_inbox()
            self.draw_all()

    def _drain_inbox(self) -> None:
        try:
            while True:
                item   = self.inbox.get_nowait()
                sender = item[0]
                text   = item[1]

                if sender == "system_event":
                    self._system(text)

                elif sender == "__ai_response__":
                    ai_peer, ai_channel, ai_prompt = item[2], item[3], item[4]
                    convo   = f"#{ai_channel}" if ai_channel else ai_peer
                    history = self._ai_history.setdefault(convo, [])
                    history.append({"role": "user",      "content": f"[{self.handle}]: {ai_prompt}"})
                    history.append({"role": "assistant", "content": text})
                    q_sender = f"{self.handle} → ai"
                    a_sender = "ai"
                    self._chat(q_sender, ai_prompt, channel=ai_channel, convo=convo)
                    self._chat(a_sender, text,      channel=ai_channel, convo=convo)
                    if ai_peer and ai_peer != SCRATCH_PEER:
                        self.outbox.put((ai_peer, f"\x00ai:q\x00{ai_prompt}", ai_channel))
                        self.outbox.put((ai_peer, f"\x00ai:a\x00{text}",      ai_channel))

                elif sender == "__peer_online__":
                    if not any(h == text for h, _ in self.peers):
                        self.peers.append((text, True))
                    else:
                        self.peers = [(h, True if h == text else on)
                                      for h, on in self.peers]

                elif sender == "__peer_offline__":
                    self.peers = [(h, False if h == text else on)
                                  for h, on in self.peers]

                elif sender == "__channel_join__":
                    if text not in self.channels:
                        self.channels[text] = Channel(name=text, members=[self.handle])

                else:
                    channel = item[2] if len(item) > 2 else ""
                    if channel and (
                        channel.lower() in RESERVED_CHANNELS
                        or channel.startswith((".", "/"))
                    ):
                        continue
                    if channel and channel not in self.channels:
                        continue
                    convo   = f"#{channel}" if channel else sender
                    history = self._ai_history.setdefault(convo, [])
                    if text.startswith("\x00ai:q\x00"):
                        prompt = text[6:]
                        history.append({"role": "user", "content": f"[{sender}]: {prompt}"})
                        self._chat(f"{sender} → ai", prompt, channel=channel, convo=convo)
                    elif text.startswith("\x00ai:a\x00"):
                        response = text[6:]
                        history.append({"role": "assistant", "content": response})
                        self._chat("ai", response, channel=channel, convo=convo)
                    else:
                        self._chat(sender, text, channel=channel)

        except queue.Empty:
            pass


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------
def _curses_main(stdscr: curses.window, args) -> None:
    rows, cols = stdscr.getmaxyx()
    if rows < MIN_ROWS or cols < MIN_COLS:
        too_small(stdscr)
        return

    from ezchat.ai.config import load_ui_config
    ui_cfg = load_ui_config()

    theme_name = getattr(args, "theme", None) or ui_cfg.theme or "phosphor_green"
    try:
        theme = set_theme(theme_name)
    except ValueError:
        theme = set_theme("phosphor_green")

    handle = getattr(args, "handle", None) or ui_cfg.handle or "you"
    from ezchat.crypto.keys import load_or_create_identity
    identity = load_or_create_identity(handle)

    # Apply config defaults for server URL if not provided on CLI
    if not getattr(args, "server", None) and ui_cfg.server:
        args.server = ui_cfg.server

    ui   = UI(stdscr, theme, handle=handle, identity=identity)
    stop = threading.Event()
    if getattr(args, "connect", None) or getattr(args, "listen", None):
        net = threading.Thread(target=net_thread, args=(ui, args, stop), daemon=True)
        net.start()

    try:
        ui.run()
    finally:
        stop.set()
        ui.save_state()


def run(args) -> None:
    """Launch the full curses UI."""
    curses.wrapper(_curses_main, args)
