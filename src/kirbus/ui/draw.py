"""DrawMixin — all curses rendering methods for the kirbus UI."""
from __future__ import annotations

import curses
import re
from datetime import datetime, date as _date_cls, timedelta
from typing import TYPE_CHECKING, Optional

from wcwidth import wcswidth, wcwidth as _wcwidth

from kirbus.ui.models import SCRATCH_PEER, SCRATCH_LABEL, BACK_ENTRY, Message, AgentMenu


def _display_width(text: str) -> int:
    """Return the number of terminal columns *text* occupies."""
    w = wcswidth(text)
    if w >= 0:
        return w
    # wcswidth returns -1 if any non-printable char is present; fall back to
    # summing per-character widths, treating non-printable as 0.
    total = 0
    for ch in text:
        cw = _wcwidth(ch)
        total += cw if cw > 0 else 0
    return total


def _wrap_text(text: str, width: int) -> list[str]:
    """Word-wrap *text* respecting actual terminal display widths.

    Unlike textwrap.wrap(), this accounts for wide/ambiguous Unicode
    characters (box-drawing, CJK, etc.) that occupy >1 terminal column.
    """
    if width <= 0:
        return [text]
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    current_w = 0
    for word in words:
        ww = _display_width(word)
        if current:
            # +1 for the space
            if current_w + 1 + ww <= width:
                current += " " + word
                current_w += 1 + ww
            else:
                lines.append(current)
                current = word
                current_w = ww
        else:
            current = word
            current_w = ww
    if current:
        lines.append(current)
    return lines or [text]

if TYPE_CHECKING:
    pass  # avoid circular imports; runtime access is via self


