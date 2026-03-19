"""Integration test: two-peer handshake and message exchange."""
import asyncio
import pytest

from ezchat.crypto.keys import generate_identity
from ezchat.net.connection import connect_to_peer, accept_peer


@pytest.mark.asyncio
async def test_handshake_both_sides_see_peer(tmp_path, monkeypatch):
    """Both sides complete the handshake and know each other's handle."""
    import ezchat.store.log as log_mod
    import ezchat.store.peers as peers_mod
    monkeypatch.setattr(log_mod,   "_HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(peers_mod, "_PEERS_PATH",  tmp_path / "peers.toml")

    alice = generate_identity("alice")
    bob   = generate_identity("bob")

    accepted: asyncio.Future = asyncio.get_event_loop().create_future()

    async def on_accept(r, w):
        c = await accept_peer(r, w, alice)
        accepted.set_result(c)

    server = await asyncio.start_server(on_accept, "127.0.0.1", 0)
    port   = server.sockets[0].getsockname()[1]

    bob_conn   = await connect_to_peer("127.0.0.1", port, bob)
    alice_conn = await asyncio.wait_for(accepted, timeout=5.0)

    assert alice_conn.peer_handle == "bob"
    assert bob_conn.peer_handle   == "alice"
    assert alice_conn.peer_ed_pub is not None
    assert bob_conn.peer_ed_pub   is not None

    server.close()
    await alice_conn.close()
    await bob_conn.close()


@pytest.mark.asyncio
async def test_message_round_trip(tmp_path, monkeypatch):
    """alice sends a message, bob receives it with a valid signature."""
    import ezchat.store.log as log_mod
    import ezchat.store.peers as peers_mod
    monkeypatch.setattr(log_mod,   "_HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(peers_mod, "_PEERS_PATH",  tmp_path / "peers.toml")

    alice = generate_identity("alice")
    bob   = generate_identity("bob")

    accepted: asyncio.Future = asyncio.get_event_loop().create_future()

    async def on_accept(r, w):
        c = await accept_peer(r, w, alice)
        accepted.set_result(c)

    server = await asyncio.start_server(on_accept, "127.0.0.1", 0)
    port   = server.sockets[0].getsockname()[1]

    bob_conn   = await connect_to_peer("127.0.0.1", port, bob)
    alice_conn = await asyncio.wait_for(accepted, timeout=5.0)

    await alice_conn.send("hello bob")

    frame = await asyncio.wait_for(bob_conn.recv(), timeout=5.0)
    assert frame is not None
    assert frame["text"] == "hello bob"
    assert frame["ed_sig"]  # signature present
    assert frame["ts"]       # timestamp present

    server.close()
    await alice_conn.close()
    await bob_conn.close()
