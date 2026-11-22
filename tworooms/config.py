"""Tunable numbers in one place: the level table, colours, limits."""
from dataclasses import dataclass

BOARD = 10.0           # board side in units
CELLS = 80             # scoring raster side; one cell is BOARD / CELLS = 0.125 units
STEP = 0.125           # builder coordinates are multiples of this
MAX_BUILD_SHAPES = 16
SLIDE_CELLS = 24       # "slid to fit" tries every shift of the whole build up to 3 units each way
MAX_CHECKS = 2         # a letter's builder may check the readings twice before the final submit

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
    1: Level(1, "two blocks", 1.0, 25, "two rectangles, apart"),
    2: Level(2, "four blocks", 1.0, 45, "four rectangles that may touch but never overlap"),
    3: Level(3, "overlaps", 0.5, 50, "four rectangles lying on each other"),
    4: Level(4, "round things", 0.5, 55, "five shapes, rectangles and ellipses"),
    5: Level(5, "corners", 0.5, 65, "six shapes, with triangles too"),
    6: Level(6, "figures", 0.25, 50, "one recognisable thing made of shapes"),
    7: Level(7, "tangle", 0.25, 100, "nine shapes piled on each other, nothing recognisable"),
    8: Level(8, "scene", 0.25, 90, "two things standing in a landscape"),
}

# Live matches
DEFAULT_ROUNDS = 4
MAX_ROUNDS = 8
LIVE_BUDGET_FACTOR = 2      # a live round's describer may use twice the level's budget
LEVEL_UP_AT = 75.0          # "in place" reading of a live round
LEVEL_DOWN_BELOW = 40.0

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


def live_budget(level: int) -> int:
    return LEVELS[level].budget * LIVE_BUDGET_FACTOR
