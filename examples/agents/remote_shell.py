"""
kirbus agent archetype: Remote Shell
-------------------------------------
Forwards messages to a local bash process and streams output back.
Turns the kirbus chat window into a secure remote terminal.

Equivalent to SSH or Raspberry Pi Connect, but:
  - E2E encrypted through the kirbus session key
  - No open ports required — NAT traversal handled by kirbus ICE
  - Gated by allowed_handles — only listed users can connect

Run:
    kirbus --agent --script remote_shell.py --server https://chat.internal:8443

Config (~/.kirbus/config.toml):
    [agent]
    allowed_handles = ["@yourhandle"]   # IMPORTANT: keep this list tight
    description     = "Remote shell"

Security note:
    This gives trusted senders full shell access on this machine.
    Keep allowed_handles to the minimum necessary.
    Consider running as a dedicated low-privilege user.
"""

import subprocess

TRUSTED = {"@yourhandle"}   # replace with your own handle

_proc: subprocess.Popen | None = None


def _get_proc() -> subprocess.Popen:
    global _proc
    if _proc is None or _proc.poll() is not None:
        _proc = subprocess.Popen(
            ["/bin/bash"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    return _proc


def on_message(sender: str, message: str) -> str | None:
    if sender not in TRUSTED:
        return None

    if message.strip() == "exit":
        global _proc
        if _proc:
            _proc.terminate()
            _proc = None
        return "(shell session closed)"

    proc = _get_proc()

    try:
        proc.stdin.write((message + "\n").encode())
        proc.stdin.flush()
        output = proc.stdout.read1(4096).decode(errors="replace")
        return output.rstrip() or "(no output)"
    except BrokenPipeError:
        _proc = None
        return "(shell process died — reconnecting on next command)"
