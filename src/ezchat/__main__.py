"""ezchat — entry point."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ezchat",
        description="P2P end-to-end encrypted terminal chat",
    )

    # --- modes ---
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--test",
        action="store_true",
        help="Start in test mode with a built-in echo-bot peer (no network required)",
    )
    mode.add_argument(
        "--echo-server",
        action="store_true",
        help="Run as a headless echo agent (uses agent runner internally)",
    )
    mode.add_argument(
        "--agent",
        metavar="SCRIPT",
        help="Run as a headless agent with the given handler script",
    )
    mode.add_argument(
        "--bench",
        action="store_true",
        help="Run the latency benchmark suite",
    )

    # --- identity ---
    parser.add_argument("--handle", metavar="NAME", help="Your display name (default: you)")
    parser.add_argument("--theme",  metavar="NAME", help="UI theme to load on startup")

    # --- connection ---
    parser.add_argument("--connect", metavar="HANDLE_OR_ADDR", help="Connect to a peer")
    parser.add_argument("--listen",  metavar="PORT", type=int,  help="Listen for incoming connections")
    parser.add_argument("--server",  metavar="URL",             help="ezchat-server URL")

    # --- test mode options ---
    parser.add_argument("--echo-delay",  metavar="MS",   type=int, default=0, help="Simulated echo latency (ms)")
    parser.add_argument("--echo-script", metavar="FILE",           help="Scripted echo responses file")

    # --- bench options ---
    parser.add_argument("--target", metavar="HANDLE_OR_ADDR", help="Benchmark target peer")

    args = parser.parse_args()

    if args.test:
        from ezchat.ui.app import run_test_mode
        run_test_mode(args)
    elif args.bench:
        from ezchat.bench.suite import run_suite
        run_suite(args)
    elif args.echo_server:
        from ezchat.agent.runner import run_builtin_echo
        run_builtin_echo(args)
    elif args.agent:
        from ezchat.agent.runner import run_agent
        run_agent(args)
    else:
        from ezchat.ui.app import run
        run(args)


if __name__ == "__main__":
    main()
