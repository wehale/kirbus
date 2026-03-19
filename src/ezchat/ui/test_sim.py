"""Test-mode simulation: fake peers, echo bot, random messages."""
from __future__ import annotations

import curses
import queue
import random
import threading
import time

from ezchat.ui.models import MIN_ROWS, MIN_COLS, too_small
from ezchat.ui.theme import set_theme

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


def _test_sim_thread(ui, stop: threading.Event) -> None:
    """Background thread: fake peers come online, respond to invites, trade messages."""
    peer_channels: dict[str, set] = {name: set() for name in _TEST_PEERS}
    next_random_msg = time.monotonic() + random.uniform(4.0, 10.0)

    for i, name in enumerate(_TEST_PEERS):
        if stop.is_set():
            return
        time.sleep(0.8 + i * 0.5)
        ui.peers.append((name, True))
        ui.inbox.put((name, f"hey {ui.handle} 👋"))

    while not stop.is_set():
        stop.wait(0.2)
        if stop.is_set():
            break

        # Drain outbox: handle channel invites
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

        # Drain sim_inbox: ack user channel messages
        if ui.sim_inbox is not None:
            try:
                while True:
                    ch_name, user_text = ui.sim_inbox.get_nowait()
                    for peer, chans in peer_channels.items():
                        if ch_name in chans:
                            acks = [
                                f"[ack] {user_text}", "👍", "got it",
                                "noted", "on it", f"re: {user_text[:30]}",
                            ]
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

        # Periodic random message
        if time.monotonic() >= next_random_msg:
            next_random_msg = time.monotonic() + random.uniform(4.0, 10.0)
            sender      = random.choice(_TEST_PEERS)
            text        = random.choice(_TEST_MESSAGES)
            my_channels = list(peer_channels[sender])
            if my_channels and random.random() < 0.6:
                ui.inbox.put((sender, text, random.choice(my_channels)))
            else:
                ui.inbox.put((sender, text, ""))


def _test_curses_main(stdscr: curses.window, args) -> None:
    from ezchat.ui.app import UI

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
    ui     = UI(stdscr, theme, handle=handle)
    ui._system("test mode — simulated peers will appear shortly")

    # Echo bot: reply to direct messages only
    original_chat = ui._chat.__func__  # type: ignore[attr-defined]

    def _echo(self, sender: str, text: str, channel: str = "") -> None:
        original_chat(self, sender, text, channel=channel)
        if sender == self.handle and self.active_peer and not channel:
            replies = [
                f"got it: \"{text}\"", "👍", "on it", "ack",
                "noted", f"re: {text[:30]} — sounds good",
            ]
            self.inbox.put((self.active_peer, random.choice(replies), ""))

    ui._chat      = lambda sender, text, channel="": _echo(ui, sender, text, channel=channel)  # type: ignore[method-assign]
    ui.sim_inbox  = queue.Queue()

    stop = threading.Event()
    sim  = threading.Thread(target=_test_sim_thread, args=(ui, stop), daemon=True)
    sim.start()
    try:
        ui.run()
    finally:
        stop.set()


def run_test_mode(args) -> None:
    """Run in loopback test mode with simulated peers."""
    curses.wrapper(_test_curses_main, args)
