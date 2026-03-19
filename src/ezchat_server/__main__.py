"""ezchat-server — entry point."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ezchat-server",
        description="ezchat server: STUN, TURN, rendezvous, and registry chain sync",
    )
    parser.add_argument("--config", metavar="FILE", help="Path to server.toml")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--api-port", type=int, default=8443)
    parser.add_argument("--stun-port", type=int, default=3478)

    args = parser.parse_args()

    # Phase 3+ — server implementation not yet built
    print("ezchat-server: not yet implemented (Phase 3)")


if __name__ == "__main__":
    main()
