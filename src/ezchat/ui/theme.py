"""Theme engine for ezchat.

Loads TOML theme files and converts them into curses color attributes.
Themes can be placed in ~/.ezchat/themes/ to override or extend built-ins.
"""
from __future__ import annotations

import curses
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Color name → (curses color constant index 0-7, is_bright)
# Resolved lazily since curses constants are ints and don't require init.
# ---------------------------------------------------------------------------
_COLOR_MAP: dict[str, tuple[int, bool]] = {
    "black":        (0, False),
    "red":          (1, False),
    "green":        (2, False),
    "yellow":       (3, False),
    "blue":         (4, False),
    "magenta":      (5, False),
    "cyan":         (6, False),
    "white":        (7, False),
    "dark_gray":    (0, True),   # bold black → dark gray on most terminals
    "bright_red":   (1, True),
    "bright_green": (2, True),
    "bright_yellow":(3, True),
    "bright_blue":  (4, True),
    "bright_magenta":(5, True),
    "bright_cyan":  (6, True),
    "bright_white": (7, True),
}

# ---------------------------------------------------------------------------
# Border character sets
# ---------------------------------------------------------------------------
BORDER_CHARS: dict[str, dict[str, str]] = {
    "single": {
        "tl": "┌", "tr": "┐", "bl": "└", "br": "┘",
        "h":  "─", "v":  "│",
    },
    "double": {
        "tl": "╔", "tr": "╗", "bl": "╚", "br": "╝",
        "h":  "═", "v":  "║",
    },
    "rounded": {
        "tl": "╭", "tr": "╮", "bl": "╰", "br": "╯",
        "h":  "─", "v":  "│",
    },
    "ascii": {
        "tl": "+", "tr": "+", "bl": "+", "br": "+",
        "h":  "-", "v":  "|",
    },
    "none": {
        "tl": " ", "tr": " ", "bl": " ", "br": " ",
        "h":  " ", "v":  " ",
    },
}

# ---------------------------------------------------------------------------
# Color pair registry (must be initialised after curses.start_color())
# ---------------------------------------------------------------------------
_pair_counter: int = 1          # pair 0 is the terminal default
_pair_cache: dict[tuple[int, int], int] = {}


def _get_pair(fg_idx: int, bg_idx: int) -> int:
    """Return a curses pair number for (fg, bg), allocating one if needed."""
    global _pair_counter
    key = (fg_idx, bg_idx)
    if key not in _pair_cache:
        curses.init_pair(_pair_counter, fg_idx, bg_idx)
        _pair_cache[key] = _pair_counter
        _pair_counter += 1
    return _pair_cache[key]


def _attr(fg_name: str, bg_name: str) -> int:
    """Return a curses attribute int for the given fg/bg color names."""
    fg_idx, fg_bright = _COLOR_MAP[fg_name]
    bg_idx, _         = _COLOR_MAP[bg_name]
    pair_num = _get_pair(fg_idx, bg_idx)
    attr = curses.color_pair(pair_num)
    if fg_bright:
        attr |= curses.A_BOLD
    return attr


# ---------------------------------------------------------------------------
# Theme dataclass
# ---------------------------------------------------------------------------
@dataclass
class Theme:
    name: str
    description: str

    # Raw color names from TOML
    _colors: dict[str, str] = field(repr=False)

    # Border config
    border_style: str = "single"
    title_align: str = "left"

    # Computed curses attrs — populated by activate()
    chat:      int = 0
    timestamp: int = 0
    accent:    int = 0
    ai:        int = 0
    error:     int = 0
    system:    int = 0
    online:    int = 0
    offline:   int = 0
    agent:     int = 0
    panel:     int = 0
    status:    int = 0
    input:     int = 0
    border:    int = 0
    bg:        int = 0

    # Border char dict (populated by activate())
    borders: dict[str, str] = field(default_factory=dict)

    def activate(self) -> None:
        """Compute all curses attributes. Call after curses.start_color()."""
        c = self._colors
        bg   = c.get("background",  "black")
        self.chat      = _attr(c.get("foreground",  "white"),     bg)
        self.timestamp = _attr(c.get("timestamp_fg","dark_gray"),  bg)
        self.accent    = _attr(c.get("accent",      "cyan"),       bg)
        self.ai        = _attr(c.get("ai_fg",       "cyan"),       bg)
        self.error     = _attr(c.get("error_fg",    "red"),        bg)
        self.system    = _attr(c.get("system_fg",   "yellow"),     bg)
        self.online    = _attr(c.get("online_fg",   "green"),      bg)
        self.offline   = _attr(c.get("offline_fg",  "dark_gray"),  bg)
        self.agent     = _attr(c.get("agent_fg",    "cyan"),       bg)
        self.panel     = _attr(c.get("panel_fg",    "white"),
                               c.get("panel_bg",    bg))
        self.status    = _attr(c.get("status_fg",   "black"),
                               c.get("status_bg",   "white"))
        self.input     = _attr(c.get("input_fg",    "white"),
                               c.get("input_bg",    bg))
        self.border    = _attr(c.get("border_fg",   "white"),      bg)
        self.bg        = _attr(c.get("foreground",  "white"),      bg)

        self.borders = BORDER_CHARS.get(self.border_style, BORDER_CHARS["single"])


# ---------------------------------------------------------------------------
# Theme loading
# ---------------------------------------------------------------------------
_BUILTIN_DIR = Path(__file__).parent.parent / "themes"
_USER_DIR    = Path.home() / ".ezchat" / "themes"


def _load_toml(path: Path) -> Theme:
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    meta   = data.get("meta",   {})
    colors = data.get("colors", {})
    border = data.get("border", {})
    return Theme(
        name         = meta.get("name",        path.stem),
        description  = meta.get("description", ""),
        _colors      = colors,
        border_style = border.get("style",       "single"),
        title_align  = border.get("title_align", "left"),
    )


def _theme_map() -> dict[str, Path]:
    """Return name → path mapping, user themes shadowing built-ins."""
    themes: dict[str, Path] = {}
    for d in (_BUILTIN_DIR, _USER_DIR):
        if d.is_dir():
            for p in sorted(d.glob("*.toml")):
                themes[p.stem] = p
    return themes


def load_theme(name: str) -> Theme:
    """Load a theme by stem name (e.g. 'phosphor_green')."""
    themes = _theme_map()
    if name not in themes:
        available = ", ".join(sorted(themes))
        raise ValueError(f"Unknown theme {name!r}. Available: {available}")
    return _load_toml(themes[name])


def list_themes() -> list[str]:
    """Return sorted list of available theme names."""
    return sorted(_theme_map())


# ---------------------------------------------------------------------------
# Global active theme
# ---------------------------------------------------------------------------
_active: Optional[Theme] = None


def current_theme() -> Theme:
    """Return the currently active theme (default: phosphor_green)."""
    global _active
    if _active is None:
        _active = load_theme("phosphor_green")
    return _active


def set_theme(name: str) -> Theme:
    """Load, activate, and return a theme as the global active theme.

    activate() must be called after curses.start_color() — this function
    does NOT call activate() so the caller controls timing.
    """
    global _active
    _active = load_theme(name)
    return _active
