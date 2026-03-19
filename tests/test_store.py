"""Tests for ezchat.store — state persistence with Ed25519-signed logs."""
import pytest
from pathlib import Path

from ezchat.crypto.keys import generate_identity
from ezchat.store import log, peers, channels, history


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _two_identities():
    alice = generate_identity("alice")
    bob   = generate_identity("bob")
    return alice, bob


# ---------------------------------------------------------------------------
# log.py
# ---------------------------------------------------------------------------

class TestSignVerify:
    def test_round_trip(self):
        alice = generate_identity("alice")
        ts   = "2026-03-19 14:23:01"
        text = "hello world"
        sig  = log.sign_message(alice.private_key, ts, "alice", text)
        assert log.verify_sig(ts, "alice", text, sig, alice.public_key)

    def test_wrong_key_rejected(self):
        alice = generate_identity("alice")
        bob   = generate_identity("bob")
        ts    = "2026-03-19 14:23:01"
        sig   = log.sign_message(alice.private_key, ts, "alice", "hi")
        assert not log.verify_sig(ts, "alice", "hi", sig, bob.public_key)

    def test_tampered_text_rejected(self):
        alice = generate_identity("alice")
        ts  = "2026-03-19 14:23:01"
        sig = log.sign_message(alice.private_key, ts, "alice", "original")
        assert not log.verify_sig(ts, "alice", "tampered", sig, alice.public_key)

    def test_tampered_sender_rejected(self):
        alice = generate_identity("alice")
        ts  = "2026-03-19 14:23:01"
        sig = log.sign_message(alice.private_key, ts, "alice", "hi")
        assert not log.verify_sig(ts, "bob", "hi", sig, alice.public_key)

    def test_tampered_timestamp_rejected(self):
        alice = generate_identity("alice")
        sig = log.sign_message(alice.private_key, "2026-03-19 14:23:01", "alice", "hi")
        assert not log.verify_sig("2026-03-19 99:99:99", "alice", "hi", sig, alice.public_key)


class TestConvPath:
    def test_scratch(self):
        p = log.conv_path("\x00scratch")
        assert p.name == "scratch.log"

    def test_channel(self):
        p = log.conv_path("#general")
        assert p.name == "#general.log"

    def test_dm(self):
        p = log.conv_path("alice")
        assert p.name == "alice.log"


class TestAppendReadRecent:
    def test_append_and_read(self, tmp_path, monkeypatch):
        monkeypatch.setattr(log, "_HISTORY_DIR", tmp_path)

        alice = generate_identity("alice")
        ts    = "2026-03-19 14:23:01"
        sig   = log.sign_message(alice.private_key, ts, "alice", "hello")
        log.append_message("alice", ts, "alice", "hello", sig)

        entries = log.read_recent("alice")
        assert len(entries) == 1
        full_ts, hhmm, sender, text, sig_out = entries[0]
        assert full_ts == ts
        assert hhmm == "14:23"
        assert sender == "alice"
        assert text == "hello"
        assert sig_out == sig

    def test_multiple_entries_order_preserved(self, tmp_path, monkeypatch):
        monkeypatch.setattr(log, "_HISTORY_DIR", tmp_path)

        alice = generate_identity("alice")
        for i in range(5):
            ts  = f"2026-03-19 14:23:0{i}"
            sig = log.sign_message(alice.private_key, ts, "alice", f"msg{i}")
            log.append_message("alice", ts, "alice", f"msg{i}", sig)

        entries = log.read_recent("alice")
        assert len(entries) == 5
        assert [e[3] for e in entries] == [f"msg{i}" for i in range(5)]

    def test_read_recent_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(log, "_HISTORY_DIR", tmp_path)

        alice = generate_identity("alice")
        for i in range(10):
            ts  = f"2026-03-19 14:23:{i:02d}"
            sig = log.sign_message(alice.private_key, ts, "alice", f"msg{i}")
            log.append_message("alice", ts, "alice", f"msg{i}", sig)

        entries = log.read_recent("alice", n=3)
        assert len(entries) == 3
        assert entries[0][3] == "msg7"
        assert entries[2][3] == "msg9"

    def test_missing_log_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(log, "_HISTORY_DIR", tmp_path)
        assert log.read_recent("nonexistent") == []


