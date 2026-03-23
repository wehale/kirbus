"""
kirbus agent archetype: Notification / Push
--------------------------------------------
Watches an external system in the background and pushes messages into chat
when something happens. The agent initiates messages rather than waiting
for them.

Run:
    kirbus --agent --script notification_push.py --server https://chat.internal:8443

Config (~/.kirbus/config.toml):
    [agent]
    allowed_handles = ["@yourhandle"]
    description     = "Notification/push example agent"

How it works:
    kirbus calls on_start(send) once after the peer connects, passing a
    send(message) coroutine. Your watch loop calls send() whenever it has
    something to report. on_message handles any replies from the peer.
"""

import asyncio

TRUSTED = {"@yourhandle"}

# ---------------------------------------------------------------------------
# Background watch loop — adapt to whatever you want to monitor.
# ---------------------------------------------------------------------------

async def on_start(send) -> None:
    """Called once when a peer connects. send(msg) pushes a message to them."""
    await send("Notification agent online. Watching for events...")
    asyncio.create_task(_watch_loop(send))


async def _watch_loop(send) -> None:
    """
    Replace this loop with real monitoring logic:
      - Poll a CI/CD API for build status changes
      - Watch a log file for error patterns
      - Check sensor readings against thresholds
      - Monitor a URL for availability
    """
    previous_status = None

    while True:
        current_status = await _check_something()

        if current_status != previous_status:
            await send(f"Status changed: {previous_status!r} → {current_status!r}")
            previous_status = current_status

        await asyncio.sleep(30)   # poll interval


async def _check_something() -> str:
    """
    Replace with your actual check.
    Return a value that represents the current state —
    the loop sends a message whenever this value changes.
    """
    # Example: check an HTTP endpoint
    # async with aiohttp.ClientSession() as s:
    #     r = await s.get("https://api.example.com/status")
    #     data = await r.json()
    #     return data["status"]
    return "ok"


# ---------------------------------------------------------------------------
# on_message handles replies from the peer (e.g. "stop", "status").
# ---------------------------------------------------------------------------

def on_message(sender: str, message: str) -> str | None:
    if sender not in TRUSTED:
        return None

    if message.strip().lower() == "status":
        return "Watch loop running."

    return None   # ignore other messages
