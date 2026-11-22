"""Tunable numbers in one place: the level table, colours, limits."""
from dataclasses import dataclass

BOARD = 10.0           # board side in units
CELLS = 80             # scoring raster side; one cell is BOARD / CELLS = 0.125 units
STEP = 0.125           # builder coordinates are multiples of this
MAX_BUILD_SHAPES = 16
PASS_SCORE = 90.0

COLORS = ["red", "blue", "yellow", "green", "black"]
COLOR_INDEX = {c: i + 1 for i, c in enumerate(COLORS)}   # 0 is empty paper


@dataclass(frozen=True)
class Level:
    n: int
    name: str
    grid: float
    budget: int
    blurb: str


LEVELS = {
    1: Level(1, "two blocks", 1.0, 60, "two rectangles, apart"),
    2: Level(2, "four blocks", 1.0, 110, "four rectangles that may touch but never overlap"),
    3: Level(3, "overlaps", 0.5, 140, "four rectangles lying on each other"),
    4: Level(4, "round things", 0.5, 170, "five shapes, rectangles and ellipses"),
    5: Level(5, "corners", 0.5, 200, "six shapes, with triangles too"),
    6: Level(6, "figures", 0.25, 120, "one recognisable thing made of shapes"),
    7: Level(7, "tangle", 0.25, 260, "nine shapes piled on each other, nothing recognisable"),
    8: Level(8, "scene", 0.25, 220, "two things standing in a landscape"),
}

# Live matches
DEFAULT_ROUNDS = 4
MAX_ROUNDS = 8
LEVEL_UP_AT = 90.0
LEVEL_DOWN_BELOW = 70.0

# Letters
LETTER_MAX_BUILDS = 5
LETTER_OPEN_DAYS = 7
MAX_DRAFTS = 3
DESCRIBERS_PER_PICTURE = 3
BUILD_IDLE_HOURS = 24          # a taken letter build with no activity this long gives its slot back
MATCH_IDLE_DAYS = 7
STALE_BOARD_HOURS = 24         # a live board with shapes and no submit this long is waiting on the builder

MAX_MESSAGE_CHARS = 2000
MAX_TOKEN_CHARS = 24
NOTE_WORDS = 60
CALLSIGN_MIN, CALLSIGN_MAX = 2, 24
ABOUT_MAX = 200
