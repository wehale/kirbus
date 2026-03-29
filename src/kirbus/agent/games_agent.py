"""Games agent — headless peer that manages game sessions via the menu protocol.

Run with:
    kirbus --agent games --server http://SERVER:8000 --handle games
"""
from __future__ import annotations

import asyncio
import logging

from kirbus.agent.menu import MenuAgent, MenuEntry
from kirbus.net.connection import Connection

_log = logging.getLogger(__name__)


class GamesAgent(MenuAgent):
    """Presents available games as a menu; manages game sessions."""

    def __init__(self) -> None:
        super().__init__()
        from kirbus.games import SessionRouter
        self._router = SessionRouter()

    def get_title(self) -> str:
        return "games"

    def get_entries(self) -> list[MenuEntry]:
        from kirbus.games import list_games
        entries = []
        for g in list_games():
            entry_type = "single" if g.max_players == 1 else "multi"
            entries.append(MenuEntry(key=g.name, label=g.description, type=entry_type))
        return entries

    def on_select(self, sender: str, key: str, opponent: str | None = None) -> str:
        players = [sender]
        if opponent:
            players.append(opponent)
        return self._router.start(key, players)

    def on_message(self, sender: str, text: str) -> list[tuple[str, str]]:
        return self._router.on_message(sender, text)

    def on_back(self, sender: str) -> str | None:
        result = self._router.quit(sender)
        return result if result != "You're not in a game." else None


async def run_games_agent(identity, server: str) -> None:
    """Connect to the mesh and handle game sessions forever."""
    from kirbus.net.rendezvous_client import RendezvousClient
    from kirbus.net.connection import accept_peer
    from urllib.parse import urlparse

    agent = GamesAgent()

    rdv        = RendezvousClient(server, identity)
    relay_host = urlparse(server).hostname or "127.0.0.1"
    # Fetch relay port from server
    info = await rdv.server_info()
    relay_port = info.get("relay_port", 9001)

    # Register with rendezvous
    pub_ip   = await rdv.my_public_ip() or "127.0.0.1"
    endpoint = f"{pub_ip}:0"
    await rdv.register(endpoint)
    rdv.start_keepalive(endpoint)
    _log.info("games agent registered as %s", identity.handle)

    # Register menu with server so clients see it immediately
    entries = agent.get_entries()
    menu_data = {
        "title": agent.get_title(),
        "entries": [{"key": e.key, "label": e.label, "type": e.type} for e in entries],
    }
    await rdv.register_agent_menu(identity.handle, menu_data)

    print(f"games agent online as @{identity.handle}")

    async def _relay_loop() -> None:
        import json
        while True:
            try:
                reader, writer = await asyncio.open_connection(relay_host, relay_port)
                writer.write(
                    (json.dumps({"role": "wait", "handle": identity.handle}) + "\n").encode()
                )
                await writer.drain()
                line = await reader.readline()
                resp = json.loads(line.decode().strip())
                if not resp.get("ok"):
                    writer.close()
                    await asyncio.sleep(1)
                    continue
                conn = await accept_peer(reader, writer, identity)
                asyncio.create_task(agent.handle_conn(conn))
            except asyncio.CancelledError:
                return
            except Exception as exc:
                _log.warning("relay error: %s", exc)
                await asyncio.sleep(5)

    await _relay_loop()
