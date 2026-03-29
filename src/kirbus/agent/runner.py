"""Agent runner — launches headless agents."""
from __future__ import annotations

import asyncio
import logging


def run_builtin_echo(args) -> None:
    """Run the built-in echo agent."""
    from kirbus.crypto.keys import load_or_create_identity
    from kirbus.agent.echo import run_echo_server

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from kirbus.home import set_handle
    handle   = getattr(args, "handle", None) or "echo-bot"
    set_handle(handle)
    port     = getattr(args, "listen",  None) or 9000
    identity = load_or_create_identity(handle)

    try:
        asyncio.run(run_echo_server("0.0.0.0", port, identity))
    except KeyboardInterrupt:
        print("\necho-server stopped.")


_BUILTIN_AGENTS = {"games", "echo"}


def run_agent(args) -> None:
    """Load and run an agent — built-in or user script."""
    from kirbus.ai.config import load_ui_config
    from kirbus.crypto.keys import load_or_create_identity

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    )

    from kirbus.home import set_handle
    agent_name = getattr(args, "agent", None) or ""
    handle     = getattr(args, "handle", None) or agent_name or "agent"
    set_handle(handle)
    server     = getattr(args, "server", None) or load_ui_config().server

    if not server:
        print("error: --server URL is required to run an agent (or set [ui] server in config.toml)")
        return

    identity = load_or_create_identity(handle)

    # --- built-in: games ---
    if agent_name.lower() == "games":
        from kirbus.agent.games_agent import run_games_agent
        print(f"Starting games agent as @{identity.handle} → {server}")
        try:
            asyncio.run(run_games_agent(identity, server))
        except KeyboardInterrupt:
            print("\ngames agent stopped.")
        return

    # --- built-in: echo (alias) ---
    if agent_name.lower() == "echo":
        run_builtin_echo(args)
        return

    # --- user script ---
    import importlib.util
    from pathlib import Path

    script = Path(agent_name)
    if not script.exists():
        print(f"error: agent script not found: {script}")
        return

    spec   = importlib.util.spec_from_file_location("_agent_script", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    on_message = getattr(module, "on_message", None)
    on_start   = getattr(module, "on_start",   None)

    if on_message is None:
        print(f"error: {script} must define on_message(sender, text) -> str | None")
        return

    async def _run_script_agent() -> None:
        from kirbus.net.rendezvous_client import RendezvousClient
        from kirbus.net.connection import accept_peer
        from urllib.parse import urlparse
        import json

        rdv        = RendezvousClient(server, identity)
        relay_host = urlparse(server).hostname or "127.0.0.1"
        info = await rdv.server_info()
        relay_port = info.get("relay_port", 9001)

        pub_ip   = await rdv.my_public_ip() or "127.0.0.1"
        endpoint = f"{pub_ip}:0"
        await rdv.register(endpoint)
        rdv.start_keepalive(endpoint)
        print(f"agent @{identity.handle} online")

        if on_start:
            async def _send(recipient: str, text: str) -> None:
                pass   # can't send without a connection yet — on_start is for setup
            await on_start(_send) if asyncio.iscoroutinefunction(on_start) else on_start()

        async def _handle_conn(conn) -> None:
            try:
                while True:
                    frame = await conn.recv()
                    if frame is None:
                        break
                    text   = frame.get("text", "")
                    sender = conn.peer_handle
                    if text:
                        if asyncio.iscoroutinefunction(on_message):
                            reply = await on_message(sender, text)
                        else:
                            reply = on_message(sender, text)
                        if reply:
                            await conn.send(str(reply))
            finally:
                await conn.close()

        while True:
            try:
                reader, writer = await asyncio.open_connection(relay_host, relay_port)
                writer.write(
                    (json.dumps({"role": "wait", "handle": identity.handle}) + "\n").encode()
                )
                await writer.drain()
                line = await reader.readline()
                resp = json.loads(line.decode().strip())
                if resp.get("ok"):
                    conn = await accept_peer(reader, writer, identity)
                    asyncio.create_task(_handle_conn(conn))
                else:
                    writer.close()
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logging.warning("relay error: %s", exc)
                await asyncio.sleep(5)

    try:
        asyncio.run(_run_script_agent())
    except KeyboardInterrupt:
        print(f"\nagent @{identity.handle} stopped.")
