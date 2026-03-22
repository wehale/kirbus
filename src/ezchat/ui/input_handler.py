"""InputMixin — key handling and command routing for the ezchat UI."""
from __future__ import annotations

import curses
import threading

from ezchat.ui.models import SCRATCH_PEER, BACK_ENTRY, RESERVED_CHANNELS
from ezchat.ui.theme import list_themes, set_theme


class InputMixin:
    """Key handling and slash-command routing mixed into UI.

    Relies on state and helpers provided by UI and DrawMixin:
        self.focus, self.peer_cursor, self.peers, self.history,
        self.history_idx, self.history_draft, self.input_buf, self.cursor,
        self.scroll, self.active_peer, self.view, self.channels, self.unread,
        self.theme, self.handle, self.inbox, self.outbox, self.messages,
        self.chat_h, self._system(), self._error(), self._chat(),
        self._presence_rows(), self._resize()
    """

    _HELP = """\
/help                        show this message
/theme <name>                switch theme
/themes                      list available themes
/ai <prompt>                 ask the AI; response sent to current conversation
/ai-peer                     forward the last peer message to the AI
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

    # ------------------------------------------------------------------
    # Input helpers
    # ------------------------------------------------------------------
    def _set_input(self, text: str) -> None:
        self.input_buf = list(text)
        self.cursor    = len(self.input_buf)

    # ------------------------------------------------------------------
    # Command routing
    # ------------------------------------------------------------------
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

        elif cmd == "/ai-peer":
            channel    = self.view if self.view != "top" else ""
            convo      = f"#{channel}" if channel else self.active_peer
            peer_name  = self.active_peer if not channel else None
            # Find the last message from someone other than us in this conversation
            last = next(
                (m for m in reversed(self.messages)
                 if m.peer == (convo if convo else "")
                 and m.sender != self.handle
                 and m.kind == "chat"
                 and not m.sender.endswith("→ ai")
                 and m.sender != "ai"),
                None,
            )
            if not last:
                self._error("No peer message found in current conversation")
                return
            prompt = f"[{last.sender}]: {last.text}"
            # Reuse /ai logic
            self._handle_command(f"/ai {prompt}")
            return

        elif cmd == "/ai":
            if not arg:
                self._error("Usage: /ai <prompt>")
                return
            self._system("AI: thinking…")
            active_peer = self.active_peer
            channel     = self.view if self.view != "top" else ""
            convo       = f"#{channel}" if channel else active_peer
            history     = list(self._ai_history.get(convo, []))

            def _ai_call() -> None:
                try:
                    from ezchat.ai import ask
                    text = ask(arg, history=history)
                except Exception as exc:
                    import traceback
                    self.inbox.put(("system_event", f"AI error: {type(exc).__name__}: {exc}"))
                    self.inbox.put(("system_event", traceback.format_exc().splitlines()[-1]))
                    return
                self.inbox.put(("__ai_response__", text, active_peer, channel, arg))

            threading.Thread(target=_ai_call, daemon=True).start()

        else:
            self._error(f"Unknown command: {cmd}  (type /help for commands)")

    def _handle_channel_command(self, arg: str) -> None:
        from ezchat.ui.models import Channel, RESERVED_CHANNELS
        parts  = arg.strip().split(maxsplit=2)
        sub    = parts[0].lower() if parts else ""
        name   = parts[1] if len(parts) > 1 else ""
        extra  = parts[2] if len(parts) > 2 else ""

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
                self.view        = "top"
            self._system(f"Left channel #{name}")

        else:
            self._error("Usage: /channel create|join|invite|leave ...")

    # ------------------------------------------------------------------
    # Key handling
    # ------------------------------------------------------------------
    def _handle_key(self, ch: int) -> None:
        if ch == curses.KEY_RESIZE:
            self._resize()
            return

        if ch == curses.KEY_MOUSE:
            try:
                _, _mx, _my, _mz, bstate = curses.getmouse()
                step = max(1, self.chat_h - 4)
                if bstate & curses.BUTTON4_PRESSED:   # scroll up
                    self.scroll += step
                elif bstate & curses.BUTTON5_PRESSED:  # scroll down
                    self.scroll = max(0, self.scroll - step)
            except curses.error:
                pass
            return

        if ch == ord("\t"):
            if self.focus == "input":
                self.focus       = "presence"
                self.peer_cursor = max(0, min(self.peer_cursor, len(self.peers) - 1))
                curses.curs_set(0)
            else:
                self.focus = "input"
                curses.curs_set(1)
            return

        if ch == 27:
            self.focus = "input"
            curses.curs_set(1)
            return

        if self.focus == "presence":
            rows       = self._presence_rows()
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
                    self.view        = "top"
                    self.peer_cursor = 0
                elif key.startswith("#"):
                    self.view        = key[1:]
                    self.active_peer = key
                    self.unread.pop(key, None)
                    self.peer_cursor = 0
                    self.focus       = "input"
                    curses.curs_set(1)
                else:
                    self.active_peer = key
                    self.unread.pop(key, None)
                    if key != SCRATCH_PEER:
                        self._system(f"Now chatting with {label}")
                    self.focus = "input"
                    curses.curs_set(1)
            return

        # Input-focused keys
        if ch in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            text = "".join(self.input_buf).strip()
            self.input_buf.clear()
            self.cursor       = 0
            self.scroll       = 0
            self.history_idx  = -1
            self.history_draft = ""
            if not text:
                return
            if not self.history or self.history[-1] != text:
                self.history.append(text)
            if text.startswith("/"):
                self._handle_command(text)
            else:
                channel = self.view if self.view != "top" else ""
                self._chat(self.handle, text, channel=channel)
                if self.active_peer and self.active_peer != SCRATCH_PEER:
                    self.outbox.put((self.active_peer, text, channel))

        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            if self.cursor > 0:
                self.cursor -= 1
                del self.input_buf[self.cursor]

        elif ch == curses.KEY_DC:
            if self.cursor < len(self.input_buf):
                del self.input_buf[self.cursor]

        elif ch == curses.KEY_LEFT:
            self.cursor = max(0, self.cursor - 1)
        elif ch == curses.KEY_RIGHT:
            self.cursor = min(len(self.input_buf), self.cursor + 1)
        elif ch == curses.KEY_HOME:
            self.cursor = 0
        elif ch == curses.KEY_END:
            self.cursor = len(self.input_buf)

        elif ch == curses.KEY_UP:
            if not self.history:
                pass
            elif self.history_idx == -1:
                self.history_draft = "".join(self.input_buf)
                self.history_idx   = len(self.history) - 1
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
                self.history_idx   = -1
                self._set_input(self.history_draft)
                self.history_draft = ""

        elif ch == curses.KEY_PPAGE:
            self.scroll += max(1, self.chat_h - 4)
        elif ch == curses.KEY_NPAGE:
            self.scroll = max(0, self.scroll - max(1, self.chat_h - 4))

        elif 32 <= ch <= 126:
            self.input_buf.insert(self.cursor, chr(ch))
            self.cursor += 1
