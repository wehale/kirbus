"""MenuAgent — base class for agents that expose a menu to clients.

Protocol messages (over existing peer connections):

  Agent → Client:
    \x00menu\x00<json>       Send menu entries to display in sidebar
    \x00session\x00<json>    Notify client that a session started/ended
    \x00invite_game\x00<json> Invite a peer to a multiplayer game

  Client → Agent:
    \x00select\x00<key>           Single-player entry selected
    \x00select\x00<key>\x00<peer> Multiplayer entry selected + opponent
    \x00back\x00                  End current session / go back
    \x00accept_invite\x00<id>     Accept a multiplayer invite
    \x00decline_invite\x00<id>    Decline a multiplayer invite
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from kirbus.net.connection import Connection

_log = logging.getLogger(__name__)


@dataclass
class MenuEntry:
    """A single entry in the agent's menu."""
    key:   str
    label: str
    type:  str = "single"   # "single" | "multi"


class MenuAgent(ABC):
    """Base class for agents that present a menu to connected clients."""

    def __init__(self) -> None:
        self.connections: dict[str, Connection] = {}
        self._sessions: dict[str, str] = {}  # handle → active entry key
        self._pending_invites: dict[str, dict] = {}  # invite_id → invite info

    # ------------------------------------------------------------------
    # Subclass interface
    # ------------------------------------------------------------------
    @abstractmethod
    def get_title(self) -> str:
        """Title shown in the sidebar panel."""

    @abstractmethod
    def get_entries(self) -> list[MenuEntry]:
        """Return the flat list of menu entries."""

    @abstractmethod
    def on_select(self, sender: str, key: str, opponent: str | None = None) -> str:
        """Called when a user selects an entry.

        For single-player: opponent is None.
        For multi-player: opponent is the chosen peer's handle.
        Returns the opening message to send to the player(s).
        """

    @abstractmethod
    def on_message(self, sender: str, text: str) -> list[tuple[str, str]]:
        """Handle a message from a player in an active session.

        Returns list of (recipient_handle, response_text) pairs.
        """

    @abstractmethod
    def on_back(self, sender: str) -> str | None:
        """Called when a user exits their session. Return optional message."""

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------
    async def handle_conn(self, conn: Connection) -> None:
        """Main loop for a single client connection."""
        self.connections[conn.peer_handle] = conn
        _log.info("%s connected", conn.peer_handle)

        await self._send_menu(conn)

        try:
            while True:
                frame = await conn.recv()
                if frame is None:
                    break
                text = frame.get("text", "")
                if not text:
                    continue
                await self._route_message(conn.peer_handle, text)
        finally:
            # Clean up
            handle = conn.peer_handle
            self.connections.pop(handle, None)
            self._sessions.pop(handle, None)
            self.on_back(handle)
            await conn.close()
            _log.info("%s disconnected", handle)

    # ------------------------------------------------------------------
    # Protocol handling
    # ------------------------------------------------------------------
    async def _send_menu(self, conn: Connection) -> None:
        """Send the menu to a client."""
        entries = self.get_entries()
        payload = json.dumps({
            "title": self.get_title(),
            "entries": [
                {"key": e.key, "label": e.label, "type": e.type}
                for e in entries
            ],
        })
        await conn.send(f"\x00menu\x00{payload}")

    async def _route_message(self, sender: str, text: str) -> None:
        """Route an incoming message based on protocol prefix."""
        if text.startswith("\x00select\x00"):
            parts = text.split("\x00")
            # parts: ['', 'select', key] or ['', 'select', key, '', opponent]
            key = parts[2]
            opponent = parts[4] if len(parts) > 4 else None

            if opponent:
                await self._handle_multi_select(sender, key, opponent)
            else:
                await self._handle_single_select(sender, key)

        elif text.startswith("\x00back\x00"):
            msg = self.on_back(sender)
            self._sessions.pop(sender, None)
            if msg:
                await self._send(sender, msg)
            # Re-send menu
            conn = self.connections.get(sender)
            if conn:
                await conn.send(f"\x00session\x00" + json.dumps({"state": "ended"}))
                await self._send_menu(conn)

        elif text.startswith("\x00accept_invite\x00"):
            invite_id = text.split("\x00")[2]
            await self._handle_accept_invite(sender, invite_id)

        elif text.startswith("\x00decline_invite\x00"):
            invite_id = text.split("\x00")[2]
            await self._handle_decline_invite(sender, invite_id)

        else:
            # Regular message — forward to session
            if sender not in self._sessions:
                return
            responses = self.on_message(sender, text)
            for recipient, msg in responses:
                await self._send(recipient, msg)

    async def _handle_single_select(self, sender: str, key: str) -> None:
        """Start a single-player session."""
        try:
            opening = self.on_select(sender, key)
        except Exception as exc:
            await self._send(sender, f"Error: {exc}")
            return
        self._sessions[sender] = key
        conn = self.connections.get(sender)
        if conn:
            await conn.send(
                f"\x00session\x00" + json.dumps({"key": key, "state": "started"})
            )
        await self._send(sender, opening)

    async def _handle_multi_select(self, sender: str, key: str, opponent: str) -> None:
        """Initiate a multiplayer game — send invite to opponent."""
        invite_id = str(uuid.uuid4())[:8]
        self._pending_invites[invite_id] = {
            "game": key,
            "from": sender,
            "opponent": opponent,
        }
        # Notify the opponent
        opp_conn = self.connections.get(opponent)
        if opp_conn:
            payload = json.dumps({
                "game": key,
                "from": sender,
                "invite_id": invite_id,
            })
            await opp_conn.send(f"\x00invite_game\x00{payload}")
            await self._send(sender, f"Invite sent to {opponent}. Waiting for response...")
        else:
            await self._send(sender, f"{opponent} is not connected.")
            del self._pending_invites[invite_id]

    async def _handle_accept_invite(self, sender: str, invite_id: str) -> None:
        """Opponent accepted the invite — start the game."""
        invite = self._pending_invites.pop(invite_id, None)
        if not invite:
            await self._send(sender, "Invite expired or not found.")
            return
        challenger = invite["from"]
        key = invite["game"]
        try:
            opening = self.on_select(challenger, key, opponent=sender)
        except Exception as exc:
            await self._send(challenger, f"Error starting game: {exc}")
            await self._send(sender, f"Error starting game: {exc}")
            return
        self._sessions[challenger] = key
        self._sessions[sender] = key
        for handle in (challenger, sender):
            conn = self.connections.get(handle)
            if conn:
                await conn.send(
                    f"\x00session\x00" + json.dumps({"key": key, "state": "started"})
                )
        await self._send(challenger, opening)
        await self._send(sender, opening)

    async def _handle_decline_invite(self, sender: str, invite_id: str) -> None:
        """Opponent declined the invite."""
        invite = self._pending_invites.pop(invite_id, None)
        if not invite:
            return
        challenger = invite["from"]
        await self._send(challenger, f"{sender} declined the game.")
        await self._send(sender, "Game declined.")

    async def _send(self, handle: str, text: str) -> None:
        """Send a message to a connected client."""
        conn = self.connections.get(handle)
        if conn:
            try:
                await conn.send(text)
            except Exception as exc:
                _log.warning("send to %s failed: %s", handle, exc)
