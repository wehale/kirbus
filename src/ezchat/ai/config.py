"""Read config sections from ~/.ezchat/config.toml."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from ezchat.home import get_home

_DEFAULTS = {
    "provider": "openai-compat",
    "model":    "gemma3:4b",
    "base_url": "http://localhost:11434/v1",
    "api_key":  "",
}


@dataclass
class AIConfig:
    provider: str = "openai-compat"
    model:    str = "gemma3:4b"
    base_url: str = "http://localhost:11434/v1"
    api_key:  str = ""


@dataclass
class UIConfig:
    theme:  str = "phosphor_green"
    handle: str = ""


def _load_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_ai_config(path: Path | None = None) -> AIConfig:
    """Load [ai] from config.toml; return defaults if file/section absent."""
    ai = _load_toml(path or get_home() / "config.toml").get("ai", {})
    return AIConfig(
        provider = ai.get("provider", _DEFAULTS["provider"]),
        model    = ai.get("model",    _DEFAULTS["model"]),
        base_url = ai.get("base_url", _DEFAULTS["base_url"]),
        api_key  = ai.get("api_key",  _DEFAULTS["api_key"]),
    )


def load_ui_config(path: Path | None = None) -> UIConfig:
    """Load [ui] from config.toml; return defaults if file/section absent."""
    ui = _load_toml(path or get_home() / "config.toml").get("ui", {})
    return UIConfig(
        theme  = ui.get("theme",  "phosphor_green"),
        handle = ui.get("handle", ""),
    )
