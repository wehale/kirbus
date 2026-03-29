"""Colossal Cave Adventure — a text adventure inspired by the original.

Explore Colossal Cave, collect treasures, and find your way out.
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
    exits: dict[str, str] = field(default_factory=dict)
    items: list[str] = field(default_factory=list)
    dark: bool = False
    special: str = ""


@dataclass
class Item:
    name: str
    description: str
    takeable: bool = True
    score: int = 0


ROOMS: dict[str, Room] = {
    "building": Room(
        "Inside Building",
        "You are inside a building, a well house for a large spring.\n"
        "There are some keys on the ground here.",
        {"south": "valley", "out": "road", "down": "stream_chamber"},
        ["keys", "food", "bottle_water"],
    ),
    "road": Room(
        "End of Road",
        "You are standing at the end of a road before a small brick building.\n"
        "Around you is a forest. A small stream flows out of the building\n"
        "and down a gully.",
        {"south": "valley", "north": "forest", "east": "building",
         "enter": "building", "west": "hill"},
    ),
    "hill": Room(
        "Hill in Road",
        "You have walked up a hill, still in the forest.\n"
        "The road slopes back to the east.",
        {"east": "road", "north": "forest"},
    ),
    "forest": Room(
        "In a Forest",
        "You are in open forest, with a deep valley to one side.",
        {"south": "road", "east": "valley", "north": "forest",
         "west": "forest"},
    ),
    "valley": Room(
        "In a Valley",
        "You are in a valley in the forest beside a stream tumbling\n"
        "along a rocky bed.",
        {"north": "road", "south": "slit", "east": "forest",
         "west": "forest"},
    ),
    "slit": Room(
        "At Slit in Streambed",
        "At your feet all the water of the stream splashes into a\n"
        "2-inch slit in the rock. Downstream the streambed is bare rock.",
        {"north": "valley", "south": "grate_outside"},
    ),
    "grate_outside": Room(
        "Outside Grate",
        "You are in a 20-foot depression floored with bare dirt.\n"
        "Set into the dirt is a strong steel grate mounted in concrete.\n"
        "A dry streambed leads into the depression.",
        {"north": "slit", "down": "below_grate"},
        special="grate",
    ),
    "below_grate": Room(
        "Below the Grate",
        "You are in a small chamber beneath a 3x3 steel grate to\n"
        "the surface. A low crawl over cobbles leads inward to the west.",
        {"up": "grate_outside", "west": "cobble_crawl"},
        dark=True,
    ),
    "cobble_crawl": Room(
        "Cobble Crawl",
        "You are crawling over cobbles in a low passage. There is a\n"
        "dim light at the east end of the passage.",
        {"east": "below_grate", "west": "debris_room"},
        ["lamp"],
        dark=True,
    ),
    "debris_room": Room(
        "Debris Room",
        "You are in a debris room filled with stuff washed in from\n"
        "the surface. A low wide passage with cobbles becomes plugged\n"
        "with mud and debris here, but an awkward canyon leads upward\n"
        "and west.",
        {"east": "cobble_crawl", "up": "awkward_canyon", "west": "awkward_canyon"},
        ["rod"],
        dark=True,
    ),
    "awkward_canyon": Room(
        "Awkward Sloping Canyon",
        "You are in an awkward sloping east/west canyon.",
        {"east": "debris_room", "west": "bird_chamber"},
        dark=True,
    ),
    "bird_chamber": Room(
        "Bird Chamber",
        "You are in a splendid chamber thirty feet high. The walls\n"
        "are frozen rivers of orange stone. A cheerful little bird\n"
        "is sitting here singing.",
        {"east": "awkward_canyon", "south": "pit_top"},
        ["bird"],
        dark=True,
    ),
    "pit_top": Room(
        "Top of Small Pit",
        "At your feet is a small pit breathing traces of white mist.\n"
        "A west passage ends here except for a small crack leading on.\n"
        "Rough stone steps lead down the pit.",
        {"north": "bird_chamber", "down": "hall_of_mists", "west": "crack"},
        dark=True,
    ),
    "crack": Room(
        "In a Crack",
        "The crack is far too small for you to follow.",
        {"east": "pit_top"},
        ["gold_nugget"],
        dark=True,
    ),
    "hall_of_mists": Room(
        "Hall of Mists",
        "You are at one end of a vast hall stretching forward out of\n"
        "sight to the west. There are openings to either side.\n"
        "The hall is filled with wisps of white mist swaying to and\n"
        "fro almost as if alive.",
        {"up": "pit_top", "west": "hall_of_mt_king", "south": "nugget_room",
         "north": "fissure"},
        dark=True,
    ),
    "fissure": Room(
        "At Fissure",
        "You are on the east bank of a fissure slicing clear across\n"
        "the hall. The mist is quite thick here, and the fissure is\n"
        "too wide to jump.",
        {"south": "hall_of_mists"},
        dark=True,
        special="fissure",
    ),
    "nugget_room": Room(
        "Nugget of Gold Room",
        "This is a low room with a crude note on the wall. The note\n"
        "says 'You won't get it up the steps.'",
        {"north": "hall_of_mists"},
        ["large_gold"],
        dark=True,
    ),
    "hall_of_mt_king": Room(
        "Hall of the Mountain King",
        "You are in the hall of the mountain king, with passages\n"
        "off in all directions. A huge green fierce snake bars\n"
        "the way!",
        {"east": "hall_of_mists", "north": "low_passage", "south": "south_chamber",
         "west": "west_chamber"},
        dark=True,
        special="snake",
    ),
    "low_passage": Room(
        "Low N/S Passage",
        "You are in a low N/S passage at a hole in the floor.\n"
        "The hole goes down to an E/W passage.",
        {"south": "hall_of_mt_king", "down": "dirty_passage", "north": "y2_room"},
        dark=True,
    ),
    "dirty_passage": Room(
        "Dirty Passage",
        "You are in a dirty broken passage. To the east is a crawl.\n"
        "To the west is a large passage. Above you is a hole to another passage.",
        {"up": "low_passage", "east": "brink_of_pit", "west": "dusty_rock"},
        dark=True,
    ),
    "brink_of_pit": Room(
        "Brink of Pit",
        "You are on the brink of a thirty foot pit with a massive\n"
        "orange column down one wall. You could climb down here but\n"
        "you could not get back up.",
        {"west": "dirty_passage", "down": "bottom_of_pit"},
        dark=True,
    ),
    "bottom_of_pit": Room(
        "Bottom of Pit",
        "You are at the bottom of the pit with a broken floor.\n"
        "There is a large opening above, but no way to reach it.\n"
        "A crawl leads south.",
        {"south": "secret_ns_canyon"},
        ["diamonds"],
        dark=True,
    ),
    "secret_ns_canyon": Room(
        "Secret N/S Canyon",
        "You are in a secret N/S canyon above a large room.\n"
        "A passage goes south from here.",
        {"north": "bottom_of_pit", "south": "secret_canyon_2"},
        dark=True,
    ),
    "secret_canyon_2": Room(
        "Secret Canyon",
        "You are in a secret canyon which here runs E/W.\n"
        "There is a tiny slot in the rock to the east.",
        {"north": "secret_ns_canyon", "east": "hall_of_mt_king"},
        dark=True,
    ),
    "dusty_rock": Room(
        "Dusty Rock Room",
        "You are in a large room full of dusty rocks. There is a\n"
        "big hole in the floor. A passage leads east.",
        {"east": "dirty_passage", "down": "complex_junction"},
        dark=True,
    ),
    "complex_junction": Room(
        "At Complex Junction",
        "You are at a complex junction. A low hands-and-knees passage\n"
        "from the north joins a higher crawl from the east to make a\n"
        "walking passage going west. There is also a large room above.",
        {"up": "dusty_rock", "west": "bedquilt", "north": "shell_room"},
        dark=True,
    ),
    "bedquilt": Room(
        "Bedquilt",
        "You are in Bedquilt, a long east/west passage with holes\n"
        "everywhere. To explore at random select north, south, up, or down.",
        {"east": "complex_junction", "west": "swiss_cheese"},
        dark=True,
    ),
    "swiss_cheese": Room(
        "Swiss Cheese Room",
        "You are in a room whose walls resemble swiss cheese.\n"
        "Obvious passages lead east, south, and west.",
        {"east": "bedquilt", "south": "tall_canyon", "west": "oriental_room"},
        dark=True,
    ),
    "tall_canyon": Room(
        "Tall E/W Canyon",
        "You are in a tall east/west canyon. A low tight crawl goes\n"
        "three feet north and seems to open up.",
        {"north": "swiss_cheese", "east": "dead_end_cave"},
        ["silver_bars"],
        dark=True,
    ),
    "dead_end_cave": Room(
        "Dead End",
        "You are at a dead end. The passage goes west.",
        {"west": "tall_canyon"},
        ["chest"],
        dark=True,
    ),
    "oriental_room": Room(
        "Oriental Room",
        "This is the oriental room. Ancient oriental cave drawings\n"
        "cover the walls. A passage runs north and another runs south.",
        {"north": "swiss_cheese", "south": "misty_cavern"},
        ["vase"],
        dark=True,
    ),
    "misty_cavern": Room(
        "Misty Cavern",
        "You are following a wide path around the outer edge of a\n"
        "large cavern. Far below, through a heavy white mist, strange\n"
        "lights can be seen flickering.",
        {"north": "oriental_room", "south": "alcove"},
        dark=True,
    ),
    "alcove": Room(
        "Alcove",
        "You are in an alcove. A small passage leads north.\n"
        "The floor here is covered with ancient carvings.",
        {"north": "misty_cavern"},
        ["emerald"],
        dark=True,
    ),
    "south_chamber": Room(
        "South Side Chamber",
        "You are in the south side chamber of the hall of the\n"
        "mountain king.",
        {"north": "hall_of_mt_king"},
        ["jewelry"],
        dark=True,
    ),
    "west_chamber": Room(
        "West Side Chamber",
        "You are in the west side chamber of the hall of the\n"
        "mountain king. A passage continues west and up here.",
        {"east": "hall_of_mt_king", "west": "crossover"},
        ["rare_coins"],
        dark=True,
    ),
    "crossover": Room(
        "Crossover",
        "You are at a crossover of a high N/S passage and a low\n"
        "E/W one.",
        {"east": "west_chamber", "north": "dead_end_2"},
        dark=True,
    ),
    "dead_end_2": Room(
        "Dead End",
        "Dead end passage. You'll have to go back south.",
        {"south": "crossover"},
        ["pearl"],
        dark=True,
    ),
    "y2_room": Room(
        "Y2 Room",
        'There is a large "Y2" on a rock in the center of the room.\n'
        "You can go south or climb the wall here.",
        {"south": "low_passage"},
        dark=True,
    ),
    "shell_room": Room(
        "Shell Room",
        "You're in a large room carved out of sedimentary rock.\n"
        "The floor and walls are littered with tiny shells embedded\n"
        "in the stone. A shallow passage proceeds downward.",
        {"south": "complex_junction", "down": "ragged_corridor"},
        ["golden_eggs"],
        dark=True,
    ),
    "ragged_corridor": Room(
        "Ragged Corridor",
        "You are in a long sloping corridor with ragged sharp walls.",
        {"up": "shell_room"},
        ["trident"],
        dark=True,
    ),
    "stream_chamber": Room(
        "Stream Chamber",
        "You are in a small chamber where a stream enters from the south\n"
        "and exits through a small grate in the floor.",
        {"up": "building", "south": "below_grate"},
        dark=True,
    ),
}

ITEMS: dict[str, Item] = {
    "keys":         Item("set of keys", "A set of brass keys."),
    "food":         Item("tasty food", "Some delicious food."),
    "bottle_water": Item("bottle of water", "A small bottle of water."),
    "lamp":         Item("brass lamp", "A shiny brass lamp (providing light)."),
    "rod":          Item("black rod", "A three foot black rod with a rusty star on an end."),
    "bird":         Item("little bird", "A cheerful little bird.", takeable=False),
    "gold_nugget":  Item("gold nugget", "A large sparkling gold nugget.", score=10),
    "large_gold":   Item("large gold nugget", "A large gold nugget. Heavy!", score=10),
    "diamonds":     Item("several diamonds", "Several large sparkling diamonds.", score=10),
    "silver_bars":  Item("silver bars", "Bars of silver.", score=5),
    "jewelry":      Item("precious jewelry", "Precious jewelry.", score=5),
    "rare_coins":   Item("rare coins", "Many rare coins.", score=5),
    "chest":        Item("treasure chest", "A treasure chest, filled with pearls!", score=15),
    "vase":         Item("ming vase", "A delicate ming vase.", score=5),
    "emerald":      Item("egg-sized emerald", "An emerald the size of a plover's egg.", score=10),
    "pearl":        Item("glistening pearl", "A glistening pearl.", score=10),
    "golden_eggs":  Item("golden eggs", "Several large golden eggs.", score=10),
    "trident":      Item("jeweled trident", "A jeweled trident.", score=5),
}

_DIRECTIONS = {
    "n": "north", "s": "south", "e": "east", "w": "west",
    "u": "up", "d": "down",
    "north": "north", "south": "south", "east": "east", "west": "west",
    "up": "up", "down": "down", "enter": "enter", "out": "out",
    "in": "enter",
}

_TREASURE_ITEMS = {k for k, v in ITEMS.items() if v.score > 0}
_MAX_SCORE = sum(v.score for v in ITEMS.values())


# ---------------------------------------------------------------------------
# Game state
# ---------------------------------------------------------------------------
@dataclass
class State:
    player: str = ""
    room: str = "road"
    inventory: list[str] = field(default_factory=list)
    treasures_deposited: list[str] = field(default_factory=list)
    grate_open: bool = False
    snake_scared: bool = False
    fissure_bridged: bool = False
    moves: int = 0
    score: int = 0


# ---------------------------------------------------------------------------
# Game class
# ---------------------------------------------------------------------------
class AdventureGame(BaseGame):
    name        = "adventure"
    description = "Colossal Cave Adventure"
    min_players = 1
    max_players = 1

    def __init__(self) -> None:
        self._state = State()
        self._over = False
        self._rooms = {k: Room(r.name, r.description, dict(r.exits), list(r.items), r.dark, r.special)
                       for k, r in ROOMS.items()}

    def start(self, players: list[str]) -> str:
        self._state.player = players[0]
        return (
            "ADVENTURE: The Colossal Cave\n"
            "Inspired by the original by Crowther & Woods (1977)\n"
            "Collect treasures and bring them to the building.\n"
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

        if cmd in _DIRECTIONS:
            return self._move(_DIRECTIONS[cmd])
        if cmd == "go" and arg in _DIRECTIONS:
            return self._move(_DIRECTIONS[arg])
        if cmd in ("look", "l"):
            return self._look()
        if cmd in ("inventory", "i"):
            return self._inventory()
        if cmd in ("take", "get", "grab"):
            return self._take(arg)
        if cmd in ("drop", "put"):
            return self._drop(arg)
        if cmd == "open":
            return self._open(arg)
        if cmd in ("examine", "x", "read"):
            return self._examine(arg)
        if cmd == "wave":
            return self._wave(arg)
        if cmd == "throw":
            return self._throw(arg)
        if cmd == "score":
            return self._show_score()
        if cmd == "help":
            return self._help()
        if cmd in ("quit", "q"):
            self._over = True
            return f"Your score: {self._state.score}/{_MAX_SCORE} in {self._state.moves} moves.\nThanks for playing!"

        if text.isalpha() and text.lower() in ("north", "south", "east", "west", "up", "down"):
            return self._move(text.lower())

        return "I don't understand that."

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _look(self) -> str:
        room = self._rooms[self._state.room]
        if room.dark and not self._has_light():
            return "It is now pitch dark. If you proceed you will likely fall into a pit."
        lines = [room.name, room.description]
        if room.items:
            for item_id in room.items:
                item = ITEMS.get(item_id)
                if item:
                    lines.append(f"There is a {item.name} here.")
        return "\n".join(lines)

    def _move(self, direction: str) -> str:
        room = self._rooms[self._state.room]

        # Grate check
        if room.special == "grate" and direction == "down":
            if not self._state.grate_open:
                return "The grate is locked. You need to unlock it first."

        # Snake blocks
        if room.special == "snake" and direction in ("north", "south", "west") and not self._state.snake_scared:
            return "A huge green fierce snake bars the way!"

        # Fissure check
        if room.special == "fissure" and direction == "west":
            if not self._state.fissure_bridged:
                return "The fissure is too wide to cross."

        if direction not in room.exits:
            return "You can't go that way."

        next_room_id = room.exits[direction]
        next_room = self._rooms[next_room_id]

        if next_room.dark and not self._has_light():
            if random.random() < 0.25:
                self._over = True
                return "You fell into a pit and broke every bone in your body!\n\n*** You have died ***"

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
            if item_id == "bird":
                return "The bird is frightened and won't let you catch it."
            return f"You can't take the {item.name}."
        if len(self._state.inventory) >= 7:
            return "You can't carry any more."
        room.items.remove(item_id)
        self._state.inventory.append(item_id)
        return f"OK"

    def _drop(self, name: str) -> str:
        if not name:
            return "Drop what?"
        item_id = self._find_item(name, self._state.inventory)
        if not item_id:
            return "You aren't carrying it."
        self._state.inventory.remove(item_id)
        # Deposit treasure at building
        if self._state.room == "building" and item_id in _TREASURE_ITEMS:
            self._state.treasures_deposited.append(item_id)
            points = ITEMS[item_id].score
            self._state.score += points
            result = f"You deposit the {ITEMS[item_id].name} in the building. (+{points} points)"
            if self._state.score >= _MAX_SCORE:
                self._over = True
                result += (
                    f"\n\nYou scored {_MAX_SCORE}/{_MAX_SCORE}!\n"
                    "You have explored the cave and recovered all the treasures!\n"
                    f"Completed in {self._state.moves} moves."
                )
            return result
        self._rooms[self._state.room].items.append(item_id)
        return "OK"

    def _open(self, name: str) -> str:
        if "grate" in name:
            if self._state.room != "grate_outside":
                return "There's no grate here."
            if "keys" not in self._state.inventory:
                return "You don't have a key."
            self._state.grate_open = True
            return "The grate is now unlocked and open."
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

    def _wave(self, name: str) -> str:
        if "rod" in name and "rod" in self._state.inventory:
            if self._state.room == "fissure":
                self._state.fissure_bridged = True
                return "A crystal bridge now spans the fissure."
            return "Nothing happens."
        return "You aren't carrying that."

    def _throw(self, name: str) -> str:
        if "rod" in name and "rod" in self._state.inventory:
            room = self._rooms[self._state.room]
            if room.special == "snake":
                self._state.snake_scared = True
                self._state.inventory.remove("rod")
                self._rooms[self._state.room].items.append("rod")
                return "The snake is frightened by the rod and slithers away!"
            return "Thrown."
        return "You aren't carrying that."

    def _inventory(self) -> str:
        if not self._state.inventory:
            return "You're not carrying anything."
        lines = ["You are currently holding:"]
        for item_id in self._state.inventory:
            lines.append(f"  {ITEMS[item_id].name}")
        return "\n".join(lines)

    def _show_score(self) -> str:
        return (
            f"Score: {self._state.score}/{_MAX_SCORE}\n"
            f"Moves: {self._state.moves}\n"
            f"Treasures deposited: {len(self._state.treasures_deposited)}"
        )

    def _help(self) -> str:
        return (
            "Commands:\n"
            "  north/south/east/west (n/s/e/w) — move\n"
            "  up/down (u/d)        — move vertically\n"
            "  look (l)             — describe the room\n"
            "  take/get <item>      — pick up an item\n"
            "  drop <item>          — drop or deposit an item\n"
            "  open <object>        — open something\n"
            "  examine/x <item>     — look at an item\n"
            "  wave <item>          — wave an item\n"
            "  throw <item>         — throw an item\n"
            "  inventory (i)        — show what you're carrying\n"
            "  score                — show your score\n"
            "  quit                 — end the game\n\n"
            "Tip: Bring treasures back to the building to score points."
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _has_light(self) -> bool:
        return "lamp" in self._state.inventory

    def _find_item(self, name: str, item_list: list[str]) -> str | None:
        name = name.lower().strip()
        for item_id in item_list:
            item = ITEMS.get(item_id)
            if not item:
                continue
            if name == item_id or name == item.name.lower():
                return item_id
            if name in item.name.lower() or name in item_id:
                return item_id
        return None