class TestVerifyLog:
    def test_all_valid(self, tmp_path, monkeypatch):
        monkeypatch.setattr(log, "_HISTORY_DIR", tmp_path)

        alice = generate_identity("alice")
        for i in range(3):
            ts  = f"2026-03-19 14:23:0{i}"
            sig = log.sign_message(alice.private_key, ts, "alice", f"msg{i}")
            log.append_message("alice", ts, "alice", f"msg{i}", sig)

        results = log.verify_log("alice", {"alice": alice.public_key})
        assert all(ok for _, ok, _, _ in results)
        assert len(results) == 3

    def test_tampered_line_detected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(log, "_HISTORY_DIR", tmp_path)

        alice = generate_identity("alice")
        ts  = "2026-03-19 14:23:00"
        sig = log.sign_message(alice.private_key, ts, "alice", "original text")
        log.append_message("alice", ts, "alice", "original text", sig)

        # Tamper the log file directly
        path = log.conv_path("alice")
        content = path.read_text()
        path.write_text(content.replace("original text", "tampered text"))

        results = log.verify_log("alice", {"alice": alice.public_key})
        assert len(results) == 1
        _lineno, ok, _sender, _raw = results[0]
        assert not ok

    def test_unknown_sender_fails(self, tmp_path, monkeypatch):
        monkeypatch.setattr(log, "_HISTORY_DIR", tmp_path)

        alice = generate_identity("alice")
        ts  = "2026-03-19 14:23:00"
        sig = log.sign_message(alice.private_key, ts, "alice", "hi")
        log.append_message("alice", ts, "alice", "hi", sig)

        # Verify with empty pubkey map — alice's key not provided
        results = log.verify_log("alice", {})
        assert not results[0][1]

    def test_missing_log_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(log, "_HISTORY_DIR", tmp_path)
        assert log.verify_log("nobody", {}) == []

    def test_unsigned_entry_fails(self, tmp_path, monkeypatch):
        monkeypatch.setattr(log, "_HISTORY_DIR", tmp_path)

        alice = generate_identity("alice")
        log.append_message("alice", "2026-03-19 14:23:00", "alice", "hi", "UNSIGNED")

        results = log.verify_log("alice", {"alice": alice.public_key})
        assert not results[0][1]


# ---------------------------------------------------------------------------
# peers.py
# ---------------------------------------------------------------------------

class TestPeers:
    def test_upsert_and_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr(peers, "_PEERS_PATH", tmp_path / "peers.toml")

        alice = generate_identity("alice")
        peers.upsert_peer("alice", alice.public_key, ip_hint="192.168.1.5")

        loaded = peers.load_peers()
        assert "alice" in loaded
        rec = loaded["alice"]
        assert rec.handle == "alice"
        assert rec.ip_hint == "192.168.1.5"
        assert rec.ed25519_pub_b64

    def test_get_pubkeys(self, tmp_path, monkeypatch):
        monkeypatch.setattr(peers, "_PEERS_PATH", tmp_path / "peers.toml")

        alice = generate_identity("alice")
        peers.upsert_peer("alice", alice.public_key)

        pubkeys = peers.get_pubkeys()
        assert "alice" in pubkeys
        # The restored pubkey should verify alice's signatures
        ts  = "2026-03-19 14:23:00"
        sig = log.sign_message(alice.private_key, ts, "alice", "hi")
        assert log.verify_sig(ts, "alice", "hi", sig, pubkeys["alice"])

    def test_upsert_overwrites(self, tmp_path, monkeypatch):
        monkeypatch.setattr(peers, "_PEERS_PATH", tmp_path / "peers.toml")

        alice = generate_identity("alice")
        peers.upsert_peer("alice", alice.public_key, ip_hint="10.0.0.1")
        peers.upsert_peer("alice", alice.public_key, ip_hint="10.0.0.2")

        loaded = peers.load_peers()
        assert loaded["alice"].ip_hint == "10.0.0.2"

    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(peers, "_PEERS_PATH", tmp_path / "nonexistent.toml")
        assert peers.load_peers() == {}

    def test_multiple_peers(self, tmp_path, monkeypatch):
        monkeypatch.setattr(peers, "_PEERS_PATH", tmp_path / "peers.toml")

        alice = generate_identity("alice")
        bob   = generate_identity("bob")
        peers.upsert_peer("alice", alice.public_key)
        peers.upsert_peer("bob",   bob.public_key)

        loaded = peers.load_peers()
        assert set(loaded.keys()) == {"alice", "bob"}


