"""Zork — a text adventure inspired by Zork I.

Explore the Great Underground Empire, collect treasures,
defeat monsters, and solve puzzles.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from kirbus.games import BaseGame


# ---------------------------------------------------------------------------
# World data
# ---------------------------------------------------------------------------
@dataclass
class Room:
    name: str
    description: str
    exits: dict[str, str] = field(default_factory=dict)  # direction → room_id
    items: list[str] = field(default_factory=list)
    dark: bool = False
    special: str = ""  # special room behavior


@dataclass
class Item:
    name: str
    description: str
    takeable: bool = True
    score: int = 0  # points for placing in trophy case


ROOMS: dict[str, Room] = {
    "west_of_house": Room(
        "West of House",
        "You are standing in an open field west of a white house,\n"
        "with a boarded front door. There is a small mailbox here.",
        {"north": "north_of_house", "south": "south_of_house", "west": "forest_1",
         "enter": "kitchen"},
        ["mailbox"],
    ),
    "north_of_house": Room(
        "North of House",
        "You are facing the north side of a white house.\n"
        "There is no door here, and all the windows are boarded.",
        {"west": "west_of_house", "east": "behind_house", "north": "forest_path"},
    ),
    "south_of_house": Room(
        "South of House",
        "You are facing the south side of a white house.\n"
        "There is no door here, and all the windows are boarded.",
        {"west": "west_of_house", "east": "behind_house", "south": "forest_2"},
    ),
    "behind_house": Room(
        "Behind House",
        "You are behind the white house. A path leads into the forest\n"
        "to the east. In one corner of the house there is a small\n"
        "window which is slightly ajar.",
        {"north": "north_of_house", "south": "south_of_house", "east": "clearing",
         "enter": "kitchen"},
    ),
    "kitchen": Room(
        "Kitchen",
        "You are in the kitchen of the white house. A table seems to\n"
        "have been used recently for the preparation of food.\n"
        "A passage leads to the west and a dark staircase leads down.",
        {"west": "living_room", "down": "cellar", "out": "behind_house"},
        ["bottle", "sack"],
    ),
    "living_room": Room(
        "Living Room",
        "You are in the living room. There is a doorway to the east,\n"
        "a wooden door with strange gothic lettering to the west,\n"
        "which appears to be nailed shut, and a trophy case.\n"
        "A large oriental rug covers the center of the floor.",
        {"east": "kitchen"},
        ["sword", "lantern"],
        special="trophy_case",
    ),
    "cellar": Room(
        "Cellar",
        "You are in a dark and damp cellar with a narrow passageway\n"
        "leading north, and a crawlway to the south. To the west is\n"
        "the bottom of a steep metal ramp which is unclimbable.",
        {"north": "troll_room", "south": "cave_south", "up": "kitchen"},
        dark=True,
    ),
    "troll_room": Room(
        "Troll Room",
        "This is a small room with passages to the east and south\n"
        "and a forbidding hole leading west. Bloodstains and deep\n"
        "scratches (perhaps made by straining, rusty chains) cover the walls.",
        {"south": "cellar", "east": "east_west_passage", "west": "maze_1"},
        dark=True,
        special="troll",
    ),
    "east_west_passage": Room(
        "East-West Passage",
        "This is a narrow east-west passage. There is a narrow\n"
        "stairway leading up at the north end of the room.",
        {"west": "troll_room", "east": "round_room", "up": "gallery"},
        dark=True,
    ),
    "round_room": Room(
        "Round Room",
        "This is a circular stone room with passages in all directions.\n"
        "Several of them have unfortunately been blocked by cave-ins.",
        {"west": "east_west_passage", "east": "loud_room", "south": "narrow_passage"},
        dark=True,
    ),
    "loud_room": Room(
        "Loud Room",
        "This is a large room with a ceiling which cannot be detected\n"
        "from the floor. There is a narrow passage from east to west\n"
        "and a stone stairway leading upward.\n"
        "The room is deafeningly loud with an unidentified rushing sound.",
        {"west": "round_room", "up": "deep_canyon"},
        ["platinum_bar"],
        dark=True,
        special="loud",
    ),
    "narrow_passage": Room(
        "Narrow Passage",
        "This is a narrow passage with the ceiling barely above your head.\n"
        "A faint glow comes from the south.",
        {"north": "round_room", "south": "treasure_room"},
        dark=True,
    ),
    "treasure_room": Room(
        "Treasure Room",
        "This is a large room, whose ceiling is too high to see.\n"
        "There are odd-shaped passages in many directions.\n"
        "A faint luminescence provides dim light.",
        {"north": "narrow_passage"},
        ["jeweled_egg", "gold_coffin"],
    ),
    "gallery": Room(
        "Gallery",
        "This is an art gallery. Most of the paintings have been stolen\n"
        "by vandals with exceptional taste. A stairway leads down.\n"
        "A doorway leads to a small room to the north.",
        {"down": "east_west_passage", "north": "studio"},
        ["painting"],
    ),
    "studio": Room(
        "Studio",
        "This appears to have been an artist's studio. The walls are\n"
        "covered with old paint splatters. A doorway leads south.",
        {"south": "gallery"},
    ),
    "cave_south": Room(
        "Damp Cave",
        "This is a damp cave with pools of water on the ground.\n"
        "A narrow crawlway leads north.",
        {"north": "cellar", "south": "underground_river"},
        ["torch"],
        dark=True,
    ),
    "underground_river": Room(
        "Underground River",
        "You are on the bank of a river flowing through an underground\n"
        "cavern. The water is fast and cold.",
        {"north": "cave_south"},
        ["trident"],
        dark=True,
    ),
    "forest_1": Room(
        "Forest",
        "This is a dimly lit forest, with large trees all around.\n"
        "To the east, there appears to be sunlight.",
        {"east": "west_of_house", "north": "forest_path", "west": "forest_2"},
    ),
    "forest_2": Room(
        "Dark Forest",
        "This is a dark and dense forest. The trees here are so thick\n"
        "almost no light gets through.",
        {"east": "south_of_house", "north": "forest_1", "south": "cliff"},
    ),
    "forest_path": Room(
        "Forest Path",
        "This is a path winding through a dimly lit forest.\n"
        "The path heads north-south here. One particularly large tree\n"
        "has some low branches.",
        {"south": "forest_1", "north": "clearing", "up": "up_tree"},
    ),
    "up_tree": Room(
        "Up a Tree",
        "You are about 10 feet above the ground nestled among some\n"
        "large branches. The nearest branch above you is beyond reach.\n"
        "On one of the branches is a small bird's nest.",
        {"down": "forest_path"},
        ["jewels"],
    ),
    "clearing": Room(
        "Clearing",
        "You are in a small clearing in a well-marked forest path\n"
        "that extends to the east and west.",
        {"east": "canyon_view", "west": "forest_path", "south": "behind_house"},
    ),
    "canyon_view": Room(
        "Canyon View",
        "You are at the top of the Great Canyon on its west wall.\n"
        "From here there is a marvelous view of the canyon and parts\n"
        "of the Frigid River below.",
        {"west": "clearing"},
        ["rusty_knife"],
    ),
    "deep_canyon": Room(
        "Deep Canyon",
        "You are on a ledge in the deep canyon. Below you is a\n"
        "seemingly bottomless pit. A narrow path leads upward.",
        {"down": "loud_room"},
        ["diamond"],
        dark=True,
    ),
    "maze_1": Room(
        "Maze",
        "You are in a maze of twisty little passages, all alike.",
        {"north": "maze_2", "south": "maze_3", "east": "troll_room", "west": "maze_2"},
        dark=True,
    ),
    "maze_2": Room(
        "Maze",
        "You are in a maze of twisty little passages, all alike.",
        {"north": "maze_3", "south": "maze_1", "east": "maze_3", "west": "maze_1"},
        ["skeleton_key"],
        dark=True,
    ),
    "maze_3": Room(
        "Maze",
        "You are in a maze of twisty little passages, all alike.",
        {"north": "maze_1", "south": "maze_2", "east": "maze_1", "west": "dead_end"},
        dark=True,
    ),
    "dead_end": Room(
        "Dead End",
        "You have come to a dead end in the maze.",
        {"east": "maze_3"},
        ["chalice"],
        dark=True,
    ),
    "cliff": Room(
        "Cliff",
        "You are on the edge of a cliff overlooking a vast underground\n"
        "cavern. Far below you can see strange lights flickering.",
        {"north": "forest_2"},
    ),
}

ITEMS: dict[str, Item] = {
    "mailbox":      Item("mailbox", "A small mailbox.", takeable=False),
    "leaflet":      Item("leaflet", "A small leaflet that reads:\n'WELCOME TO ZORK!\nYour quest: collect treasures and place them in the trophy case.'"),
    "sword":        Item("sword", "An elvish sword of great antiquity."),
    "lantern":      Item("lantern", "A brass lantern (providing light)."),
    "bottle":       Item("bottle", "A clear glass bottle."),
    "sack":         Item("sack", "An elongated brown sack, smelling of hot peppers."),
    "jeweled_egg":  Item("jeweled egg", "A jewel-encrusted egg, with a golden latch.", score=5),
    "gold_coffin":  Item("gold coffin", "A sarcophagus made of solid gold.", score=10),
    "painting":     Item("painting", "A masterful painting of a castle in a pastoral setting.", score=5),
    "jewels":       Item("jewels", "A handful of sparkling jewels.", score=5),
    "platinum_bar": Item("platinum bar", "A heavy bar of pure platinum.", score=10),
    "diamond":      Item("diamond", "A huge diamond, sparkling with inner light.", score=10),
    "torch":        Item("torch", "A flaming torch (providing light)."),
    "trident":      Item("trident", "A crystal trident.", score=5),
    "chalice":      Item("chalice", "A beautiful silver chalice.", score=10),
    "rusty_knife":  Item("rusty knife", "A rusty old knife."),
    "skeleton_key": Item("skeleton key", "An old skeleton key."),
}

_DIRECTIONS = {
    "n": "north", "s": "south", "e": "east", "w": "west",
    "u": "up", "d": "down",
    "north": "north", "south": "south", "east": "east", "west": "west",
    "up": "up", "down": "down", "enter": "enter", "out": "out",
    "in": "enter",
}

_TROPHY_ITEMS = {k for k, v in ITEMS.items() if v.score > 0}
_MAX_SCORE = sum(v.score for v in ITEMS.values())


# ---------------------------------------------------------------------------
# Game state
# ---------------------------------------------------------------------------
@dataclass
class State:
    player: str = ""
    room: str = "west_of_house"
    inventory: list[str] = field(default_factory=list)
    trophy_case: list[str] = field(default_factory=list)
    troll_alive: bool = True
    mailbox_open: bool = False
    moves: int = 0
    score: int = 0


# ---------------------------------------------------------------------------
# Game class
# ---------------------------------------------------------------------------
class ZorkGame(BaseGame):
    name        = "zork"
    description = "Zork"
    min_players = 1
    max_players = 1

    def __init__(self) -> None:
        self._state = State()
        self._over = False
        # Deep copy rooms so items can be moved
        self._rooms = {k: Room(r.name, r.description, dict(r.exits), list(r.items), r.dark, r.special)
                       for k, r in ROOMS.items()}

    def start(self, players: list[str]) -> str:
        self._state.player = players[0]
        return (
            "ZORK I: The Great Underground Empire\n"
            "Inspired by the original by Infocom (1980)\n"
            "Type 'help' for commands.\n\n"
            + self._look()
        )

    def on_message(self, sender: str, text: str) -> list[tuple[str, str]]:
        text = text.strip()
        if not text:
            return [(sender, "What?")]
        result = self._handle(text)
        self._state.moves += 1
        return [(sender, result)]

    @property
    def is_over(self) -> bool:
        return self._over

    # ------------------------------------------------------------------
    # Command parser
    # ------------------------------------------------------------------
    def _handle(self, text: str) -> str:
        words = text.lower().split()
        cmd = words[0]
        arg = " ".join(words[1:]) if len(words) > 1 else ""

        # Movement
        if cmd in _DIRECTIONS:
            return self._move(_DIRECTIONS[cmd])
        if cmd == "go" and arg in _DIRECTIONS:
            return self._move(_DIRECTIONS[arg])

        # Actions
        if cmd in ("look", "l"):
            return self._look()
        if cmd in ("inventory", "i"):
            return self._inventory()
        if cmd in ("take", "get", "grab"):
            return self._take(arg)
        if cmd in ("drop", "put"):
            if "in case" in arg or "in trophy" in arg:
                item = arg.replace(" in case", "").replace(" in trophy case", "").replace(" in trophy", "").strip()
                return self._put_in_case(item)
            return self._drop(arg)
        if cmd == "open":
            return self._open(arg)
        if cmd == "examine" or cmd == "x" or cmd == "read":
            return self._examine(arg)
        if cmd in ("attack", "kill", "fight", "hit"):
            return self._attack(arg)
        if cmd == "score":
            return self._show_score()
        if cmd == "help":
            return self._help()
        if cmd in ("quit", "q"):
            self._over = True
            return f"Your score: {self._state.score}/{_MAX_SCORE} in {self._state.moves} moves.\nThanks for playing!"
        if cmd == "save":
            return "Game state is preserved while your session is active."
        if cmd == "echo" and self._rooms[self._state.room].special == "loud":
            return self._handle_loud_room(text)

        # Try as direction
        if cmd in ("north", "south", "east", "west", "up", "down"):
            return self._move(cmd)

        return "I don't understand that."

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _look(self) -> str:
        room = self._rooms[self._state.room]
        if room.dark and not self._has_light():
            return "It is pitch black. You are likely to be eaten by a grue.\n(Use a light source!)"
        lines = [room.name, room.description]
        if room.items:
            for item_id in room.items:
                item = ITEMS.get(item_id)
                if item:
                    lines.append(f"There is a {item.name} here.")
        return "\n".join(lines)

    def _move(self, direction: str) -> str:
        room = self._rooms[self._state.room]

        # Troll blocks passage
        if room.special == "troll" and self._state.troll_alive and direction in ("east", "west"):
            return "A menacing troll blocks your way! You'll have to deal with it first."

        if direction not in room.exits:
            return "You can't go that way."

        # Dark room death
        next_room_id = room.exits[direction]
        next_room = self._rooms[next_room_id]
        if next_room.dark and not self._has_light():
            if random.random() < 0.3:
                self._over = True
                return "Oh no! You have walked into the slavering fangs of a lurking grue!\n\n*** You have died ***"

        self._state.room = next_room_id
        return self._look()

    def _take(self, name: str) -> str:
        if not name:
            return "Take what?"
        room = self._rooms[self._state.room]
        item_id = self._find_item(name, room.items)
        if not item_id:
            return f"There is no {name} here."
        item = ITEMS[item_id]
        if not item.takeable:
            return f"You can't take the {item.name}."
        if len(self._state.inventory) >= 8:
            return "You're carrying too many things already."
        room.items.remove(item_id)
        self._state.inventory.append(item_id)
        return f"Taken: {item.name}"

    def _drop(self, name: str) -> str:
        if not name:
            return "Drop what?"
        item_id = self._find_item(name, self._state.inventory)
        if not item_id:
            return "You're not carrying that."
        self._state.inventory.remove(item_id)
        self._rooms[self._state.room].items.append(item_id)
        return f"Dropped: {ITEMS[item_id].name}"

    def _open(self, name: str) -> str:
        if "mailbox" in name:
            if self._state.room != "west_of_house":
                return "There's no mailbox here."
            if not self._state.mailbox_open:
                self._state.mailbox_open = True
                room = self._rooms["west_of_house"]
                if "mailbox" in room.items:
                    room.items.append("leaflet")
                return "Opening the mailbox reveals a small leaflet."
            return "The mailbox is already open."
        if "egg" in name:
            if "jeweled_egg" in self._state.inventory:
                return "The egg is delicate. You'd need a key or tool to open it safely."
            return "You don't have that."
        return f"You can't open the {name}."

    def _examine(self, name: str) -> str:
        if not name:
            return self._look()
        item_id = self._find_item(name, self._state.inventory)
        if not item_id:
            room = self._rooms[self._state.room]
            item_id = self._find_item(name, room.items)
        if not item_id:
            return f"You don't see any {name} here."
        return ITEMS[item_id].description

    def _attack(self, target: str) -> str:
        if "troll" in target:
            if self._state.room != "troll_room":
                return "There's no troll here."
            if not self._state.troll_alive:
                return "The troll is already dead."
            if "sword" in self._state.inventory:
                self._state.troll_alive = False
                self._state.score += 5
                return (
                    "You swing the elvish sword at the troll!\n"
                    "The sword glows with a fierce blue light as it strikes.\n"
                    "The troll staggers back and collapses. The path is clear."
                )
            else:
                if random.random() < 0.4:
                    self._over = True
                    return "The troll swings its axe and strikes you down!\n\n*** You have died ***"
                return "You attack the troll bare-handed. It laughs and swats you aside.\nYou might need a weapon."
        return "Violence isn't the answer here."

    def _put_in_case(self, name: str) -> str:
        if self._state.room != "living_room":
            return "There's no trophy case here."
        item_id = self._find_item(name, self._state.inventory)
        if not item_id:
            return "You're not carrying that."
        if item_id not in _TROPHY_ITEMS:
            return f"The {ITEMS[item_id].name} doesn't belong in the trophy case."
        self._state.inventory.remove(item_id)
        self._state.trophy_case.append(item_id)
        points = ITEMS[item_id].score
        self._state.score += points
        result = f"You place the {ITEMS[item_id].name} in the trophy case. (+{points} points)"
        if self._state.score >= _MAX_SCORE:
            self._over = True
            result += (
                f"\n\nCongratulations! You scored {_MAX_SCORE}/{_MAX_SCORE}!\n"
                "You have mastered the Great Underground Empire!\n"
                f"Completed in {self._state.moves} moves."
            )
        return result

    def _inventory(self) -> str:
        if not self._state.inventory:
            return "You are empty-handed."
        lines = ["You are carrying:"]
        for item_id in self._state.inventory:
            lines.append(f"  {ITEMS[item_id].name}")
        return "\n".join(lines)

    def _show_score(self) -> str:
        return (
            f"Score: {self._state.score}/{_MAX_SCORE}\n"
            f"Moves: {self._state.moves}\n"
            f"Trophy case: {len(self._state.trophy_case)} items"
        )

    def _handle_loud_room(self, text: str) -> str:
        words = text.lower().split()
        if len(words) > 1 and words[1] == "echo":
            return "The acoustics of the room seem to shift. The rushing sound fades slightly."
        return "Your voice echoes deafeningly!"

    def _help(self) -> str:
        return (
            "Commands:\n"
            "  north/south/east/west (n/s/e/w) — move\n"
            "  up/down (u/d)        — move vertically\n"
            "  look (l)             — describe the room\n"
            "  take/get <item>      — pick up an item\n"
            "  drop <item>          — drop an item\n"
            "  put <item> in case   — place treasure in trophy case\n"
            "  open <object>        — open something\n"
            "  examine/x <item>     — look at an item closely\n"
            "  attack <target>      — attack a creature\n"
            "  inventory (i)        — show what you're carrying\n"
            "  score                — show your score\n"
            "  quit                 — end the game"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _has_light(self) -> bool:
        return "lantern" in self._state.inventory or "torch" in self._state.inventory

    def _find_item(self, name: str, item_list: list[str]) -> str | None:
        """Fuzzy match an item name against a list of item IDs."""
        name = name.lower().strip()
        for item_id in item_list:
            item = ITEMS.get(item_id)
            if not item:
                continue
            if name == item_id or name == item.name.lower():
                return item_id
            # Partial match
            if name in item.name.lower() or name in item_id:
                return item_id
        return None
