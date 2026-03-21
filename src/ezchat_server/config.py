"""Server configuration."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ServerConfig:
    host:        str = "0.0.0.0"
    api_port:    int = 8000
    relay_port:  int = 9001
    ttl:         int = 60
    log_level:   str = "info"


def load_server_config(path: Path | None = None) -> ServerConfig:
    if path is None or not path.exists():
        return ServerConfig()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ServerConfig()
    s = data.get("server", {})
    return ServerConfig(
        host       = s.get("host",       "0.0.0.0"),
        api_port   = s.get("api_port",   8000),
        relay_port = s.get("relay_port", 9001),
        ttl        = s.get("ttl",        60),
        log_level  = s.get("log_level",  "info"),
    )