# ---------------------------------------------------------------------------
# channels.py
# ---------------------------------------------------------------------------

class TestChannels:
    def test_save_and_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr(channels, "_CHANNELS_PATH", tmp_path / "channels.toml")

        data = {"general": ["alice", "bob"], "devops": ["alice"]}
        channels.save_channels(data)

        loaded = channels.load_channels()
        assert loaded == data

    def test_empty_channels(self, tmp_path, monkeypatch):
        monkeypatch.setattr(channels, "_CHANNELS_PATH", tmp_path / "channels.toml")
        channels.save_channels({})
        assert channels.load_channels() == {}

    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(channels, "_CHANNELS_PATH", tmp_path / "nonexistent.toml")
        assert channels.load_channels() == {}

    def test_members_order_preserved(self, tmp_path, monkeypatch):
        monkeypatch.setattr(channels, "_CHANNELS_PATH", tmp_path / "channels.toml")

        members = ["carol", "alice", "bob"]
        channels.save_channels({"team": members})

        loaded = channels.load_channels()
        assert loaded["team"] == members


# ---------------------------------------------------------------------------
# history.py
# ---------------------------------------------------------------------------

class TestHistory:
    def test_save_and_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr(history, "_HISTORY_PATH", tmp_path / "command_history.txt")

        cmds = ["/theme phosphor_green", "/channel create dev", "/help"]
        history.save_cmd_history(cmds)

        loaded = history.load_cmd_history()
        assert loaded == cmds

    def test_max_lines_enforced(self, tmp_path, monkeypatch):
        monkeypatch.setattr(history, "_HISTORY_PATH", tmp_path / "command_history.txt")
        monkeypatch.setattr(history, "_MAX_LINES", 5)

        cmds = [f"/cmd{i}" for i in range(10)]
        history.save_cmd_history(cmds)

        loaded = history.load_cmd_history()
        assert loaded == cmds[-5:]

    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(history, "_HISTORY_PATH", tmp_path / "nonexistent.txt")
        assert history.load_cmd_history() == []

    def test_empty_lines_stripped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(history, "_HISTORY_PATH", tmp_path / "command_history.txt")

        history.save_cmd_history(["/cmd1", "", "/cmd2"])
        loaded = history.load_cmd_history()
        assert "" not in loaded
        assert "/cmd1" in loaded
        assert "/cmd2" in loaded


# ---------------------------------------------------------------------------
# End-to-end: sign → persist → reload → verify
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_sign_persist_reload_verify(self, tmp_path, monkeypatch):
        """Full cycle: sign a message, write it to disk, reload it, verify the sig."""
        monkeypatch.setattr(log, "_HISTORY_DIR", tmp_path)
        monkeypatch.setattr(peers, "_PEERS_PATH", tmp_path / "peers.toml")

        alice = generate_identity("alice")
        bob   = generate_identity("bob")

        # Alice sends a message to bob
        ts  = log.now_ts()
        sig = log.sign_message(alice.private_key, ts, "alice", "hey bob")
        log.append_message("bob", ts, "alice", "hey bob", sig)

        # Store alice's pubkey (as bob would on connect)
        peers.upsert_peer("alice", alice.public_key, ip_hint="192.168.1.10")

        # Later: reload pubkeys and verify the log
        pubkeys = peers.get_pubkeys()
        results = log.verify_log("bob", pubkeys)

        assert len(results) == 1
        _lineno, ok, sender, _raw = results[0]
        assert ok
        assert sender == "alice"

    def test_tampered_log_detected_end_to_end(self, tmp_path, monkeypatch):
        """Tampering with the log file is detectable on verify."""
        monkeypatch.setattr(log, "_HISTORY_DIR", tmp_path)
        monkeypatch.setattr(peers, "_PEERS_PATH", tmp_path / "peers.toml")

        alice = generate_identity("alice")
        peers.upsert_peer("alice", alice.public_key)

        ts  = "2026-03-19 14:23:00"
        sig = log.sign_message(alice.private_key, ts, "alice", "i said X")
        log.append_message("bob", ts, "alice", "i said X", sig)

        # Attacker edits the log to change what alice said
        path = log.conv_path("bob")
        path.write_text(path.read_text().replace("i said X", "i said Y"))

        pubkeys = peers.get_pubkeys()
        results = log.verify_log("bob", pubkeys)
        assert not results[0][1]   # forgery detected
