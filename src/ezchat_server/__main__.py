"""ezchat-server — entry point.

Usage
-----
    ezchat-server                          # defaults: API :8000, relay :9001
    ezchat-server --api-port 8000 --relay-port 9001
    ezchat-server --config /path/to/server.toml

server.toml example
-------------------
    [server]
    host       = "0.0.0.0"
    api_port   = 8000
    relay_port = 9001
    ttl        = 60
    log_level  = "info"
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path


async def _main(cfg) -> None:
    from aiohttp import web
    from ezchat_server.rendezvous import make_app
    from ezchat_server.relay import start_relay_server

    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    )
    log = logging.getLogger("ezchat-server")

    # --- rendezvous HTTP API ---
    app    = make_app(ttl=cfg.ttl)
    runner = web.AppRunner(app)
    await runner.setup()
    site   = web.TCPSite(runner, cfg.host, cfg.api_port)
    await site.start()
    log.info("rendezvous API listening on %s:%d", cfg.host, cfg.api_port)

    # --- TCP relay ---
    relay = await start_relay_server(cfg.host, cfg.relay_port)
    log.info("relay listening on %s:%d", cfg.host, cfg.relay_port)

    log.info("ezchat-server ready  (ttl=%ds)", cfg.ttl)

    try:
        await asyncio.Event().wait()   # run forever
    finally:
        relay.close()
        await runner.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ezchat-server",
        description="ezchat rendezvous + relay server",
    )
    parser.add_argument("--config",      metavar="FILE", help="Path to server.toml")
    parser.add_argument("--host",        default=None)
    parser.add_argument("--api-port",    type=int, default=None, dest="api_port")
    parser.add_argument("--relay-port",  type=int, default=None, dest="relay_port")
    parser.add_argument("--ttl",         type=int, default=None)
    parser.add_argument("--log-level",   default=None, dest="log_level")
    args = parser.parse_args()

    from ezchat_server.config import load_server_config
    cfg_path = Path(args.config) if args.config else None
    cfg      = load_server_config(cfg_path)

    # CLI overrides
    if args.host:        cfg.host       = args.host
    if args.api_port:    cfg.api_port   = args.api_port
    if args.relay_port:  cfg.relay_port = args.relay_port
    if args.ttl:         cfg.ttl        = args.ttl
    if args.log_level:   cfg.log_level  = args.log_level

    asyncio.run(_main(cfg))


if __name__ == "__main__":
    main()
