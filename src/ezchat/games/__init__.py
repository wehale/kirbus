"""ezchat games — plugin system.

BaseGame
--------
Subclass BaseGame, set class attributes, implement start/on_message/is_over.
Drop the file in this directory — the registry picks it up automatically.

Session routing
---------------
Single-player key:  "{handle}:{game_name}"
Multiplayer key:    "{sorted_handle1}:{sorted_handle2}:{game_name}"
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from abc import ABC, abstractmethod
from pathlib import Path

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------
class BaseGame(ABC):
    """Base class for all ezchat games."""

    name:        str = ""   # command name ("chess", "zork", …)
    description: str = ""   # shown in /games list
    min_players: int = 1
    max_players: int = 2

    @classmethod
    def available(cls) -> bool:
        """Return False to hide this game from the list (e.g. missing game file)."""
        return True

    @abstractmethod
    def start(self, players: list[str]) -> str:
        """Called once when the session is created.

        players — list of handle strings (1 or more)
        Returns the opening message sent to all players.
        """

    @abstractmethod
    def on_message(self, sender: str, text: str) -> list[tuple[str, str]]:
        """Handle an incoming message from a player.

        Returns a list of (recipient_handle, message_text) pairs.
        Recipients may be a subset of players or all of them.
        """

    @property
    @abstractmethod
    def is_over(self) -> bool:
        """True when the game has ended and the session should be removed."""


# ---------------------------------------------------------------------------
# Registry — auto-discovers all BaseGame subclasses in this package
# ---------------------------------------------------------------------------
_registry: dict[str, type[BaseGame]] = {}


def _load_plugins() -> None:
    """Import every module in this package so subclasses register themselves."""
    pkg_path = Path(__file__).parent
    for finder, mod_name, _ in pkgutil.iter_modules([str(pkg_path)]):
        full_name = f"ezchat.games.{mod_name}"
        try:
            importlib.import_module(full_name)
        except Exception as exc:
            _log.debug("games: skipping %s: %s", full_name, exc)

    for cls in _all_subclasses(BaseGame):
        if cls.name:
            _registry[cls.name.lower()] = cls
            _log.debug("games: registered %r", cls.name)


def _all_subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _all_subclasses(sub)


def get_game_class(name: str) -> type[BaseGame] | None:
    if not _registry:
        _load_plugins()
    return _registry.get(name.lower())


def list_games() -> list[type[BaseGame]]:
    if not _registry:
        _load_plugins()
    return sorted((c for c in _registry.values() if c.available()), key=lambda c: c.name)


# ---------------------------------------------------------------------------
# Session router
# ---------------------------------------------------------------------------
def _session_key(players: list[str], game_name: str) -> str:
    return ":".join(sorted(players) + [game_name.lower()])


class SessionRouter:
    """Manages all active game sessions."""

    def __init__(self) -> None:
        # session_key → (game_instance, players)
        self._sessions: dict[str, tuple[BaseGame, list[str]]] = {}
        # handle → session_key  (quick reverse lookup)
        self._by_player: dict[str, str] = {}

    def start(self, game_name: str, players: list[str]) -> str:
        """Create and start a new session.  Returns opening text or error."""
        cls = get_game_class(game_name)
        if cls is None:
            available = ", ".join(g.name for g in list_games()) or "none"
            return f"Unknown game '{game_name}'. Available: {available}"

        if len(players) < cls.min_players or len(players) > cls.max_players:
            return (f"{cls.name} requires {cls.min_players}–{cls.max_players} players, "
                    f"got {len(players)}.")

        # End any existing session for these players
        for p in players:
            self._end_player_session(p)

        key = _session_key(players, game_name)
        try:
            game = cls()
            opening = game.start(players)
        except Exception as exc:
            return str(exc)

        self._sessions[key] = (game, players)
        for p in players:
            self._by_player[p] = key
        return opening

    def on_message(self, sender: str, text: str) -> list[tuple[str, str]]:
        """Route a message to the sender's active session.

        Returns list of (recipient, message) to send back.
        Returns [] if sender has no active session.
        """
        key = self._by_player.get(sender)
        if key is None:
            return []
        game, players = self._sessions[key]
        try:
            responses = game.on_message(sender, text)
        except Exception as exc:
            _log.warning("game error for %s: %s", sender, exc)
            responses = [(sender, f"Game error: {exc}")]

        if game.is_over:
            self._remove_session(key)

        return responses

    def active_game(self, handle: str) -> str | None:
        """Return the game name for the player's active session, or None."""
        key = self._by_player.get(handle)
        if key is None:
            return None
        _, players = self._sessions.get(key, (None, []))
        # key format: sorted_players... : game_name
        return key.rsplit(":", 1)[-1]

    def quit(self, handle: str) -> str:
        """End the session for this player."""
        key = self._by_player.get(handle)
        if key is None:
            return "You're not in a game."
        _, players = self._sessions[key]
        self._remove_session(key)
        return "Game ended."

    # ------------------------------------------------------------------
    def _end_player_session(self, handle: str) -> None:
        key = self._by_player.get(handle)
        if key:
            self._remove_session(key)

    def _remove_session(self, key: str) -> None:
        entry = self._sessions.pop(key, None)
        if entry:
            _, players = entry
            for p in players:
                self._by_player.pop(p, None)
