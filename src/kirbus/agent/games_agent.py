"""Games agent — headless peer that manages all game sessions.

Handles messages of the form:
    "chess @joebeans"   — challenge joebeans to chess
    "zork"              — start single-player Zork
    "tictactoe @bob"    — challenge bob to tic-tac-toe
    "games" / "help"    — list available games
    "quit"              — end current session
    anything else       — forwarded to the active session

Run with:
    kirbus --agent games --server http://SERVER:8000 --handle games
"""
from __future__ import annotations

import asyncio
import logging

from kirbus.net.connection import Connection

_log = logging.getLogger(__name__)

_NO_SESSION  = "You're not in a game. Type 'games' to see what's available."


def _games_list() -> str:
    from kirbus.games import list_games
    games = list_games()
    if not games:
        return "No games available."
    lines = ["Available games:"]
    for g in games:
        players = (
            "single-player" if g.max_players == 1
            else f"1–{g.max_players} players"
        )
        lines.append(f"  {g.name} — {g.description} ({players})")
    lines.append("")
    lines.append("How to play:")
    lines.append("  Type a game name to start, e.g. 'zork'")
    lines.append("  For multiplayer: 'tictactoe @opponent'")
    lines.append("  Type 'quit' to end a game")
    return "\n".join(lines)


def _parse_start(text: str) -> tuple[str, str | None]:
    """Parse 'chess @joebeans' → ('chess', 'joebeans').
       Parse 'zork' → ('zork', None).
    """
    parts = text.strip().split()
    game  = parts[0].lower()
    opponent = None
    if len(parts) > 1 and parts[1].startswith("@"):
        opponent = parts[1][1:]
    return game, opponent


async def run_games_agent(identity, server: str) -> None:
    """Connect to the mesh and handle game sessions forever."""
    from kirbus.net.rendezvous_client import RendezvousClient
    from kirbus.net.connection import accept_peer
    from kirbus.games import SessionRouter
    from urllib.parse import urlparse

    rdv        = RendezvousClient(server, identity)
    relay_host = urlparse(server).hostname or "127.0.0.1"
    relay_port = 9001
    router     = SessionRouter()

    # connections: peer_handle → Connection
    connections: dict[str, Connection] = {}

    # Register with rendezvous
    pub_ip   = await rdv.my_public_ip() or "127.0.0.1"
    endpoint = f"{pub_ip}:0"   # relay-only, no direct port
    await rdv.register(endpoint)
    rdv.start_keepalive(endpoint)
    _log.info("games agent registered as %s", identity.handle)
    print(f"games agent online as @{identity.handle}")

    async def _send_all(responses: list[tuple[str, str]]) -> None:
        for recipient, msg in responses:
            conn = connections.get(recipient)
            if conn:
                try:
                    await conn.send(msg, channel=_CHANNEL)
                except Exception as exc:
                    _log.warning("send to %s failed: %s", recipient, exc)

    async def _handle_message(sender: str, text: str) -> None:
        text = text.strip()
        if not text:
            return

        lower = text.lower()

        # Help
        if lower in ("games", "help", "?", "/games", "/help"):
            conn = connections.get(sender)
            if conn:
                await conn.send(_games_list(), channel=_CHANNEL)
            return

        # Quit current session
        if lower in ("quit", "q", "/quit"):
            result = router.quit(sender)
            conn = connections.get(sender)
            if conn:
                await conn.send(result, channel=_CHANNEL)
            return

        # Check if sender is already in a game
        active = router.active_game(sender)
        if active:
            responses = router.on_message(sender, text)
            await _send_all(responses)
            return

        # Try to start a new game
        from kirbus.games import get_game_class
        game_name, opponent = _parse_start(text)
        if get_game_class(game_name):
            players = [sender]
            if opponent:
                players.append(opponent)
            opening = router.start(game_name, players)
            # Send opening to all players via #games
            for p in players:
                conn = connections.get(p)
                if conn:
                    try:
                        await conn.send(opening, channel=_CHANNEL)
                    except Exception:
                        pass
            return

        # Unknown — show help
        conn = connections.get(sender)
        if conn:
            await conn.send(
                f"Unknown command '{text}'.\n{_games_list()}",
                channel=_CHANNEL,
            )

    _CHANNEL = "games"   # all game traffic lives in #games

    async def _handle_conn(conn: Connection) -> None:
        connections[conn.peer_handle] = conn
        _log.info("games: %s connected", conn.peer_handle)
        try:
            # Invite peer to #games channel so traffic shows up there
            await conn.send(f"\x00channel_invite\x00{_CHANNEL}")
            await conn.send(_games_list(), channel=_CHANNEL)
            while True:
                frame = await conn.recv()
                if frame is None:
                    break
                text    = frame.get("text", "")
                channel = frame.get("channel", "")
                # Only handle messages in #games or direct (for compatibility)
                if text and (not channel or channel == _CHANNEL):
                    await _handle_message(conn.peer_handle, text)
        finally:
            connections.pop(conn.peer_handle, None)
            router.quit(conn.peer_handle)
            await conn.close()
            _log.info("games: %s disconnected", conn.peer_handle)

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
                    await asyncio.sleep(5)
                    continue
                conn = await accept_peer(reader, writer, identity)
                asyncio.create_task(_handle_conn(conn))
            except asyncio.CancelledError:
                return
            except Exception as exc:
                _log.warning("relay error: %s", exc)
                await asyncio.sleep(5)

    await _relay_loop()
