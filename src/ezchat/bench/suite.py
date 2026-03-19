"""Benchmark suite — grows one section per phase.

Phase 1 : UI / theme loading
Phase 2 : crypto primitives  (added when crypto module lands)
Phase 3 : message round-trip (added when network layer lands)
Phase 4 : chain ops          (added when registry lands)
Phase 5 : file transfer      (added when file module lands)
Phase 6 : AI latency         (added when AI module lands)

Run with:
    uv run ezchat --bench
"""
from __future__ import annotations

import sys

from ezchat.bench.timer import BenchReport, Timer


# ---------------------------------------------------------------------------
# Phase 1 — UI / theme loading
# ---------------------------------------------------------------------------
_ITERATIONS = 100   # repeat each measurement N times for stable averages


def _bench_themes(report: BenchReport) -> None:
    from ezchat.ui.theme import list_themes, load_theme

    themes = list_themes()

    # Cold load (first import already happened, but TOML parse is fresh)
    for name in themes:
        with report.measure(f"load_theme({name})"):
            load_theme(name)

    # Warm: average over N iterations
    total_ns = 0
    for _ in range(_ITERATIONS):
        with Timer() as t:
            for name in themes:
                load_theme(name)
        total_ns += t.elapsed_ns

    from ezchat.bench.timer import TimerResult
    avg_ns = total_ns // _ITERATIONS
    report.add(TimerResult(f"all themes ×{_ITERATIONS} (avg)", avg_ns))


# ---------------------------------------------------------------------------
# Phase 2 — crypto primitives
# ---------------------------------------------------------------------------
def _bench_crypto(report: BenchReport) -> None:
    from ezchat.crypto.keys import generate_identity, generate_ephemeral
    from ezchat.crypto.session import SessionKey, derive_session_key

    # Ed25519 keygen
    with report.measure("Ed25519 keygen"):
        identity = generate_identity("bench")

    # X25519 ephemeral keygen
    with report.measure("X25519 keygen"):
        eph = generate_ephemeral()

    # Sign + verify
    msg = b"hello ezchat"
    with report.measure("Ed25519 sign"):
        sig = identity.sign(msg)

    # Full ECDH + HKDF (both sides)
    alice = generate_ephemeral()
    bob   = generate_ephemeral()
    with report.measure("X25519 ECDH + HKDF"):
        secret = alice.exchange(bob.pub_bytes)
        key_bytes = derive_session_key(secret, alice.pub_bytes, bob.pub_bytes)

    session = SessionKey(key_bytes)

    # AES-256-GCM encrypt (short message)
    plaintext = b"Hello, this is a test message for benchmarking."
    with report.measure("AES-256-GCM encrypt (48 B)"):
        ct = session.encrypt(plaintext)

    with report.measure("AES-256-GCM decrypt (48 B)"):
        session.decrypt(ct)

    # Larger payload
    payload_1k = b"x" * 1024
    with report.measure("AES-256-GCM encrypt (1 KB)"):
        ct_1k = session.encrypt(payload_1k)

    with report.measure("AES-256-GCM decrypt (1 KB)"):
        session.decrypt(ct_1k)

    # Averaged over N iterations
    from ezchat.bench.timer import TimerResult
    total_ns = 0
    for _ in range(_ITERATIONS):
        with Timer() as t:
            ct = session.encrypt(plaintext)
            session.decrypt(ct)
        total_ns += t.elapsed_ns
    report.add(TimerResult(f"enc+dec round-trip ×{_ITERATIONS} (avg)", total_ns // _ITERATIONS))


# ---------------------------------------------------------------------------
# Suite entry point
# ---------------------------------------------------------------------------
def run_suite(args) -> None:  # noqa: ANN001
    print(f"\n  ezchat bench  —  Python {sys.version.split()[0]}")

    # --- Phase 1: UI / themes ---
    report1 = BenchReport("Phase 1 — UI / theme loading")
    _bench_themes(report1)
    report1.print()

    # --- Phase 2: crypto ---
    report2 = BenchReport("Phase 2 — crypto primitives")
    _bench_crypto(report2)
    report2.print()

    _pending = [
        "Phase 3 — network round-trip (LAN loopback)",
        "Phase 4 — registry chain (block append, verify)",
        "Phase 5 — file transfer (1 MB chunk throughput)",
        "Phase 6 — AI first-token latency",
    ]
    print()
    for label in _pending:
        print(f"  [ pending ] {label}")
    print()
