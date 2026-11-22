"""SQLite storage: one file, WAL mode, all state here so a restart loses nothing."""
import json
import random
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY,
    callsign TEXT NOT NULL,
    callsign_lc TEXT NOT NULL UNIQUE,
    key_hash TEXT NOT NULL UNIQUE,
    kind TEXT,
    about TEXT,
    hidden INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS pictures (
    id INTEGER PRIMARY KEY,
    level INTEGER NOT NULL,
    seed INTEGER NOT NULL,
    shapes TEXT NOT NULL,
    created REAL NOT NULL,
    UNIQUE(level, seed)
);
CREATE TABLE IF NOT EXISTS seen (
    player_id INTEGER NOT NULL,
    picture_id INTEGER NOT NULL,
    PRIMARY KEY (player_id, picture_id)
);
CREATE TABLE IF NOT EXISTS letters (
    id TEXT PRIMARY KEY,
    picture_id INTEGER NOT NULL,
    describer_id INTEGER NOT NULL,
    level INTEGER NOT NULL,
    word TEXT NOT NULL,
    status TEXT NOT NULL,              -- draft, open, closed, discarded
    text TEXT,
    words INTEGER,
    created REAL NOT NULL,
    sent REAL,
    closed REAL,
    close_reason TEXT,
    hidden INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS letters_status ON letters(status, level);
CREATE INDEX IF NOT EXISTS letters_picture ON letters(picture_id);
CREATE INDEX IF NOT EXISTS letters_describer ON letters(describer_id);
CREATE TABLE IF NOT EXISTS builds (
    id TEXT PRIMARY KEY,
    letter_id TEXT,
    round_id TEXT,
    builder_id INTEGER NOT NULL,
    shapes TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,              -- building, submitted, expired, cancelled
    note TEXT,
    note_words INTEGER,
    score REAL,
    overlap REAL,
    created REAL NOT NULL,
    updated REAL NOT NULL,
    submitted REAL
);
CREATE INDEX IF NOT EXISTS builds_letter ON builds(letter_id);
CREATE INDEX IF NOT EXISTS builds_builder ON builds(builder_id, status);
CREATE TABLE IF NOT EXISTS matches (
    id TEXT PRIMARY KEY,
    creator_id INTEGER NOT NULL,
    guest_id INTEGER,
    open INTEGER NOT NULL,
    rounds INTEGER NOT NULL,
    start_level INTEGER NOT NULL,
    status TEXT NOT NULL,              -- waiting, playing, finished, abandoned
    created REAL NOT NULL,
    updated REAL NOT NULL,
    finished REAL,
    hidden INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS matches_status ON matches(status, open);
CREATE TABLE IF NOT EXISTS rounds (
    id TEXT PRIMARY KEY,
    match_id TEXT NOT NULL,
    n INTEGER NOT NULL,
    level INTEGER NOT NULL,
    picture_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    describer_id INTEGER NOT NULL,
    builder_id INTEGER NOT NULL,
    build_id TEXT NOT NULL,
    status TEXT NOT NULL,              -- playing, finished, abandoned
    started REAL NOT NULL,
    finished REAL,
    hidden INTEGER NOT NULL DEFAULT 0,
    UNIQUE(match_id, n)
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    round_id TEXT NOT NULL,
    player_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    words INTEGER NOT NULL,
    created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_round ON messages(round_id);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT,
    public INTEGER NOT NULL,
    kind TEXT NOT NULL,
    data TEXT NOT NULL,
    created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS events_match ON events(match_id, id);
CREATE INDEX IF NOT EXISTS events_public ON events(public, id);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def tx(conn: sqlite3.Connection):
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


_C = "bdfghjklmnprstvz"
_V = "aeiou"


def new_id(conn: sqlite3.Connection) -> str:
    """Pronounceable, lowercase, no digits (so an id can be said in a chat that refuses numbers): 'tamorik'."""
    while True:
        s = "".join(secrets.choice(_C if i % 2 == 0 else _V) for i in range(7))
        taken = conn.execute(
            "SELECT 1 FROM letters WHERE id=? UNION SELECT 1 FROM builds WHERE id=? UNION SELECT 1 FROM matches WHERE id=? "
            "UNION SELECT 1 FROM rounds WHERE id=?", (s, s, s, s)).fetchone()
        if not taken:
            return s


def now() -> float:
    return time.time()


def dumps(v) -> str:
    return json.dumps(v, separators=(",", ":"))


def loads(s: str):
    return json.loads(s)


# Words painted on the frame of every describer's picture. Plain, concrete, no colours, shapes or numbers.
ROUND_WORDS = """
acorn adder alder almond amber anchor anvil apron arch arrow attic badger bagel banjo barley barn basket beacon
beaver bell bench birch biscuit bison blanket bobbin bonnet bottle boulder bramble bridge brook broom bucket buckle
button cabin cactus camel candle canoe canyon carpet carrot castle cedar cellar chalk cherry chimney cider clover
cobble comet copper coral cotton cradle crane crater cricket crow cupboard daisy dingo dolphin donkey dragon
drum eagle easel elbow elm ember fable falcon feather fennel ferry fiddle finch fjord flannel flint fog forest fossil
fox garlic garnet gate gecko ginger glacier goose granite gravel gull hammer harbour harp hazel hearth hedge heron
hinge honey hornet hound husk igloo inlet island ivy jackal jasmine jetty jigsaw juniper kayak kettle kiln kite
koala ladder lagoon lantern larch lemon lentil lichen linen lizard lobster locket loom lynx magpie mallet maple
marble meadow melon mitten molar moth mussel needle nettle nutmeg oak oar oasis olive onion orchard osprey otter
owl oyster paddle pantry parrot pebble pelican pepper pigeon pillow pine pistachio plum pocket pony poppy puffin
pumpkin quail quarry quill quince rabbit radish raft raven reed ribbon river robin rocket rope saddle saffron
salmon sandal satchel scarf shovel shrimp sickle sledge slipper sparrow spindle sponge spoon spruce squid
squirrel starling stork straw sundial swallow swan teapot thimble thistle thrush timber toad tortoise trowel
trumpet tulip tunnel turnip turtle umbrella valley velvet violin vulture wagon walnut walrus weasel whale wheat
whistle willow window wren yak yarrow zebra zither
""".split()


def choose_word(avoid: set[str] = frozenset()) -> str:
    options = [w for w in ROUND_WORDS if w.upper() not in avoid]
    return random.choice(options).upper()
