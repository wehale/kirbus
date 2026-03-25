"""Zork I, II, III — wraps the Jericho Z-machine interpreter.

Requires:  pip install jericho  (included in the [games] extra)
Game files (z5 format, MIT-licensed via the-infocom-files):
  curl -L https://raw.githubusercontent.com/the-infocom-files/zork1/master/zork1.z5 \
       -o ~/.kirbus/games/zork1.z5
  curl -L https://raw.githubusercontent.com/the-infocom-files/zork2/master/zork2.z5 \
       -o ~/.kirbus/games/zork2.z5
  curl -L https://raw.githubusercontent.com/the-infocom-files/zork3/master/zork3.z5 \
       -o ~/.kirbus/games/zork3.z5
"""
from __future__ import annotations

from pathlib import Path

from kirbus.games import BaseGame
from kirbus.home import get_home


def _find_file(*names: str) -> Path | None:
    base = get_home() / "games"
    for name in names:
        p = base / name
        if p.exists():
            return p
    return None


class _ZorkBase(BaseGame):
    """Shared logic for all Zork titles."""
    min_players = 1
    max_players = 1

    # Subclasses set these
    _filenames: tuple[str, ...] = ()
    _title: str = ""

    @classmethod
    def available(cls) -> bool:
        return _find_file(*cls._filenames) is not None

    def __init__(self) -> None:
        self._env    = None
        self._over   = False

    def start(self, players: list[str]) -> str:
        try:
            import jericho
        except ImportError:
            raise RuntimeError(
                "Zork requires the 'jericho' package.\n"
                "Install it:  uv pip install -e '.[games]'"
            )

        game_file = _find_file(*self._filenames)
        if game_file is None:
            names = " or ".join(self._filenames)
            raise RuntimeError(
                f"{self._title} game file not found.\n"
                f"Place {names} in ~/.kirbus/games/"
            )

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._env = jericho.FrotzEnv(str(game_file))
        obs, _ = self._env.reset()
        return obs.strip()

    def on_message(self, sender: str, text: str) -> list[tuple[str, str]]:
        if self._env is None:
            return [(sender, "No active session.")]
        cmd = text.strip()
        if cmd.lower() in ("quit", "q"):
            self._over = True
            self._env.close()
            return [(sender, f"{self._title} session ended.")]
        try:
            obs, _reward, done, _info = self._env.step(cmd)
        except Exception as exc:
            return [(sender, f"Error: {exc}")]
        if done:
            self._over = True
        return [(sender, obs.strip())]

    @property
    def is_over(self) -> bool:
        return self._over


class ZorkGame(_ZorkBase):
    name       = "zork"
    description = "Zork I: The Great Underground Empire"
    _title     = "Zork I"
    _filenames = ("zork1.z5", "zork1.z3", "zork.z5", "zork.z3")


class Zork2Game(_ZorkBase):
    name       = "zork2"
    description = "Zork II: The Wizard of Frobozz"
    _title     = "Zork II"
    _filenames = ("zork2.z5", "zork2.z3")


class Zork3Game(_ZorkBase):
    name       = "zork3"
    description = "Zork III: The Dungeon Master"
    _title     = "Zork III"
    _filenames = ("zork3.z5", "zork3.z3")
