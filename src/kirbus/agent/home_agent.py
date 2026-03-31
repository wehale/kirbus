"""Home agent — smart home control via kirbus.

Presents IoT devices as a menu. Selecting a device starts a session
where you can send commands (on/off, dim, set temp, lock/unlock, etc.).

Behind the scenes, commands are sent to a Matter bridge-app via chip-tool.
The Baby Monitor device plays a baby cry through a USB speaker and listens
for Matter BooleanState events from an E84 running ML inference.

Run with:
    kirbus --agent home --server http://SERVER:8000 --handle my-house
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from kirbus.agent.menu import MenuAgent, MenuEntry
from kirbus.net.connection import Connection

_log = logging.getLogger(__name__)

# Audio config — override with env vars
AUDIO_DEVICE = os.environ.get("KIRBUS_AUDIO_DEVICE", "plughw:3,0")
BABYCRY_FILE = os.environ.get("KIRBUS_BABYCRY_FILE", str(Path.home() / "babycry.wav"))


# ---------------------------------------------------------------------------
# Device definitions
# ---------------------------------------------------------------------------
@dataclass
class Device:
    key: str
    name: str
    type: str          # "light" | "thermostat" | "lock" | "garage" | "switch"
    endpoint: int = 0  # Matter endpoint ID (for chip-tool)
    state: dict = field(default_factory=dict)

    def default_state(self) -> None:
        if self.type == "baby_cry":
            self.state = {"playing": False}
        elif self.type == "baby_monitor":
            self.state = {"cry_detected": False, "last_detection": None}
        elif self.type == "light":
            self.state = {"on": False, "brightness": 100}
        elif self.type == "thermostat":
            self.state = {"mode": "auto", "target": 72, "current": 71}
        elif self.type == "lock":
            self.state = {"locked": True}
        elif self.type == "garage":
            self.state = {"open": False}
        elif self.type == "switch":
            self.state = {"on": False}


# The house
DEVICES = [
    Device("baby_cry",      "Baby Cry",           "baby_cry",     endpoint=0),
    Device("baby_monitor",  "Baby Monitor",        "baby_monitor", endpoint=0),
    Device("living_light",  "Living Room Light",  "light",        endpoint=2),
    Device("kitchen_light", "Kitchen Light",      "light",        endpoint=3),
    Device("bedroom_light", "Bedroom Light",      "light",        endpoint=4),
    Device("thermostat",    "Thermostat",         "thermostat",   endpoint=5),
    Device("front_lock",    "Front Door Lock",    "lock",         endpoint=6),
    Device("garage",        "Garage Door",        "garage",       endpoint=7),
    Device("porch_light",   "Porch Light",        "light",        endpoint=8),
]


# ---------------------------------------------------------------------------
# Matter backend (swappable — simulated for now)
# ---------------------------------------------------------------------------
class MatterBackend:
    """Interface for controlling Matter devices. Subclass for real chip-tool."""

    def send_command(self, device: Device, command: str, args: dict) -> str:
        """Send a command to a device. Returns status message."""
        if device.type == "baby_cry":
            return self._handle_baby_cry(device, command, args)
        elif device.type == "baby_monitor":
            return self._handle_baby_monitor(device, command, args)
        elif device.type == "light":
            return self._handle_light(device, command, args)
        elif device.type == "thermostat":
            return self._handle_thermostat(device, command, args)
        elif device.type == "lock":
            return self._handle_lock(device, command, args)
        elif device.type == "garage":
            return self._handle_garage(device, command, args)
        elif device.type == "switch":
            return self._handle_switch(device, command, args)
        return "Unknown device type."

    def _handle_baby_cry(self, dev: Device, cmd: str, args: dict) -> str:
        if cmd == "play":
            if not Path(BABYCRY_FILE).exists():
                return f"Audio file not found: {BABYCRY_FILE}"
            dev.state["playing"] = True
            try:
                subprocess.Popen(
                    ["aplay", "-D", AUDIO_DEVICE, BABYCRY_FILE],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return "Playing baby cry audio..."
            except Exception as e:
                dev.state["playing"] = False
                return f"Failed to play audio: {e}"
        elif cmd == "stop":
            dev.state["playing"] = False
            subprocess.run(["pkill", "-f", f"aplay.*{BABYCRY_FILE}"],
                           capture_output=True)
            return "Stopped audio playback."
        elif cmd == "status":
            playing = "PLAYING" if dev.state["playing"] else "idle"
            return f"Baby Cry: {playing}"
        return f"Unknown command: {cmd}. Try: play, stop, status"

    def _handle_baby_monitor(self, dev: Device, cmd: str, args: dict) -> str:
        if cmd == "status":
            detected = "YES" if dev.state["cry_detected"] else "no"
            last = dev.state["last_detection"] or "never"
            return (
                f"Baby Monitor: listening\n"
                f"  Cry detected: {detected}\n"
                f"  Last detection: {last}"
            )
        return f"Unknown command: {cmd}. Try: status"

    def _handle_light(self, dev: Device, cmd: str, args: dict) -> str:
        if cmd == "on":
            dev.state["on"] = True
            return f"{dev.name}: ON (brightness {dev.state['brightness']}%)"
        elif cmd == "off":
            dev.state["on"] = False
            return f"{dev.name}: OFF"
        elif cmd == "dim":
            level = args.get("level", 50)
            dev.state["brightness"] = max(0, min(100, level))
            dev.state["on"] = level > 0
            return f"{dev.name}: brightness set to {dev.state['brightness']}%"
        elif cmd == "status":
            on = "ON" if dev.state["on"] else "OFF"
            return f"{dev.name}: {on}, brightness {dev.state['brightness']}%"
        return f"Unknown command for light: {cmd}"

    def _handle_thermostat(self, dev: Device, cmd: str, args: dict) -> str:
        if cmd == "set":
            temp = args.get("temp", 72)
            dev.state["target"] = max(60, min(85, temp))
            return f"{dev.name}: target set to {dev.state['target']}F (current: {dev.state['current']}F)"
        elif cmd == "mode":
            mode = args.get("mode", "auto")
            if mode in ("heat", "cool", "auto", "off"):
                dev.state["mode"] = mode
                return f"{dev.name}: mode set to {mode}"
            return f"Invalid mode. Options: heat, cool, auto, off"
        elif cmd == "status":
            return (
                f"{dev.name}: {dev.state['mode']} mode\n"
                f"  Target: {dev.state['target']}F\n"
                f"  Current: {dev.state['current']}F"
            )
        return f"Unknown command for thermostat: {cmd}"

    def _handle_lock(self, dev: Device, cmd: str, args: dict) -> str:
        if cmd == "lock":
            dev.state["locked"] = True
            return f"{dev.name}: LOCKED"
        elif cmd == "unlock":
            dev.state["locked"] = False
            return f"{dev.name}: UNLOCKED"
        elif cmd == "status":
            status = "LOCKED" if dev.state["locked"] else "UNLOCKED"
            return f"{dev.name}: {status}"
        return f"Unknown command for lock: {cmd}"

    def _handle_garage(self, dev: Device, cmd: str, args: dict) -> str:
        if cmd == "open":
            dev.state["open"] = True
            return f"{dev.name}: OPENING..."
        elif cmd == "close":
            dev.state["open"] = False
            return f"{dev.name}: CLOSING..."
        elif cmd == "status":
            status = "OPEN" if dev.state["open"] else "CLOSED"
            return f"{dev.name}: {status}"
        return f"Unknown command for garage: {cmd}"

    def _handle_switch(self, dev: Device, cmd: str, args: dict) -> str:
        if cmd == "on":
            dev.state["on"] = True
            return f"{dev.name}: ON"
        elif cmd == "off":
            dev.state["on"] = False
            return f"{dev.name}: OFF"
        elif cmd == "status":
            status = "ON" if dev.state["on"] else "OFF"
            return f"{dev.name}: {status}"
        return f"Unknown command for switch: {cmd}"


class ChipToolBackend(MatterBackend):
    """Real Matter backend using chip-tool. TODO: wire up when Matter is compiled."""

    def __init__(self, chip_tool_path: str = "chip-tool", node_id: int = 1):
        self._chip_tool = chip_tool_path
        self._node_id = node_id

    def send_command(self, device: Device, command: str, args: dict) -> str:
        # TODO: implement real chip-tool calls
        # Example: chip-tool onoff on <node-id> <endpoint>
        # For now, fall back to simulated
        return super().send_command(device, command, args)


# ---------------------------------------------------------------------------
# Home agent
# ---------------------------------------------------------------------------
class HomeAgent(MenuAgent):
    """Presents smart home devices as a menu with interactive control."""

    def __init__(self, backend: MatterBackend | None = None) -> None:
        super().__init__()
        self._backend = backend or MatterBackend()
        self._devices: dict[str, Device] = {}
        for dev in DEVICES:
            d = Device(dev.key, dev.name, dev.type, dev.endpoint)
            d.default_state()
            self._devices[d.key] = d
        self._active: dict[str, str] = {}  # handle → device key

    def broadcast(self, message: str) -> None:
        """Send a message to all connected clients."""
        for handle, conn in list(self.connections.items()):
            try:
                asyncio.get_event_loop().create_task(conn.send(message))
            except Exception:
                pass

    def get_title(self) -> str:
        return "my-house"

    def get_entries(self) -> list[MenuEntry]:
        entries = []
        for dev in self._devices.values():
            entries.append(MenuEntry(key=dev.key, label=dev.name, type="single"))
        return entries

    def on_select(self, sender: str, key: str, opponent: str | None = None) -> str:
        dev = self._devices.get(key)
        if not dev:
            return "Device not found."
        self._active[sender] = key
        return self._device_prompt(dev)

    def on_message(self, sender: str, text: str) -> list[tuple[str, str]]:
        dev_key = self._active.get(sender)
        if not dev_key:
            return [(sender, "No device selected.")]
        dev = self._devices[dev_key]
        result = self._handle_command(dev, text.strip())
        return [(sender, result)]

    def on_back(self, sender: str) -> str | None:
        self._active.pop(sender, None)
        return None

    def _device_prompt(self, dev: Device) -> str:
        lines = [f"=== {dev.name} ===", ""]
        if dev.type == "baby_cry":
            playing = "PLAYING" if dev.state["playing"] else "idle"
            lines.append(f"Status: {playing}")
            lines.append("")
            lines.append("Commands: play, stop, status")
        elif dev.type == "baby_monitor":
            detected = "YES" if dev.state["cry_detected"] else "no"
            last = dev.state["last_detection"] or "never"
            lines.append("Status: listening")
            lines.append(f"Cry detected: {detected}")
            lines.append(f"Last detection: {last}")
            lines.append("")
            lines.append("Waiting for baby cry detection from E84...")
        elif dev.type == "light":
            on = "ON" if dev.state["on"] else "OFF"
            lines.append(f"Status: {on}, brightness {dev.state['brightness']}%")
            lines.append("")
            lines.append("Commands: on, off, dim <0-100>, status")
        elif dev.type == "thermostat":
            lines.append(f"Mode: {dev.state['mode']}")
            lines.append(f"Target: {dev.state['target']}F  Current: {dev.state['current']}F")
            lines.append("")
            lines.append("Commands: set <temp>, mode <heat|cool|auto|off>, status")
        elif dev.type == "lock":
            status = "LOCKED" if dev.state["locked"] else "UNLOCKED"
            lines.append(f"Status: {status}")
            lines.append("")
            lines.append("Commands: lock, unlock, status")
        elif dev.type == "garage":
            status = "OPEN" if dev.state["open"] else "CLOSED"
            lines.append(f"Status: {status}")
            lines.append("")
            lines.append("Commands: open, close, status")
        elif dev.type == "switch":
            status = "ON" if dev.state["on"] else "OFF"
            lines.append(f"Status: {status}")
            lines.append("")
            lines.append("Commands: on, off, status")
        return "\n".join(lines)

    def _handle_command(self, dev: Device, text: str) -> str:
        parts = text.lower().split()
        if not parts:
            return self._device_prompt(dev)
        cmd = parts[0]

        if cmd == "help":
            return self._device_prompt(dev)

        args: dict = {}
        if cmd == "dim" and len(parts) > 1 and parts[1].isdigit():
            args["level"] = int(parts[1])
        elif cmd == "set" and len(parts) > 1 and parts[1].isdigit():
            args["temp"] = int(parts[1])
        elif cmd == "mode" and len(parts) > 1:
            args["mode"] = parts[1]

        return self._backend.send_command(dev, cmd, args)


# ---------------------------------------------------------------------------
# Matter BooleanState subscription listener
# ---------------------------------------------------------------------------
class MatterSubscription:
    """Subscribes to Matter BooleanState events via chip-tool.

    When the E84 detects a baby cry, it sets BooleanState to true.
    chip-tool subscribe picks this up and we notify all connected clients.
    """

    def __init__(self, agent: HomeAgent, chip_tool: str, node_id: int, endpoint: int):
        self._agent = agent
        self._chip_tool = chip_tool
        self._node_id = node_id
        self._endpoint = endpoint
        self._proc: subprocess.Popen | None = None

    async def start(self) -> None:
        """Start the subscription in background."""
        chip_tool = Path(self._chip_tool)
        if not chip_tool.exists():
            _log.warning("chip-tool not found at %s — Matter subscription disabled", self._chip_tool)
            return
        asyncio.get_event_loop().run_in_executor(None, self._subscribe_loop)

    def _subscribe_loop(self) -> None:
        """Blocking loop that runs chip-tool subscribe and watches output."""
        import time
        while True:
            try:
                self._proc = subprocess.Popen(
                    [
                        self._chip_tool,
                        "booleanstate", "subscribe", "state-value",
                        str(self._node_id), str(self._endpoint),
                        "1", "30",  # min/max interval seconds
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for line in self._proc.stdout:
                    line = line.strip()
                    if "StateValue" in line and "TRUE" in line.upper():
                        self._on_cry_detected()
                    elif "StateValue" in line and "FALSE" in line.upper():
                        self._on_cry_cleared()
                self._proc.wait()
            except Exception as e:
                _log.debug("Matter subscription error: %s", e)
            time.sleep(5)  # retry delay

    def _on_cry_detected(self) -> None:
        from datetime import datetime
        dev = self._agent._devices.get("baby_monitor")
        if dev:
            dev.state["cry_detected"] = True
            dev.state["last_detection"] = datetime.now().strftime("%H:%M:%S")
            _log.info("Baby cry detected via Matter!")
            # Notify all connected clients
            self._agent.broadcast("ALERT: Baby cry detected!")

    def _on_cry_cleared(self) -> None:
        dev = self._agent._devices.get("baby_monitor")
        if dev:
            dev.state["cry_detected"] = False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def run_home_agent(identity, server: str) -> None:
    """Connect to the mesh and handle home control sessions via HTTP proxy."""
    from kirbus.net.rendezvous_client import RendezvousClient
    import json
    import urllib.request

    agent = HomeAgent()

    rdv = RendezvousClient(server, identity)

    # Register with rendezvous
    pub_ip = await rdv.my_public_ip() or "127.0.0.1"
    endpoint = f"{pub_ip}:0"
    await rdv.register(endpoint)
    rdv.start_keepalive(endpoint)
    _log.info("home agent registered as %s", identity.handle)

    # Register menu with server
    entries = agent.get_entries()
    menu_data = {
        "title": agent.get_title(),
        "entries": [{"key": e.key, "label": e.label, "type": e.type} for e in entries],
    }
    await rdv.register_agent_menu(identity.handle, menu_data)

    print(f"home agent online as @{identity.handle}")

    # Start Matter BooleanState subscription if chip-tool is available
    chip_tool_path = os.environ.get(
        "KIRBUS_CHIP_TOOL",
        os.path.expanduser("~/git/connectedhomeip/examples/chip-tool/out/debug/chip-tool"),
    )
    matter_node_id = int(os.environ.get("KIRBUS_MATTER_NODE", "1"))
    matter_endpoint = int(os.environ.get("KIRBUS_MATTER_ENDPOINT", "1"))
    sub = MatterSubscription(agent, chip_tool_path, matter_node_id, matter_endpoint)
    asyncio.create_task(sub.start())

    def _send_reply(to: str, text: str) -> None:
        """Send a reply to a client via the server HTTP proxy."""
        try:
            data = json.dumps({"from": identity.handle, "to": to, "text": text}).encode()
            req = urllib.request.Request(
                f"{server}/agent/reply",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            _log.debug("reply send failed: %s", e)

    async def _poll_loop() -> None:
        """Long-poll the server for incoming messages from clients."""
        loop = asyncio.get_event_loop()
        while True:
            try:
                def _fetch():
                    try:
                        req = urllib.request.Request(f"{server}/agent/{identity.handle}/recv")
                        resp = urllib.request.urlopen(req, timeout=35)
                        if resp.status == 204:
                            return None
                        return json.loads(resp.read().decode())
                    except Exception:
                        return None

                msg = await loop.run_in_executor(None, _fetch)
                if not msg or msg.get("empty"):
                    continue

                sender = msg["from"]
                text = msg["text"]

                # Route through the agent's protocol handler
                if text.startswith("\x00select\x00"):
                    parts = text.split("\x00")
                    key = parts[2]
                    opponent = parts[4] if len(parts) > 4 else None
                    opening = agent.on_select(sender, key, opponent)
                    await loop.run_in_executor(None, _send_reply, sender, opening)

                elif text.startswith("\x00back\x00"):
                    msg_back = agent.on_back(sender)
                    if msg_back:
                        await loop.run_in_executor(None, _send_reply, sender, msg_back)

                else:
                    # Regular message — forward to session
                    responses = agent.on_message(sender, text)
                    for recipient, reply_text in responses:
                        await loop.run_in_executor(None, _send_reply, recipient, reply_text)

            except asyncio.CancelledError:
                return
            except Exception as e:
                _log.debug("poll error: %s", e)
                await asyncio.sleep(1)

    await _poll_loop()
