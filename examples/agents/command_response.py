"""
kirbus agent archetype: Command / Response
------------------------------------------
Receives a message, performs an action, returns a result.

Run:
    kirbus --agent --script command_response.py --server https://chat.internal:8443

Config (~/.kirbus/config.toml):
    [agent]
    allowed_handles = ["@yourhandle"]
    description     = "Command/response example agent"

Adapt this template to control anything that has a Python API:
home automation, GPIO, databases, external services, etc.
kirbus delivers the string; you decide what it means.
"""

# ---------------------------------------------------------------------------
# Authorization — always check sender before acting.
# sender is cryptographically verified by the kirbus handshake.
# ---------------------------------------------------------------------------
TRUSTED = {"@yourhandle"}   # replace with the handles you want to allow


def on_message(sender: str, message: str) -> str | None:
    if sender not in TRUSTED:
        return None   # reveal nothing to unknown senders

    message = message.strip().lower()

    if message == "help":
        return (
            "Available commands:\n"
            "  hello       — ping the agent\n"
            "  status      — report agent status\n"
            "  help        — show this message"
        )

    if message == "hello":
        return "Hello! Agent is online."

    if message == "status":
        return "Status: OK"

    # Add your own commands here:
    # if message == "lights on":
    #     your_api_call()
    #     return "Lights on ✓"

    return f"Unknown command: {message!r} — try 'help'"
