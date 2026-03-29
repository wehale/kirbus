"""Barren Realms — single-player kingdom management game.

Manage your kingdom: grow food, build armies, expand land,
and compete against AI realms for dominance.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from kirbus.games import BaseGame
from kirbus.home import get_home

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
STARTING_TURNS = 25
TURNS_PER_SESSION = 15
MAX_DAYS = 30

_AI_NAMES = [
    "Kingdom of Mordath", "Duchy of Silverpine", "Empire of Krath",
    "Realm of Thornwall", "Dominion of Ashfeld", "Barony of Greymoor",
    "Lands of Sunhaven", "Province of Darkhollow",
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Realm:
    name: str
    land: int = 200
    gold: int = 1000
    food: int = 500
    population: int = 100
    soldiers: int = 20
    farms: int = 10
    markets: int = 5
    forts: int = 1
    is_ai: bool = False

    @property
    def net_worth(self) -> int:
        return (
            self.gold
            + self.land * 10
            + self.population * 5
            + self.soldiers * 20
            + self.farms * 50
            + self.markets * 100
            + self.forts * 500
            + self.food * 2
        )

    @property
    def food_production(self) -> int:
        return self.farms * 10

    @property
    def food_consumption(self) -> int:
        return self.population + self.soldiers

    @property
    def gold_income(self) -> int:
        return self.markets * 20 + self.population * 2

    @property
    def defense_power(self) -> int:
        return self.soldiers * 2 + self.forts * 50

    @property
    def attack_power(self) -> int:
        return self.soldiers * 2

    @property
    def max_population(self) -> int:
        return self.land * 2

    @property
    def available_land(self) -> int:
        return self.land - self.farms - self.markets - self.forts


@dataclass
class GameState:
    player_name: str = ""
    realm: Realm = field(default_factory=lambda: Realm(""))
    ai_realms: list[Realm] = field(default_factory=list)
    day: int = 1
    turns_left: int = STARTING_TURNS
    events: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------
def _save_path(player: str) -> Path:
    return get_home() / "games" / f"barrenrealms_{player}.json"


def _realm_to_dict(r: Realm) -> dict:
    return {
        "name": r.name, "land": r.land, "gold": r.gold, "food": r.food,
        "population": r.population, "soldiers": r.soldiers,
        "farms": r.farms, "markets": r.markets, "forts": r.forts,
        "is_ai": r.is_ai,
    }


def _realm_from_dict(d: dict) -> Realm:
    return Realm(**d)


def _save_game(state: GameState) -> None:
    path = _save_path(state.player_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "player_name": state.player_name,
        "realm": _realm_to_dict(state.realm),
        "ai_realms": [_realm_to_dict(r) for r in state.ai_realms],
        "day": state.day,
        "turns_left": state.turns_left,
    }
    path.write_text(json.dumps(data, indent=2))


def _load_game(player: str) -> GameState | None:
    path = _save_path(player)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        state = GameState(
            player_name=data["player_name"],
            realm=_realm_from_dict(data["realm"]),
            ai_realms=[_realm_from_dict(r) for r in data["ai_realms"]],
            day=data["day"],
            turns_left=data["turns_left"],
        )
        return state
    except Exception:
        return None


# ---------------------------------------------------------------------------
# AI logic
# ---------------------------------------------------------------------------
def _ai_turn(realm: Realm) -> None:
    """Simple AI: grow economy, build army, occasionally expand."""
    # Food production
    realm.food += realm.food_production - realm.food_consumption
    realm.gold += realm.gold_income

    # Build if affordable
    if realm.gold > 300 and realm.available_land > 5:
        choice = random.choice(["farm", "market", "soldiers"])
        if choice == "farm":
            realm.farms += 2
            realm.gold -= 200
        elif choice == "market":
            realm.markets += 1
            realm.gold -= 300
        elif choice == "soldiers" and realm.gold > 200:
            new = min(realm.population // 5, 10)
            realm.soldiers += new
            realm.gold -= new * 15

    # Population growth
    if realm.food > realm.food_consumption * 2:
        growth = min(random.randint(3, 10), realm.max_population - realm.population)
        realm.population += max(0, growth)

    # Expand land occasionally
    if random.random() < 0.3 and realm.gold > 500:
        new_land = random.randint(5, 15)
        realm.land += new_land
        realm.gold -= new_land * 20

    # Starvation
    if realm.food < 0:
        starved = min(abs(realm.food) // 2, realm.population // 4)
        realm.population = max(10, realm.population - starved)
        realm.food = 0

    # Fort building
    if realm.gold > 1000 and random.random() < 0.2:
        realm.forts += 1
        realm.gold -= 500


def _ai_attack_player(ai: Realm, player: Realm) -> str | None:
    """AI may attack the player if strong enough. Returns event text or None."""
    if ai.attack_power < player.defense_power * 0.8:
        return None
    if random.random() > 0.15:  # only 15% chance per day
        return None

    # Attack!
    att = ai.attack_power + random.randint(-10, 10)
    dfn = player.defense_power + random.randint(-10, 10)

    if att > dfn:
        # Attacker wins
        land_taken = random.randint(5, min(20, player.land // 10))
        gold_taken = random.randint(50, min(300, player.gold // 5))
        soldiers_lost = random.randint(1, max(1, player.soldiers // 5))
        player.land = max(50, player.land - land_taken)
        player.gold = max(0, player.gold - gold_taken)
        player.soldiers = max(0, player.soldiers - soldiers_lost)
        ai.land += land_taken
        ai.gold += gold_taken
        return (
            f"*** {ai.name} attacked your realm! ***\n"
            f"You lost {land_taken} land, {gold_taken} gold, and {soldiers_lost} soldiers."
        )
    else:
        # Defender wins
        ai_lost = random.randint(1, max(1, ai.soldiers // 5))
        ai.soldiers = max(0, ai.soldiers - ai_lost)
        return f"{ai.name} attacked but your defenses held! They lost {ai_lost} soldiers."


# ---------------------------------------------------------------------------
# Game class
# ---------------------------------------------------------------------------
class BarrenRealmsGame(BaseGame):
    name        = "realm"
    description = "Barren Realms"
    min_players = 1
    max_players = 1

    def __init__(self) -> None:
        self._state: GameState = GameState()
        self._over: bool = False

    def start(self, players: list[str]) -> str:
        player = players[0]
        loaded = _load_game(player)
        if loaded:
            self._state = loaded
            # New day
            self._advance_day()
            return (
                f"Welcome back, Ruler {player}!\n"
                f"Day {self._state.day} of {MAX_DAYS}\n\n"
                + self._show_events()
                + self._status_brief()
            )
        else:
            # New game
            realm_name = f"Realm of {player}"
            self._state = GameState(
                player_name=player,
                realm=Realm(name=realm_name),
                ai_realms=self._create_ai_realms(),
                day=1,
                turns_left=STARTING_TURNS,
            )
            return (
                "=== BARREN REALMS ===\n"
                f"Welcome, Ruler {player}!\n\n"
                f"You rule the {realm_name}.\n"
                "Build farms for food, markets for gold,\n"
                "raise soldiers, and expand your land.\n"
                f"You have {MAX_DAYS} days to build the greatest realm.\n"
                f"Each day you get {TURNS_PER_SESSION} turns.\n\n"
                "Commands: build, recruit, explore, attack,\n"
                "          status, rankings, help, save, quit\n\n"
                + self._status_brief()
            )

    def _create_ai_realms(self) -> list[Realm]:
        names = random.sample(_AI_NAMES, 4)
        realms = []
        for name in names:
            r = Realm(
                name=name,
                land=random.randint(150, 250),
                gold=random.randint(800, 1500),
                food=random.randint(400, 700),
                population=random.randint(80, 130),
                soldiers=random.randint(15, 35),
                farms=random.randint(8, 15),
                markets=random.randint(3, 8),
                forts=random.randint(0, 2),
                is_ai=True,
            )
            realms.append(r)
        return realms

    def _advance_day(self) -> None:
        """Process end-of-day: AI turns, events, new turns."""
        self._state.events.clear()
        r = self._state.realm

        # Player realm production
        r.food += r.food_production - r.food_consumption
        r.gold += r.gold_income

        # Population growth
        if r.food > r.food_consumption * 2 and r.population < r.max_population:
            growth = random.randint(2, 8)
            growth = min(growth, r.max_population - r.population)
            r.population += growth
            self._state.events.append(f"{growth} new citizens joined your realm.")

        # Starvation
        if r.food < 0:
            starved = min(abs(r.food) // 2, r.population // 4)
            r.population = max(10, r.population - starved)
            r.food = 0
            if starved > 0:
                self._state.events.append(f"Famine! {starved} citizens starved.")

        # AI turns
        for ai in self._state.ai_realms:
            _ai_turn(ai)
            event = _ai_attack_player(ai, r)
            if event:
                self._state.events.append(event)

        # New turns
        self._state.day += 1
        self._state.turns_left = TURNS_PER_SESSION

        # Check game over
        if self._state.day > MAX_DAYS:
            self._end_game()

    def _end_game(self) -> None:
        self._over = True
        path = _save_path(self._state.player_name)
        if path.exists():
            path.unlink()

    def on_message(self, sender: str, text: str) -> list[tuple[str, str]]:
        text = text.strip()
        if not text:
            return [(sender, "Enter a command. Type 'help' for options.")]
        return [(sender, self._handle(text))]

    @property
    def is_over(self) -> bool:
        return self._over

    # ------------------------------------------------------------------
    # Command handling
    # ------------------------------------------------------------------
    def _handle(self, text: str) -> str:
        parts = text.lower().split()
        cmd = parts[0]

        if cmd in ("quit", "q"):
            _save_game(self._state)
            self._over = True
            return f"Game saved. Your net worth: {self._state.realm.net_worth:,}.\nSee you tomorrow, Ruler."

        if cmd == "help":
            return (
                "Commands:\n"
                "  build <farm|market|fort> [qty] — construct buildings (1 turn each)\n"
                "  recruit [qty]   — recruit soldiers (1 turn per 10)\n"
                "  explore [qty]   — explore for new land (1 turn per expedition)\n"
                "  attack <#>      — attack an AI realm\n"
                "  status          — show your realm details\n"
                "  rankings        — compare all realms\n"
                "  save            — save your game\n"
                "  end             — end day early (advance to next day)\n"
                "  quit            — save and exit"
            )

        if cmd == "save":
            _save_game(self._state)
            return "Game saved."

        if cmd == "end":
            _save_game(self._state)
            self._advance_day()
            if self._over:
                return self._final_rankings()
            return (
                f"Day {self._state.day} of {MAX_DAYS}\n\n"
                + self._show_events()
                + self._status_brief()
            )

        if cmd == "status" or cmd == "st":
            return self._status_full()

        if cmd == "rankings" or cmd == "rank":
            return self._rankings()

        if cmd in ("build", "b"):
            return self._build(parts)

        if cmd in ("recruit", "rec"):
            qty = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
            return self._recruit(qty)

        if cmd in ("explore", "exp"):
            qty = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
            return self._explore(qty)

        if cmd in ("attack", "att"):
            if len(parts) < 2 or not parts[1].isdigit():
                return self._attack_list()
            return self._attack(int(parts[1]))

        return f"Unknown command: {cmd}. Type 'help' for options."

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _use_turn(self, n: int = 1) -> str | None:
        """Consume turns. Returns error string if not enough."""
        if self._state.turns_left < n:
            return f"Not enough turns. You have {self._state.turns_left} left."
        self._state.turns_left -= n
        if self._state.turns_left <= 0:
            _save_game(self._state)
            self._advance_day()
            if self._over:
                return None  # caller should check is_over
        return None

    def _build(self, parts: list[str]) -> str:
        if len(parts) < 2:
            return (
                "Build what?\n"
                "  build farm [qty]   — 100 gold, uses 1 land (produces 10 food)\n"
                "  build market [qty] — 300 gold, uses 1 land (produces 20 gold)\n"
                "  build fort [qty]   — 500 gold, uses 1 land (+50 defense)"
            )
        what = parts[1]
        qty = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
        r = self._state.realm

        costs = {"farm": 100, "market": 300, "fort": 500}
        if what not in costs:
            return "Build: farm, market, or fort."

        cost = costs[what] * qty
        if r.gold < cost:
            max_afford = r.gold // costs[what]
            return f"Not enough gold. Need {cost:,}, have {r.gold:,}. Can afford {max_afford}."
        if r.available_land < qty:
            return f"Not enough land. Need {qty}, have {r.available_land} available."

        err = self._use_turn(qty)
        if err:
            return err

        r.gold -= cost
        if what == "farm":
            r.farms += qty
        elif what == "market":
            r.markets += qty
        elif what == "fort":
            r.forts += qty

        result = f"Built {qty} {what}(s) for {cost:,} gold."
        if self._over:
            return result + "\n\n" + self._final_rankings()
        return result + f" Turns left: {self._state.turns_left}"

    def _recruit(self, qty: int) -> str:
        r = self._state.realm
        cost = qty * 15
        if r.gold < cost:
            max_afford = r.gold // 15
            return f"Not enough gold. Need {cost:,}, have {r.gold:,}. Can afford {max_afford}."
        if r.population < qty:
            return f"Not enough citizens. Need {qty}, have {r.population}."

        turns_needed = max(1, qty // 10)
        err = self._use_turn(turns_needed)
        if err:
            return err

        r.gold -= cost
        r.soldiers += qty
        r.population -= qty

        result = f"Recruited {qty} soldiers for {cost:,} gold."
        if self._over:
            return result + "\n\n" + self._final_rankings()
        return result + f" Turns left: {self._state.turns_left}"

    def _explore(self, expeditions: int) -> str:
        r = self._state.realm
        cost = expeditions * 50

        if r.gold < cost:
            return f"Not enough gold. Need {cost:,}, have {r.gold:,}."

        err = self._use_turn(expeditions)
        if err:
            return err

        r.gold -= cost
        total_land = 0
        total_food = 0
        for _ in range(expeditions):
            land = random.randint(5, 20)
            food_found = random.randint(0, 50)
            total_land += land
            total_food += food_found
        r.land += total_land
        r.food += total_food

        result = f"Explored and found {total_land} land"
        if total_food > 0:
            result += f" and {total_food} food"
        result += "!"
        if self._over:
            return result + "\n\n" + self._final_rankings()
        return result + f" Turns left: {self._state.turns_left}"

    def _attack_list(self) -> str:
        lines = ["=== Rival Realms ===", ""]
        for i, ai in enumerate(self._state.ai_realms):
            strength = "weak" if ai.defense_power < self._state.realm.attack_power * 0.7 else \
                       "strong" if ai.defense_power > self._state.realm.attack_power * 1.3 else \
                       "even"
            lines.append(f"  {i+1}. {ai.name} — {ai.land} land, ~{strength} defenses")
        lines.append("")
        lines.append(f"Your attack power: {self._state.realm.attack_power}")
        lines.append("Usage: attack <#>")
        return "\n".join(lines)

    def _attack(self, target: int) -> str:
        idx = target - 1
        if idx < 0 or idx >= len(self._state.ai_realms):
            return "Invalid target. Type 'attack' to see options."

        r = self._state.realm
        if r.soldiers < 5:
            return "Need at least 5 soldiers to attack."

        err = self._use_turn(3)
        if err:
            return err

        ai = self._state.ai_realms[idx]
        att = r.attack_power + random.randint(-15, 15)
        dfn = ai.defense_power + random.randint(-15, 15)

        if att > dfn:
            # Victory
            land_taken = random.randint(10, min(40, ai.land // 5))
            gold_taken = random.randint(100, min(500, ai.gold // 3))
            soldiers_lost = random.randint(1, max(1, r.soldiers // 8))
            ai_soldiers_lost = random.randint(3, max(3, ai.soldiers // 4))

            r.land += land_taken
            r.gold += gold_taken
            r.soldiers = max(0, r.soldiers - soldiers_lost)
            ai.land = max(50, ai.land - land_taken)
            ai.gold = max(0, ai.gold - gold_taken)
            ai.soldiers = max(0, ai.soldiers - ai_soldiers_lost)

            result = (
                f"Victory against {ai.name}!\n"
                f"Gained: {land_taken} land, {gold_taken} gold\n"
                f"Lost: {soldiers_lost} soldiers"
            )
        else:
            # Defeat
            soldiers_lost = random.randint(2, max(2, r.soldiers // 5))
            gold_lost = random.randint(0, min(200, max(0, r.gold // 5)))
            r.soldiers = max(0, r.soldiers - soldiers_lost)
            r.gold = max(0, r.gold - gold_lost)

            result = (
                f"Defeated by {ai.name}!\n"
                f"Lost: {soldiers_lost} soldiers, {gold_lost} gold"
            )

        if self._over:
            return result + "\n\n" + self._final_rankings()
        return result + f"\nTurns left: {self._state.turns_left}"

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------
    def _status_brief(self) -> str:
        r = self._state.realm
        return (
            f"--- {r.name} ---\n"
            f"Land: {r.land}  |  Gold: {r.gold:,}  |  Food: {r.food:,}\n"
            f"Pop: {r.population}  |  Soldiers: {r.soldiers}  |  Turns: {self._state.turns_left}\n"
            f"Net worth: {r.net_worth:,}"
        )

    def _status_full(self) -> str:
        r = self._state.realm
        return (
            f"=== {r.name} ===\n"
            f"Day: {self._state.day} of {MAX_DAYS}\n"
            f"Turns left: {self._state.turns_left}\n\n"
            f"Land: {r.land} ({r.available_land} available)\n"
            f"Gold: {r.gold:,} (+{r.gold_income}/day)\n"
            f"Food: {r.food:,} (+{r.food_production}/day, -{r.food_consumption}/day)\n"
            f"Population: {r.population}/{r.max_population}\n"
            f"Soldiers: {r.soldiers}\n\n"
            f"Buildings:\n"
            f"  Farms: {r.farms} (produce {r.food_production} food)\n"
            f"  Markets: {r.markets} (produce {r.gold_income - r.population * 2} gold)\n"
            f"  Forts: {r.forts} (+{r.forts * 50} defense)\n\n"
            f"Military:\n"
            f"  Attack: {r.attack_power}  |  Defense: {r.defense_power}\n\n"
            f"Net worth: {r.net_worth:,}"
        )

    def _rankings(self) -> str:
        all_realms = [self._state.realm] + self._state.ai_realms
        all_realms.sort(key=lambda r: r.net_worth, reverse=True)
        lines = ["=== Rankings ===", ""]
        lines.append(f"{'#':>3s}  {'Realm':30s} {'Land':>8s} {'Gold':>10s} {'Army':>6s} {'Worth':>10s}")
        lines.append("-" * 72)
        for i, r in enumerate(all_realms):
            marker = " <<<" if r.name == self._state.realm.name else ""
            lines.append(
                f"{i+1:>3d}  {r.name:30s} {r.land:>8,} {r.gold:>10,} {r.soldiers:>6} {r.net_worth:>10,}{marker}"
            )
        return "\n".join(lines)

    def _final_rankings(self) -> str:
        all_realms = [self._state.realm] + self._state.ai_realms
        all_realms.sort(key=lambda r: r.net_worth, reverse=True)
        rank = next(i+1 for i, r in enumerate(all_realms) if r.name == self._state.realm.name)
        lines = [
            "=== GAME OVER ===",
            f"After {MAX_DAYS} days, the realms stand:",
            "",
        ]
        for i, r in enumerate(all_realms):
            marker = " <<<" if r.name == self._state.realm.name else ""
            lines.append(f"  {i+1}. {r.name} — net worth: {r.net_worth:,}{marker}")
        lines.append("")
        if rank == 1:
            lines.append("You are the supreme ruler! Victory!")
        elif rank <= 2:
            lines.append("A strong showing. Almost supreme!")
        else:
            lines.append("The realm needs a stronger ruler...")
        return "\n".join(lines)

    def _show_events(self) -> str:
        if not self._state.events:
            return ""
        lines = ["=== Overnight Events ==="]
        for e in self._state.events:
            lines.append(f"  {e}")
        lines.append("")
        return "\n".join(lines) + "\n"
