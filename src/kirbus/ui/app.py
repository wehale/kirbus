"""kirbus curses UI — orchestrator.

Layout
------
┌────────────────────┬────────────────────────────────────────┐
│  PRESENCE  (20 ch) │  CHAT                                  │
│                    │                                        │
│  ● you             │  [12:34] system: Welcome to kirbus     │
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

from kirbus import store as _store
from kirbus.ui.draw import DrawMixin
from kirbus.ui.input_handler import InputMixin
from kirbus.ui.models import (
    PRESENCE_W, INPUT_H, STATUS_H, MIN_COLS, MIN_ROWS,
    SCRATCH_PEER, RESERVED_CHANNELS,
    Channel, Message, AgentMenu, AgentEntry, too_small,
)
from kirbus.ui.net_thread import net_thread
from kirbus.ui.theme import Theme, set_theme
from kirbus.ui.test_sim import run_test_mode  # re-export for __main__

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
        identity  = None,   # kirbus.crypto.keys.Identity | None
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

        self.peers:             list[tuple[str, bool]] = []
        self.channels:          dict[str, Channel]     = {}
        self.agent_peers:       set[str]               = set()
        self.peer_fingerprints: dict[str, str]         = {}
        self.peer_key_status:   dict[str, str]         = {}
        self.blocked_peers:     set[str]               = set()

        self.focus:       str = "input"
        self.peer_cursor: int = 0
        self.active_peer: str = ""
        self.view:        str = "top"

        self.unread: dict[str, int] = {}
        # Per-conversation AI message history for multi-turn context
        self._ai_history: dict[str, list[dict]] = {}

        # Registry / server selection state
        self.registry_servers: list[dict] = []   # [{name, description, access, online_count, url}]
        self.connected_server: str = ""          # name of the server we're connected to
        self.is_su: bool = False                 # whether we have su role

        # Agent menu state
        self.agent_menus: dict[str, AgentMenu] = {}     # agent_handle → menu (persisted)
        self.agent_menu: AgentMenu | None = None        # currently active menu (if viewing one)
        self.agent_session: str = ""                     # active session key (e.g. "zork")
        self.agent_picking_peer: str = ""                # entry key when picking a multiplayer opponent
        self._pending_game_invite: dict | None = None    # incoming multiplayer invite

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
        self._system("Welcome to kirbus  |  type /help for commands")

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------
    def _load_state(self) -> None:
        for ch_name, members in _store.load_channels().items():
            self.channels[ch_name] = Channel(name=ch_name, members=list(members))

        peer_records = _store.load_peers()
        for handle, rec in peer_records.items():
            if handle == self.handle:
                continue
            if not any(h == handle for h, _ in self.peers):
                self.peers.append((handle, False))
            if rec.blocked:
                self.blocked_peers.add(handle)

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

    def _show_trophy(self, text: str) -> None:
        ts, date = self._now()
        w = max(len(text) + 6, 40)
        bar = "=" * (w - 2)
        pad_text = f"  {text}  ".center(w - 2)
        lines = [
            "",
            f"+{bar}+",
            f"|{'  *** UNLOCKED ***  '.center(w - 2)}|",
            f"+{bar}+",
            f"|{pad_text}|",
            f"+{bar}+",
            "",
        ]
        for line in lines:
            self.messages.append(Message(ts, "system", line, "trophy", date=date))

    @staticmethod
    def _detect_preformatted(text: str) -> bool:
        """Return True if text looks like preformatted content (game boards, ASCII art)."""
        if "\n" not in text:
            return False
        # Box-drawing characters are a strong signal.
        _BOX = set("─│┼┌┐└┘├┤┬┴╔╗╚╝═║╭╮╰╯")
        return any(ch in _BOX for ch in text)

    def _chat(self, sender: str, text: str, channel: str = "", convo: str = "") -> None:
        ts, date = self._now()
        if not convo:
            convo = f"#{channel}" if channel else (
                self.active_peer if sender == self.handle else sender
            )
        kind = "preformatted" if self._detect_preformatted(text) else "chat"
        self.messages.append(Message(ts, sender, text, kind, peer=convo, date=date))
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
                    fp         = item[2] if len(item) > 2 else ""
                    key_status = item[3] if len(item) > 3 else "known"
                    if fp:
                        self.peer_fingerprints[text] = fp
                    # Don't downgrade "new"/"changed" to "known" on reconnect
                    prev = self.peer_key_status.get(text)
                    if prev not in ("new", "changed") or key_status != "known":
                        self.peer_key_status[text] = key_status
                    if text not in self.agent_peers:
                        if not any(h == text for h, _ in self.peers):
                            self.peers.append((text, True))
                        else:
                            self.peers = [(h, True if h == text else on)
                                          for h, on in self.peers]

                elif sender == "__peer_offline__":
                    self.peers = [(h, False if h == text else on)
                                  for h, on in self.peers]
                    # Remove channels where this peer was the only non-local member
                    to_remove = [
                        name for name, ch in self.channels.items()
                        if text in ch.members
                        and all(m == self.handle or m == text for m in ch.members)
                    ]
                    for name in to_remove:
                        del self.channels[name]
                        if self.view == name:
                            self.view = "top"
                            self.active_peer = ""
                            self.scroll = 0

                elif sender == "__registry_servers__":
                    # text is the server list from the registry
                    self.registry_servers = item[2] if len(item) > 2 else []
                    # Silently update the server list in the sidebar

                elif sender == "__server_connected__":
                    self.connected_server = text
                    self._system(f"Connected to server: {text}")

                elif sender == "__secret_message__":
                    self._show_trophy(text)

                elif sender == "__su_granted__":
                    self.is_su = True
                    self._system("Superuser access granted")

                elif sender == "__peer_is_agent__":
                    self.agent_peers.add(text)
                    self.peers = [(h, on) for h, on in self.peers if h != text]

                elif sender == "__agent_menu__":
                    import json
                    agent_handle = text
                    data = json.loads(item[2])
                    entries = [
                        AgentEntry(key=e["key"], label=e["label"],
                                   type=e.get("type", "single"))
                        for e in data.get("entries", [])
                    ]
                    menu = AgentMenu(
                        title=data.get("title", agent_handle),
                        entries=entries,
                        agent=agent_handle,
                    )
                    self.agent_menus[agent_handle] = menu
                    # Don't auto-switch — just store the menu.
                    # User enters via ▸ games in the sidebar.

                elif sender == "__agent_session__":
                    import json
                    data = json.loads(item[2])
                    state = data.get("state", "")
                    if state == "started":
                        self.agent_session = data.get("key", "")
                        self.agent_picking_peer = ""
                    elif state == "ended":
                        self.agent_session = ""
                        self.agent_picking_peer = ""

                elif sender == "__game_invite__":
                    import json
                    agent_handle = text
                    data = json.loads(item[2])
                    game_name = data.get("game", "")
                    from_peer = data.get("from", "")
                    invite_id = data.get("invite_id", "")
                    self._system(
                        f"{from_peer} challenges you to {game_name}! "
                        f"Type /accept-game to play or /decline-game to decline."
                    )
                    self._pending_game_invite = {
                        "agent": agent_handle,
                        "game": game_name,
                        "from": from_peer,
                        "invite_id": invite_id,
                    }

                elif sender == "__channel_join__":
                    inviter = item[2] if len(item) > 2 else None
                    if text not in self.channels:
                        members = [self.handle]
                        if inviter and inviter not in members:
                            members.append(inviter)
                        self.channels[text] = Channel(name=text, members=members)
                    elif inviter and inviter not in self.channels[text].members:
                        self.channels[text].members.append(inviter)

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

    from kirbus.ai.config import load_ui_config
    ui_cfg = load_ui_config()

    theme_name = getattr(args, "theme", None) or ui_cfg.theme or "ansi_bbs"
    try:
        theme = set_theme(theme_name)
    except ValueError:
        theme = set_theme("ansi_bbs")

    handle = getattr(args, "handle", None) or ui_cfg.handle or "you"
    from kirbus.home import set_handle
    set_handle(handle)
    from kirbus.crypto.keys import load_or_create_identity
    identity = load_or_create_identity(handle)

    # Apply config defaults for server URL if not provided on CLI
    if not getattr(args, "server", None) and ui_cfg.server:
        args.server = ui_cfg.server

    # Resolve registry URL
    registry_arg = getattr(args, "registry", None)
    if registry_arg and registry_arg.lower() == "none":
        args._registry_url = None
    elif registry_arg:
        args._registry_url = registry_arg
    elif ui_cfg.registry:
        args._registry_url = ui_cfg.registry
    elif not getattr(args, "server", None) and not getattr(args, "connect", None) and not getattr(args, "listen", None):
        # No explicit connection args — use default registry
        from kirbus.net.registry_client import DEFAULT_REGISTRY
        args._registry_url = DEFAULT_REGISTRY
    else:
        args._registry_url = None

    ui   = UI(stdscr, theme, handle=handle, identity=identity)
    stop = threading.Event()
    has_connection = getattr(args, "connect", None) or getattr(args, "listen", None) or getattr(args, "server", None)
    has_registry = getattr(args, "_registry_url", None)
    if has_connection or has_registry:
        net = threading.Thread(target=net_thread, args=(ui, args, stop), daemon=True)
        net.start()

    try:
        ui.run()
    finally:
        stop.set()
        ui.save_state()


def run(args) -> None:
    """Launch the full curses UI."""
    _handle_encrypt_history(args)
    curses.wrapper(_curses_main, args)


def _handle_encrypt_history(args) -> None:
    """Handle --encrypt-history / --no-encrypt-history before curses starts."""
    import getpass
    from kirbus.ai.config import load_ui_config
    from kirbus.home import get_home
    from kirbus.store.crypto_history import (
        init_encryption, salt_path, encrypt_file, decrypt_file,
    )

    ui_cfg = load_ui_config()
    want_encrypt = getattr(args, "encrypt_history", False)
    want_decrypt = getattr(args, "no_encrypt_history", False)
    has_salt = salt_path(get_home()).exists()
    enabled = want_encrypt or (ui_cfg.encrypt_history and not want_decrypt) or has_salt

    if want_decrypt and has_salt:
        # Decrypt all history and disable
        passphrase = getpass.getpass("History passphrase (to decrypt): ")
        if not init_encryption(passphrase, get_home()):
            print("Wrong passphrase. Cannot decrypt.")
            raise SystemExit(1)
        history_dir = get_home() / "history"
        if history_dir.exists():
            for f in history_dir.glob("*.log"):
                decrypt_file(f)
        salt_path(get_home()).unlink(missing_ok=True)
        from kirbus.store.crypto_history import _verify_path
        _verify_path(get_home()).unlink(missing_ok=True)
        print("History decrypted. Encryption disabled.")
        return

    if not enabled:
        return

    if not has_salt and want_encrypt:
        # First time — set passphrase
        passphrase = getpass.getpass("Set history passphrase: ")
        confirm = getpass.getpass("Confirm passphrase: ")
        if passphrase != confirm:
            print("Passphrases don't match. Encryption not enabled.")
            raise SystemExit(1)
        init_encryption(passphrase, get_home())
        # Encrypt existing history
        history_dir = get_home() / "history"
        if history_dir.exists():
            for f in history_dir.glob("*.log"):
                encrypt_file(f)
        print("History encryption enabled.")
    else:
        # Existing salt — prompt for passphrase with retries
        attempts = 0
        while True:
            passphrase = getpass.getpass("History passphrase: ")
            if init_encryption(passphrase, get_home()):
                break
            attempts += 1
            if attempts >= 3:
                print("3 failed attempts. Type RESET to wipe encrypted history and start fresh.")
                print("This will permanently delete all encrypted chat logs.")
                ans = input("> ").strip()
                if ans == "RESET":
                    history_dir = get_home() / "history"
                    if history_dir.exists():
                        for f in history_dir.glob("*.log"):
                            f.unlink()
                    salt_path(get_home()).unlink(missing_ok=True)
                    from kirbus.store.crypto_history import _verify_path
                    _verify_path(get_home()).unlink(missing_ok=True)
                    print("History wiped. Set a new passphrase.")
                    passphrase = getpass.getpass("Set history passphrase: ")
                    confirm = getpass.getpass("Confirm passphrase: ")
                    if passphrase != confirm:
                        print("Passphrases don't match. Starting without encryption.")
                        return
                    init_encryption(passphrase, get_home())
                    print("History encryption enabled.")
                    return
                attempts = 0
            print("Wrong passphrase. Try again, or Ctrl-C to quit.")
