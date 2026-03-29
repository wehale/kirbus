"""Kirbus Trade Wars — single-player space trading game.

Navigate sectors, trade commodities at ports, upgrade your ship,
and amass a fortune in this classic BBS-inspired trading game.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from kirbus.games import BaseGame
from kirbus.home import get_home

# ---------------------------------------------------------------------------
# Universe data
# ---------------------------------------------------------------------------
_SECTOR_NAMES = [
    "Sol Station", "Rigel Outpost", "Vega Prime", "Altair Depot",
    "Sirius Hub", "Procyon Yard", "Deneb Market", "Polaris Gate",
    "Antares Dock", "Capella Port", "Arcturus Base", "Spica Trading Co",
    "Betelgeuse Bazaar", "Canopus Exchange", "Aldebaran Way",
    "Regulus Stop", "Fomalhaut Junction", "Achernar Terminal",
    "Bellatrix Landing", "Mintaka Crossing",
]

# Adjacency — each sector connects to 2-4 neighbors (hand-crafted small galaxy)
_EDGES = [
    (0, 1), (0, 2), (0, 4),
    (1, 3), (1, 5),
    (2, 4), (2, 6),
    (3, 5), (3, 7),
    (4, 6), (4, 8),
    (5, 7), (5, 9),
    (6, 8), (6, 10),
    (7, 9), (7, 11),
    (8, 10), (8, 12),
    (9, 11), (9, 13),
    (10, 12), (10, 14),
    (11, 13), (11, 15),
    (12, 14), (12, 16),
    (13, 15), (13, 17),
    (14, 16), (14, 18),
    (15, 17), (15, 19),
    (16, 18),
    (17, 19),
    (18, 19),
]

_COMMODITIES = ["Ore", "Organics", "Equipment"]

# Port types: what they buy (B) and sell (S)
_PORT_TYPES = [
    {"Ore": "B", "Organics": "S", "Equipment": "B"},   # type 0
    {"Ore": "S", "Organics": "B", "Equipment": "B"},   # type 1
    {"Ore": "B", "Organics": "B", "Equipment": "S"},   # type 2
    {"Ore": "S", "Organics": "S", "Equipment": "B"},   # type 3
    {"Ore": "S", "Organics": "B", "Equipment": "S"},   # type 4
    {"Ore": "B", "Organics": "S", "Equipment": "S"},   # type 5
]

_SHIPS = {
    "Merchant Cruiser": {"holds": 50, "cost": 0},
    "Colonial Transport": {"holds": 125, "cost": 25000},
    "Cargo Hauler": {"holds": 250, "cost": 75000},
    "Imperial Freighter": {"holds": 500, "cost": 200000},
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Port:
    name: str
    sector: int
    port_type: int
    prices: dict[str, int] = field(default_factory=dict)
    stock: dict[str, int] = field(default_factory=dict)

    def refresh_prices(self) -> None:
        """Randomize prices and stock for this port."""
        pt = _PORT_TYPES[self.port_type]
        for commodity in _COMMODITIES:
            base = {"Ore": 10, "Organics": 15, "Equipment": 30}[commodity]
            spread = int(base * 0.4)
            self.prices[commodity] = random.randint(base - spread, base + spread)
            if pt[commodity] == "S":
                self.stock[commodity] = random.randint(50, 200)
            else:
                self.stock[commodity] = random.randint(20, 100)

    def sells(self, commodity: str) -> bool:
        return _PORT_TYPES[self.port_type][commodity] == "S"

    def buys(self, commodity: str) -> bool:
        return _PORT_TYPES[self.port_type][commodity] == "B"


@dataclass
class Ship:
    name: str
    holds: int
    cargo: dict[str, int] = field(default_factory=lambda: {c: 0 for c in _COMMODITIES})

    @property
    def cargo_used(self) -> int:
        return sum(self.cargo.values())

    @property
    def cargo_free(self) -> int:
        return self.holds - self.cargo_used


@dataclass
class GameState:
    player: str = ""
    credits: int = 5000
    sector: int = 0
    ship: Ship = field(default_factory=lambda: Ship("Merchant Cruiser", 50))
    turns: int = 500
    visited: set[int] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Universe builder
# ---------------------------------------------------------------------------
def _build_adjacency() -> dict[int, list[int]]:
    adj: dict[int, list[int]] = {i: [] for i in range(len(_SECTOR_NAMES))}
    for a, b in _EDGES:
        adj[a].append(b)
        adj[b].append(a)
    return adj


def _build_ports() -> dict[int, Port]:
    ports: dict[int, Port] = {}
    # ~70% of sectors have a port
    for i in range(len(_SECTOR_NAMES)):
        if i == 0 or random.random() < 0.7:
            pt = random.randint(0, len(_PORT_TYPES) - 1)
            port = Port(name=_SECTOR_NAMES[i], sector=i, port_type=pt)
            port.refresh_prices()
            ports[i] = port
    return ports


# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------
def _save_path(player: str) -> Path:
    return get_home() / "games" / f"tradewars_{player}.json"


def _save_game(state: GameState, ports: dict[int, Port]) -> None:
    path = _save_path(state.player)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "credits": state.credits,
        "sector": state.sector,
        "ship_name": state.ship.name,
        "ship_holds": state.ship.holds,
        "cargo": state.ship.cargo,
        "turns": state.turns,
        "visited": list(state.visited),
        "ports": {
            str(k): {
                "port_type": v.port_type,
                "prices": v.prices,
                "stock": v.stock,
            }
            for k, v in ports.items()
        },
    }
    path.write_text(json.dumps(data, indent=2))


def _load_game(player: str) -> tuple[GameState, dict[int, Port]] | None:
    path = _save_path(player)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        state = GameState(
            player=player,
            credits=data["credits"],
            sector=data["sector"],
            ship=Ship(
                name=data["ship_name"],
                holds=data["ship_holds"],
                cargo=data.get("cargo", {c: 0 for c in _COMMODITIES}),
            ),
            turns=data["turns"],
            visited=set(data.get("visited", [])),
        )
        ports: dict[int, Port] = {}
        for k, v in data.get("ports", {}).items():
            sid = int(k)
            port = Port(
                name=_SECTOR_NAMES[sid],
                sector=sid,
                port_type=v["port_type"],
                prices=v.get("prices", {}),
                stock=v.get("stock", {}),
            )
            ports[sid] = port
        return state, ports
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Game class
# ---------------------------------------------------------------------------
class TradeWarsGame(BaseGame):
    name        = "tradewars"
    description = "Kirbus Trade Wars"
    min_players = 1
    max_players = 1

    def __init__(self) -> None:
        self._adj:   dict[int, list[int]] = _build_adjacency()
        self._ports: dict[int, Port] = {}
        self._state: GameState = GameState()
        self._over:  bool = False
        self._mode:  str = "nav"  # "nav" | "port" | "shipyard"

    def start(self, players: list[str]) -> str:
        player = players[0]
        loaded = _load_game(player)
        if loaded:
            self._state, self._ports = loaded
            self._state.player = player
            return (
                f"Welcome back, Commander {player}!\n"
                f"Ship: {self._state.ship.name} | "
                f"Credits: {self._state.credits:,} | "
                f"Turns: {self._state.turns}\n\n"
                + self._sector_display()
            )
        else:
            self._ports = _build_ports()
            self._state = GameState(player=player)
            self._state.visited.add(0)
            return (
                "=== KIRBUS TRADE WARS ===\n"
                f"Welcome, Commander {player}!\n\n"
                "You start at Sol Station with a Merchant Cruiser,\n"
                "50 cargo holds, and 5,000 credits.\n"
                "Trade commodities between ports to build your fortune.\n"
                "You have 500 turns. Use them wisely.\n\n"
                "Commands: move <#>, buy/sell <item>, port, scan,\n"
                "          map, status, shipyard, save, quit\n\n"
                + self._sector_display()
            )

    def on_message(self, sender: str, text: str) -> list[tuple[str, str]]:
        text = text.strip()
        if not text:
            return [(sender, "Enter a command. Type 'help' for options.")]

        if self._mode == "port":
            return [(sender, self._handle_port(text))]
        if self._mode == "shipyard":
            return [(sender, self._handle_shipyard(text))]

        return [(sender, self._handle_nav(text))]

    @property
    def is_over(self) -> bool:
        return self._over

    # ------------------------------------------------------------------
    # Navigation mode
    # ------------------------------------------------------------------
    def _handle_nav(self, text: str) -> str:
        parts = text.lower().split()
        cmd = parts[0]

        if cmd in ("quit", "q"):
            _save_game(self._state, self._ports)
            self._over = True
            return (
                f"Game saved. Final score: {self._score():,} credits.\n"
                "See you next time, Commander."
            )

        if cmd == "help":
            return (
                "Commands:\n"
                "  move <sector#>  — warp to an adjacent sector\n"
                "  buy <item> [qty] — buy from port (ore, organics, equipment)\n"
                "  sell <item> [qty]— sell to port\n"
                "  port             — enter the port to trade\n"
                "  scan             — scan adjacent sectors for ports\n"
                "  map              — show visited sectors\n"
                "  status           — show ship and cargo\n"
                "  shipyard         — upgrade your ship (Sol Station only)\n"
                "  save             — save your game\n"
                "  quit             — save and exit"
            )

        if cmd == "save":
            _save_game(self._state, self._ports)
            return "Game saved."

        if cmd in ("move", "m", "warp", "w"):
            if len(parts) < 2 or not parts[1].isdigit():
                neighbors = self._adj[self._state.sector]
                return f"Move where? Adjacent sectors: {', '.join(str(s) for s in sorted(neighbors))}"
            target = int(parts[1])
            return self._move_to(target)

        if cmd == "port" or cmd == "p":
            return self._enter_port()

        if cmd == "scan" or cmd == "sc":
            return self._scan()

        if cmd == "status" or cmd == "st":
            return self._status()

        if cmd == "map":
            return self._show_map()

        if cmd == "shipyard" or cmd == "sy":
            return self._enter_shipyard()

        if cmd in ("buy", "b", "sell", "s"):
            if self._state.sector in self._ports:
                self._mode = "port"
                return self._handle_port(text)
            return "No port in this sector."

        # Try bare number as move
        if text.isdigit():
            return self._move_to(int(text))

        return f"Unknown command: {cmd}. Type 'help' for options."

    def _move_to(self, target: int) -> str:
        if target < 0 or target >= len(_SECTOR_NAMES):
            return f"Sector {target} doesn't exist."
        if target not in self._adj[self._state.sector]:
            return f"Sector {target} is not adjacent. Adjacent: {', '.join(str(s) for s in sorted(self._adj[self._state.sector]))}"
        if self._state.turns <= 0:
            _save_game(self._state, self._ports)
            self._over = True
            return f"Out of turns! Final score: {self._score():,} credits."
        self._state.sector = target
        self._state.turns -= 1
        self._state.visited.add(target)
        return self._sector_display()

    def _sector_display(self) -> str:
        s = self._state.sector
        name = _SECTOR_NAMES[s]
        neighbors = sorted(self._adj[s])
        port = self._ports.get(s)
        lines = [
            f"[ Sector {s}: {name} ]",
            f"Warps to: {', '.join(str(n) for n in neighbors)}",
        ]
        if port:
            pt = _PORT_TYPES[port.port_type]
            buys = [c for c in _COMMODITIES if pt[c] == "B"]
            sells = [c for c in _COMMODITIES if pt[c] == "S"]
            lines.append(f"Port: {port.name}")
            lines.append(f"  Buys: {', '.join(buys)}  |  Sells: {', '.join(sells)}")
        else:
            lines.append("No port in this sector.")
        lines.append(f"Credits: {self._state.credits:,}  |  Turns: {self._state.turns}  |  Cargo: {self._state.ship.cargo_used}/{self._state.ship.holds}")
        return "\n".join(lines)

    def _scan(self) -> str:
        lines = ["=== Sector Scan ==="]
        for n in sorted(self._adj[self._state.sector]):
            name = _SECTOR_NAMES[n]
            port = self._ports.get(n)
            if port:
                pt = _PORT_TYPES[port.port_type]
                buys = [c for c in _COMMODITIES if pt[c] == "B"]
                sells = [c for c in _COMMODITIES if pt[c] == "S"]
                lines.append(f"  Sector {n}: {name} — Buys {', '.join(buys)} / Sells {', '.join(sells)}")
            else:
                lines.append(f"  Sector {n}: {name} — no port")
        return "\n".join(lines)

    def _status(self) -> str:
        s = self._state
        cargo_lines = []
        for c in _COMMODITIES:
            amt = s.ship.cargo[c]
            if amt > 0:
                cargo_lines.append(f"  {c}: {amt}")
        cargo_str = "\n".join(cargo_lines) if cargo_lines else "  (empty)"
        return (
            f"=== Commander {s.player} ===\n"
            f"Ship: {s.ship.name} ({s.ship.holds} holds)\n"
            f"Credits: {s.credits:,}\n"
            f"Turns remaining: {s.turns}\n"
            f"Sector: {s.sector} ({_SECTOR_NAMES[s.sector]})\n"
            f"Sectors explored: {len(s.visited)}/{len(_SECTOR_NAMES)}\n"
            f"Cargo ({s.ship.cargo_used}/{s.ship.holds}):\n{cargo_str}\n"
            f"Score: {self._score():,}"
        )

    def _show_map(self) -> str:
        lines = ["=== Galaxy Map ==="]
        for i in range(len(_SECTOR_NAMES)):
            marker = "*" if i == self._state.sector else " "
            visited = "+" if i in self._state.visited else "?"
            port_marker = "P" if i in self._ports else " "
            name = _SECTOR_NAMES[i] if i in self._state.visited else "???"
            neighbors = ", ".join(str(n) for n in sorted(self._adj[i]))
            lines.append(f"  [{visited}]{marker}{port_marker} {i:2d}: {name:22s} → {neighbors}")
        lines.append("")
        lines.append("* = current  + = visited  ? = unexplored  P = port")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Port trading mode
    # ------------------------------------------------------------------
    def _enter_port(self) -> str:
        port = self._ports.get(self._state.sector)
        if not port:
            return "No port in this sector."
        self._mode = "port"
        return self._port_display(port)

    def _port_display(self, port: Port) -> str:
        lines = [f"=== {port.name} Trading Port ===", ""]
        lines.append(f"{'Commodity':15s} {'Price':>8s} {'Stock':>8s} {'Action':>8s} {'You Have':>8s}")
        lines.append("-" * 55)
        for c in _COMMODITIES:
            action = "SELL→you" if port.sells(c) else "BUY←you"
            lines.append(
                f"{c:15s} {port.prices[c]:>8,} {port.stock[c]:>8,} {action:>8s} {self._state.ship.cargo[c]:>8,}"
            )
        lines.append("")
        lines.append(f"Credits: {self._state.credits:,}  |  Cargo: {self._state.ship.cargo_used}/{self._state.ship.holds}")
        lines.append("")
        lines.append("Commands: buy <commodity> <qty>, sell <commodity> <qty>, leave")
        return "\n".join(lines)

    def _handle_port(self, text: str) -> str:
        parts = text.lower().split()
        cmd = parts[0]
        port = self._ports[self._state.sector]

        if cmd in ("leave", "l", "exit", "quit", "q"):
            self._mode = "nav"
            return self._sector_display()

        if cmd == "buy" or cmd == "b":
            return self._port_buy(parts, port)

        if cmd == "sell" or cmd == "s":
            return self._port_sell(parts, port)

        return self._port_display(port)

    def _match_commodity(self, name: str) -> str | None:
        name = name.lower()
        for c in _COMMODITIES:
            if c.lower().startswith(name):
                return c
        return None

    def _port_buy(self, parts: list[str], port: Port) -> str:
        if len(parts) < 2:
            return "Usage: buy <commodity> [qty]  (e.g. buy ore 20)"
        commodity = self._match_commodity(parts[1])
        if not commodity:
            return f"Unknown commodity: {parts[1]}"
        if not port.sells(commodity):
            return f"This port doesn't sell {commodity}."
        price = port.prices[commodity]
        max_afford = self._state.credits // price if price > 0 else 0
        max_cargo = self._state.ship.cargo_free
        max_stock = port.stock[commodity]
        maximum = min(max_afford, max_cargo, max_stock)
        if len(parts) >= 3 and parts[2].isdigit():
            qty = min(int(parts[2]), maximum)
        else:
            qty = maximum
        if qty <= 0:
            return f"Can't buy any {commodity}. (afford: {max_afford}, space: {max_cargo}, stock: {max_stock})"
        cost = qty * price
        self._state.credits -= cost
        self._state.ship.cargo[commodity] += qty
        port.stock[commodity] -= qty
        return (
            f"Bought {qty} {commodity} for {cost:,} credits.\n"
            + self._port_display(port)
        )

    def _port_sell(self, parts: list[str], port: Port) -> str:
        if len(parts) < 2:
            return "Usage: sell <commodity> [qty]  (e.g. sell ore 20)"
        commodity = self._match_commodity(parts[1])
        if not commodity:
            return f"Unknown commodity: {parts[1]}"
        if not port.buys(commodity):
            return f"This port doesn't buy {commodity}."
        have = self._state.ship.cargo[commodity]
        if have <= 0:
            return f"You don't have any {commodity}."
        price = port.prices[commodity]
        if len(parts) >= 3 and parts[2].isdigit():
            qty = min(int(parts[2]), have)
        else:
            qty = have
        revenue = qty * price
        self._state.credits += revenue
        self._state.ship.cargo[commodity] -= qty
        port.stock[commodity] += qty
        return (
            f"Sold {qty} {commodity} for {revenue:,} credits.\n"
            + self._port_display(port)
        )

    # ------------------------------------------------------------------
    # Shipyard mode
    # ------------------------------------------------------------------
    def _enter_shipyard(self) -> str:
        if self._state.sector != 0:
            return "Shipyard is only at Sol Station (sector 0)."
        self._mode = "shipyard"
        return self._shipyard_display()

    def _shipyard_display(self) -> str:
        lines = ["=== Sol Station Shipyard ===", ""]
        lines.append(f"Current ship: {self._state.ship.name} ({self._state.ship.holds} holds)")
        lines.append(f"Credits: {self._state.credits:,}")
        lines.append("")
        lines.append(f"{'#':>3s}  {'Ship':25s} {'Holds':>8s} {'Cost':>10s}")
        lines.append("-" * 50)
        for i, (name, info) in enumerate(_SHIPS.items()):
            current = " <<<" if name == self._state.ship.name else ""
            lines.append(f"{i+1:>3d}  {name:25s} {info['holds']:>8d} {info['cost']:>10,}{current}")
        lines.append("")
        lines.append("Commands: buy <#>, leave")
        return "\n".join(lines)

    def _handle_shipyard(self, text: str) -> str:
        parts = text.lower().split()
        cmd = parts[0]

        if cmd in ("leave", "l", "exit", "quit", "q"):
            self._mode = "nav"
            return self._sector_display()

        if cmd in ("buy", "b") and len(parts) >= 2 and parts[1].isdigit():
            idx = int(parts[1]) - 1
            ships = list(_SHIPS.items())
            if idx < 0 or idx >= len(ships):
                return "Invalid ship number."
            name, info = ships[idx]
            if name == self._state.ship.name:
                return "You already own that ship."
            cost = info["cost"]
            if self._state.credits < cost:
                return f"Not enough credits. Need {cost:,}, have {self._state.credits:,}."
            if self._state.ship.cargo_used > info["holds"]:
                return f"Too much cargo! Ship has {info['holds']} holds but you're carrying {self._state.ship.cargo_used}."
            self._state.credits -= cost
            self._state.ship = Ship(name=name, holds=info["holds"], cargo=self._state.ship.cargo.copy())
            return (
                f"Purchased {name}! {info['holds']} cargo holds.\n\n"
                + self._shipyard_display()
            )

        return self._shipyard_display()

    # ------------------------------------------------------------------
    # Score
    # ------------------------------------------------------------------
    def _score(self) -> int:
        """Total net worth: credits + cargo value at average prices."""
        total = self._state.credits
        for c in _COMMODITIES:
            base = {"Ore": 10, "Organics": 15, "Equipment": 30}[c]
            total += self._state.ship.cargo[c] * base
        return total
