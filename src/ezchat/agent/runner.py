"""Agent runner — launches headless agents."""
from __future__ import annotations

import asyncio
import logging


def run_builtin_echo(args) -> None:  # noqa: ANN001
    """Run the built-in echo agent."""
    from ezchat.crypto.keys import load_or_create_identity
    from ezchat.agent.echo import run_echo_server

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    handle = getattr(args, "handle", None) or "echo-bot"
    port   = getattr(args, "listen", None) or 9000
    host   = "0.0.0.0"

    identity = load_or_create_identity(handle)

    try:
        asyncio.run(run_echo_server(host, port, identity))
    except KeyboardInterrupt:
        print("\necho-server stopped.")


def run_agent(args) -> None:  # noqa: ANN001
    """Load and run a user-supplied agent script."""
    raise NotImplementedError("Custom agent runner not yet implemented (Phase 10)")