class DrawMixin:
    """Rendering methods mixed into UI.

    Relies on state attributes set by UI.__init__:
        self.theme, self.focus, self.peer_cursor, self.active_peer,
        self.view, self.channels, self.peers, self.messages, self.unread,
        self.scroll, self.input_buf, self.cursor, self.handle,
        self.chat_w, self.chat_h, self.pw, self.cw, self.sw, self.iw
    """

    _URL_RE = re.compile(r"(https?://[^\s\"'<>)\]]+|ftp://[^\s\"'<>)\]]+)")

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------
    def _split_urls(self, text: str) -> list[tuple[str, bool]]:
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
        try:
            win.addstr(y, x, text, attr)
        except curses.error:
            pass

    def _addstr_with_urls(self, win: curses.window, y: int, x: int,
                          text: str, base_attr: int, max_w: int) -> None:
        url_attr  = self.theme.accent | curses.A_UNDERLINE
        col       = x
        remaining = max_w
        for segment, is_url in self._split_urls(text):
            if remaining <= 0:
                break
            # Truncate segment to fit remaining display columns.
            chunk = segment
            cw = _display_width(chunk)
            if cw > remaining:
                # Trim character by character from the end.
                truncated = ""
                tw = 0
                for ch in chunk:
                    chw = _wcwidth(ch)
                    if chw < 0:
                        chw = 0
                    if tw + chw > remaining:
                        break
                    truncated += ch
                    tw += chw
                chunk = truncated
                cw = tw
            try:
                win.addstr(y, col, chunk, url_attr if is_url else base_attr)
            except curses.error:
                pass
            col       += cw
            remaining -= cw

    def _draw_border(self, win: curses.window, title: str = "",
                     attr: Optional[int] = None) -> None:
        b = self.theme.borders
        a = attr if attr is not None else self.theme.border
        h, w = win.getmaxyx()
        self._safe_addstr(win, 0,     0, b["tl"] + b["h"] * (w - 2) + b["tr"], a)
        self._safe_addstr(win, h - 1, 0, b["bl"] + b["h"] * (w - 2) + b["br"], a)
        for row in range(1, h - 1):
            self._safe_addstr(win, row, 0,     b["v"], a)
            self._safe_addstr(win, row, w - 1, b["v"], a)
        if title and w > 4:
            label = f" {title} "[:w - 4]
            lw    = _display_width(label)
            align = self.theme.title_align
            if align == "center":
                x = max(1, (w - lw) // 2)
            elif align == "right":
                x = max(1, w - lw - 1)
            else:
                x = 2
            self._safe_addstr(win, 0, x, label, a | curses.A_BOLD)

    # ------------------------------------------------------------------
    # Presence panel
    # ------------------------------------------------------------------
    def _presence_rows(self) -> list[tuple[str, str, bool]]:
        """Return (key, display_label, online) rows for the current view."""
        menu: AgentMenu | None = getattr(self, "agent_menu", None)
        if menu is not None:
            return self._agent_presence_rows(menu)

        if self.view != "top":
            ch = self.channels.get(self.view)
            members = ch.members if ch else []
            agent_peers = getattr(self, "agent_peers", set())
            rows = [(BACK_ENTRY, "../", True)]
            for handle in members:
                if handle == self.handle or handle in agent_peers:
                    continue
                online = any(h == handle and on for h, on in self.peers)
                rows.append((handle, handle, online))
            return rows
        # Show server list from registry if not connected to a server yet
        registry_servers = getattr(self, "registry_servers", [])
        connected_server = getattr(self, "connected_server", "")
        if registry_servers and not connected_server:
            rows: list[tuple[str, str, bool]] = []
            rows.append(("\x00srv_header", "── servers ──", False))
            for srv in registry_servers:
                name   = srv.get("name", "?")
                access = srv.get("access", "open")
                count  = srv.get("online_count", 0)
                icon   = "🔒" if access == "password" else "●"
                label  = f"{icon} {name} ({count})"
                rows.append((f"\x00srv:{name}", label, True))
            return rows

        rows: list[tuple[str, str, bool]] = [(SCRATCH_PEER, SCRATCH_LABEL, True)]
        if self.channels:
            rows.append(("\x00ch_header", "── channels ──", False))
            for name, ch in sorted(self.channels.items()):
                rows.append((ch.key, f"# {name}", True))
        if self.peers:
            fps = getattr(self, "peer_fingerprints", {})
            kst = getattr(self, "peer_key_status", {})
            rows.append(("\x00dm_header", "── direct ──", False))
            for handle, online in sorted(self.peers, key=lambda p: (not p[1], p[0])):
                if not online:
                    continue
                fp      = fps.get(handle, "")
                status  = kst.get(handle, "known")
                blocked = handle in getattr(self, "blocked_peers", set())
                if blocked:
                    pfx = "⊘ "
                elif status == "changed":
                    pfx = "⚠ "
                elif status == "new":
                    pfx = "★ "
                else:
                    pfx = ""
                label  = f"{pfx}{handle} [{fp[:4]}]" if fp else f"{pfx}{handle}"
                rows.append((handle, label, online))
        return rows

    def _agent_presence_rows(self, menu: AgentMenu) -> list[tuple[str, str, bool]]:
        """Build sidebar rows for an agent menu."""
        session = getattr(self, "agent_session", "")
        picking = getattr(self, "agent_picking_peer", "")

        if session:
            # In an active session — just show ../
            return [(BACK_ENTRY, "../", True)]

        if picking:
            # Picking a multiplayer opponent — show ../ and online peers
            rows: list[tuple[str, str, bool]] = [(BACK_ENTRY, "../", True)]
            rows.append(("\x00pick_header", "── pick opponent ──", False))
            for handle, online in sorted(self.peers, key=lambda p: (not p[1], p[0])):
                if online and handle != self.handle:
                    rows.append((f"\x00pick:{handle}", handle, True))
            return rows

        # Show the menu entries + online peers
        rows = [(BACK_ENTRY, "../", True)]
        if menu.entries:
            rows.append(("\x00menu_header", "── play ──", False))
            for entry in menu.entries:
                suffix = " ⚔" if entry.type == "multi" else ""
                rows.append((f"\x00entry:{entry.key}", f"{entry.label}{suffix}", True))
        # Show online peers (for multiplayer awareness)
        online_peers = [(h, on) for h, on in self.peers
                        if on and h != self.handle]
        if online_peers:
            rows.append(("\x00peer_header", "── online ──", False))
            for handle, _ in sorted(online_peers, key=lambda p: p[0]):
                rows.append((f"\x00agent_peer:{handle}", f"● {handle}", True))
        return rows

    def _draw_presence(self) -> None:
        self.pw.erase()
        focused     = self.focus == "presence"
        border_attr = self.theme.accent if focused else self.theme.border
        menu: AgentMenu | None = getattr(self, "agent_menu", None)
        registry_servers = getattr(self, "registry_servers", [])
        connected_server = getattr(self, "connected_server", "")
        if menu is not None:
            session = getattr(self, "agent_session", "")
            picking = getattr(self, "agent_picking_peer", "")
            if session:
                panel_title = session
            elif picking:
                panel_title = picking
            else:
                panel_title = menu.title
        elif self.view != "top":
            panel_title = f"# {self.view}"
        elif registry_servers and not connected_server:
            panel_title = "registry"
        else:
            panel_title = "peers"
        self._draw_border(self.pw, panel_title, attr=border_attr)
        h, w = self.pw.getmaxyx()
        inner_w = w - 4

        rows = self._presence_rows()
        # Headers are not selectable — they start with known prefixes
        _HEADER_PREFIXES = ("\x00ch_", "\x00dm_", "\x00srv_",
                            "\x00menu_", "\x00peer_", "\x00pick_")
        selectable = [i for i, (k, _, _) in enumerate(rows)
                      if not any(k.startswith(p) for p in _HEADER_PREFIXES)]
        if selectable:
            if self.peer_cursor not in selectable:
                self.peer_cursor = selectable[0]
        else:
            self.peer_cursor = 0

        for i, (key, label, online) in enumerate(rows):
            row = i + 1
            if row >= h - 1:
                break
            is_header  = any(key.startswith(p) for p in _HEADER_PREFIXES)
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
            elif key.startswith("\x00srv:"):
                attr = self.theme.online
            elif key.startswith("\x00entry:"):
                attr = self.theme.accent
            elif key.startswith(("\x00pick:", "\x00agent_peer:")):
                attr = self.theme.online
            else:
                blocked = key in getattr(self, "blocked_peers", set())
                kst     = getattr(self, "peer_key_status", {})
                status  = kst.get(key, "known")
                has_unread = key in self.unread
                if has_unread:
                    attr = self.theme.error | curses.A_BOLD
                elif blocked:
                    attr = self.theme.offline
                elif status == "changed":
                    attr = self.theme.error
                elif status == "new":
                    attr = self.theme.accent
                else:
                    attr = self.theme.online if online else self.theme.offline

            is_server = key.startswith("\x00srv:")
            dot      = "" if is_scratch or is_back or is_server else ("●" if online else "○")
            prefix   = f"{dot} " if dot else ""
            row_text = f"{prefix}{label}"[:inner_w]
            if is_cursor:
                row_text = row_text.ljust(inner_w)
            self._safe_addstr(self.pw, row, 2, row_text, attr)

        self.pw.noutrefresh()

    # ------------------------------------------------------------------
    # Chat panel
    # ------------------------------------------------------------------
    def _date_label(self, date: str) -> str:
        today     = datetime.now().strftime("%Y-%m-%d")
        yesterday = (_date_cls.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        if date == today:
            return "today"
        if date == yesterday:
            return "yesterday"
        try:
            return datetime.strptime(date, "%Y-%m-%d").strftime("%a %b %-d")
        except ValueError:
            return date

    def _wrap_messages(self) -> list[tuple[Message | None, str, int]]:
        inner_w = max(1, self.chat_w - 4)
        lines: list[tuple[Message | None, str, int]] = []
        last_date: str = ""
        for msg in self.messages:
            if self.active_peer and self.active_peer != SCRATCH_PEER:
                if msg.peer != self.active_peer:
                    continue
            elif self.active_peer == SCRATCH_PEER:
                if msg.peer not in ("", SCRATCH_PEER):
                    continue
            else:
                if msg.peer != "":
                    continue
            if msg.date and msg.date != last_date:
                last_date = msg.date
                label   = self._date_label(msg.date)
                label_w = _display_width(label)
                pad     = max(0, (inner_w - label_w - 2) // 2)
                divider = "─" * pad + f" {label} " + "─" * pad
                lines.append((None, divider, self.theme.timestamp))
            attr   = self._msg_attr(msg)
            prefix = f"[{msg.timestamp}] {msg.sender}: "
            if msg.kind == "preformatted":
                # First line gets the prefix, remaining lines are indented
                # but never word-wrapped — preserves game boards / ASCII art.
                indent = " " * _display_width(prefix)
                for i, raw_line in enumerate(msg.text.split("\n")):
                    if i == 0:
                        lines.append((msg, prefix + raw_line, attr))
                    else:
                        lines.append((msg, indent + raw_line, attr))
            else:
                first  = True
                # Split on newlines first, then word-wrap each line.
                for raw_line in (prefix + msg.text).split("\n"):
                    for part in _wrap_text(raw_line, inner_w) or [raw_line]:
                        lines.append((msg, part if first else "  " + part, attr))
                        first = False
        return lines

    def _msg_attr(self, msg: Message) -> int:
        if msg.kind == "system":       return self.theme.system
        if msg.kind == "error":        return self.theme.error
        if msg.kind == "preformatted": return self.theme.chat
        if msg.sender == self.handle:  return self.theme.accent
        return self.theme.chat

    def _draw_chat(self) -> None:
        self.cw.erase()
        total_unread = sum(self.unread.values())
        if self.active_peer:
            display    = SCRATCH_LABEL if self.active_peer == SCRATCH_PEER else self.active_peer
            chat_title = f"{display} [{total_unread}]" if total_unread else display
        elif getattr(self, "registry_servers", []) and not getattr(self, "connected_server", ""):
            chat_title = "select a chat server with Tab"
        else:
            chat_title = "chat — select a peer with Tab"
        chat_border = self.theme.border
        self._draw_border(self.cw, chat_title, attr=chat_border)
        inner_h = self.chat_h - 2
        inner_w = self.chat_w - 4

        lines = self._wrap_messages()
        total = len(lines)
        self.scroll = max(0, min(self.scroll, max(0, total - inner_h)))
        start   = max(0, total - inner_h - self.scroll)
        visible = lines[start: start + inner_h]

        for row_offset, (_, text, attr) in enumerate(visible):
            self._addstr_with_urls(self.cw, row_offset + 1, 2, text, attr, inner_w)

        if self.scroll > 0:
            indicator = f" ↑ {self.scroll} more "
            self._safe_addstr(self.cw, 1, self.chat_w - _display_width(indicator) - 2,
                              indicator, self.theme.system)
        self.cw.noutrefresh()

    # ------------------------------------------------------------------
    # Status bar and input box
    # ------------------------------------------------------------------
    def _draw_status(self) -> None:
        self.sw.erase()
        _, w = self.sw.getmaxyx()
        peer_count     = sum(1 for _, on in self.peers if on)
        active_display = SCRATCH_LABEL if self.active_peer == SCRATCH_PEER else self.active_peer
        to_label       = f"→ {active_display}" if self.active_peer else "no peer selected"
        total_unread   = sum(self.unread.values())
        unread_label   = f"  │  ● {total_unread}" if total_unread else ""
        su_tag = " [su]" if getattr(self, "is_su", False) else ""
        bar = f"  {self.handle}{su_tag}  │  {to_label}  │  online: {peer_count}{unread_label}  "
        self._safe_addstr(self.sw, 0, 0, bar.ljust(w)[:w], self.theme.status)
        self.sw.noutrefresh()

    def _draw_input(self) -> None:
        self.iw.erase()
        self._draw_border(self.iw)
        _, w    = self.iw.getmaxyx()
        inner_w = w - 4
        peer_display = SCRATCH_LABEL if self.active_peer == SCRATCH_PEER else self.active_peer
        prefix       = f"→ {peer_display}: " if self.active_peer else "> "
        buf_str      = "".join(self.input_buf)
        visible_w    = inner_w - len(prefix)
        view_start   = max(0, self.cursor - visible_w + 1)
        visible      = buf_str[view_start: view_start + visible_w]
        self._safe_addstr(self.iw, 1, 2, prefix + visible, self.theme.input)
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
