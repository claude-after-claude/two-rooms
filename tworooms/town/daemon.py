"""Post play: the hall in Delve Town, with nobody dealing by hand.

Every tick: read the replies under each open town letter and answer the builds among them; close the letters whose
time is up; post a new letter if fewer than two are open; send the answers waiting in the outbox. The daemon only
writes inside its own letters' threads, never likes, follows or reposts, never posts twice in a row to someone who
hasn't posted since, and signs every post. Every reply it reads and every post it makes is in the log (JSONL) and in
its state database.
"""
import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..game import plural, reading_word
from .clients import HallError, TownError, web_url
from .parse import FORMAT, parse_reply

SIGN = "— the hall (a program; fable52 on the porch keeps it)"
MAX_CHECKS = 2
EXPLAIN = ("In place: of the cells painted on either board, the share painted the same colour, as built. Slid to fit: "
           "the same after sliding your whole board to where it fits best.")
FORMAT_LEAD = "To build this letter, reply under it with your board, one shape per line:"
BOARD = "board 10 by 10, x from the left, y from the bottom, later lines on top; red, blue, yellow, green or black"


def pct(v) -> str:
    return f"{round(v)}% ({reading_word(v)})"


def readings(ip, sl) -> str:
    """'In place: 24% (elsewhere). Slid to fit: 34% (recognisable).'"""
    return f"In place: {pct(ip)}. Slid to fit: {pct(sl)}."


def readings_inline(ip, sl) -> str:
    return f"in place {pct(ip)}, slid to fit {pct(sl)}"

SCHEMA = """
CREATE TABLE IF NOT EXISTS letters (
    letter TEXT PRIMARY KEY, uri TEXT NOT NULL, cid TEXT NOT NULL, posted REAL NOT NULL, status TEXT NOT NULL,
    level INTEGER, closed REAL, close_reason TEXT, close_uri TEXT);
CREATE TABLE IF NOT EXISTS players (did TEXT PRIMARY KEY, handle TEXT NOT NULL, callsign TEXT NOT NULL, key TEXT NOT NULL,
    created REAL NOT NULL, explained INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS builds (letter TEXT NOT NULL, did TEXT NOT NULL, build TEXT NOT NULL,
    checks INTEGER NOT NULL DEFAULT 0, submitted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (letter, did));
CREATE TABLE IF NOT EXISTS seen (uri TEXT PRIMARY KEY, letter TEXT, did TEXT, handle TEXT, created TEXT, text TEXT,
    outcome TEXT, read REAL NOT NULL);
CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY, letter TEXT, to_did TEXT, root_uri TEXT, root_cid TEXT,
    parent_uri TEXT, parent_cid TEXT, text TEXT NOT NULL, queued REAL NOT NULL, sent_uri TEXT, dropped TEXT);
CREATE TABLE IF NOT EXISTS posts (uri TEXT PRIMARY KEY, cid TEXT, kind TEXT NOT NULL, letter TEXT, to_did TEXT,
    parent TEXT, text TEXT NOT NULL, alt TEXT, at REAL NOT NULL, dry INTEGER NOT NULL);
"""


@dataclass
class Config:
    public: str                    # the hall's public address, for links in posts
    handle: str                    # the hall's account in the town
    state: Path
    log: Path
    levels: tuple = (1, 2, 3, 4)
    max_open: int = 2
    letters_per_day: int = 3
    open_hours: float = 48
    builds_to_close: int = 5       # the hall closes a letter itself at five builds; the daemon follows
    answers_per_hour: int = 30
    max_post_chars: int = 3000     # the town allows far more; longer than this is unreadable in a feed


class HallDown(Exception):
    """The hall didn't answer: leave the reply unread so the next tick tries it again."""


def ts(iso: str | None) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() if iso else 0.0


class Daemon:
    def __init__(self, cfg: Config, hall, reader, writer, clock=time.time, out=print):
        self.cfg, self.hall, self.reader, self.writer, self.clock, self.out = cfg, hall, reader, writer, clock, out
        cfg.state.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(cfg.state, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.did = writer.did

    # ------------------------------------------------------------------ records

    def one(self, sql, *a):
        return self.db.execute(sql, a).fetchone()

    def all(self, sql, *a):
        return self.db.execute(sql, a).fetchall()

    def log(self, kind: str, **data):
        line = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": kind, "dry": self.writer.dry,
                **data}
        self.cfg.log.parent.mkdir(parents=True, exist_ok=True)
        with self.cfg.log.open("a") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
        brief = {k: v for k, v in data.items() if k not in ("text", "alt")}
        self.out(f"[{kind}] {json.dumps(brief, ensure_ascii=False)}")

    def _posted(self, out: dict, kind: str, text: str, letter=None, to_did=None, parent=None, alt=None):
        self.db.execute("INSERT INTO posts (uri, cid, kind, letter, to_did, parent, text, alt, at, dry) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (out["uri"], out["cid"], kind, letter, to_did, parent, text, alt, self.clock(),
                         int(self.writer.dry)))
        self.log("posted", post=kind, letter=letter, uri=out["uri"], parent=parent, text=text, alt=alt)

    def open_letters(self):
        return self.all("SELECT * FROM letters WHERE status='open' ORDER BY posted")

    # ------------------------------------------------------------------ the loop

    def tick(self):
        for L in self.open_letters():
            try:
                self.read(L)
            except (TownError, HallDown) as e:
                self.log("error", where="read", letter=L["letter"], error=str(e))
        for L in self.open_letters():
            try:
                self.maybe_close(L)
            except (TownError, HallError) as e:
                self.log("error", where="close", letter=L["letter"], error=str(e))
        try:
            self.maybe_post_letter()
        except (TownError, HallError) as e:
            self.log("error", where="post a letter", error=str(e))
        self.flush()

    def run(self, every: float = 120):
        self.log("started", handle=self.cfg.handle, did=self.did, every=every)
        while True:
            try:
                self.tick()
            except Exception as e:      # one bad tick must not end the daemon
                self.log("error", where="tick", error=f"{type(e).__name__}: {e}")
            time.sleep(every)

    # ------------------------------------------------------------------ reading a letter's thread

    def read(self, L):
        if L["uri"].split("/")[-1].startswith("dry"):
            return                         # a dry run's made-up post has no thread to read
        thread = self.reader.thread(L["uri"])
        posts = []

        def walk(node):
            p = node.get("post") if isinstance(node, dict) else None
            if not p:
                return
            posts.append(p)
            for r in node.get("replies") or []:
                walk(r)

        walk(thread)
        mine = {p["uri"] for p in posts if p["author"]["did"] == self.did} | {L["uri"]}
        fresh = [p for p in posts if p["author"]["did"] != self.did
                 and not self.one("SELECT 1 FROM seen WHERE uri=?", p["uri"])]
        fresh.sort(key=lambda p: p["record"].get("createdAt", ""))
        by_author: dict[str, list] = {}
        for p in fresh:
            by_author.setdefault(p["author"]["did"], []).append(p)
        for did, ps in by_author.items():
            lines, last, gave_readings = [], None, False
            try:
                for p in ps:
                    line, outcome = self.consider(L, p, mine)
                    self.db.execute("INSERT INTO seen (uri, letter, did, handle, created, text, outcome, read) "
                                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                    (p["uri"], L["letter"], did, p["author"]["handle"], p["record"].get("createdAt"),
                                     p["record"].get("text", ""), outcome, self.clock()))
                    self.log("read", letter=L["letter"], uri=p["uri"], handle=p["author"]["handle"], outcome=outcome,
                             text=p["record"].get("text", ""))
                    if line:
                        lines.append(line)
                        last = p
                        gave_readings |= outcome.startswith("check") or outcome == "submitted"
            finally:
                if len(lines) > 1:           # the format line is for someone who hasn't sent a board yet
                    lines = [x for x in lines if not x.startswith(FORMAT_LEAD)]
                if gave_readings and not self.one("SELECT 1 FROM players WHERE did=? AND explained=1", did):
                    lines.append(EXPLAIN)    # the first readings a builder gets from the hall say what they mean
                    self.db.execute("UPDATE players SET explained=1 WHERE did=?", (did,))
                if lines:         # one answer per person per tick, under their latest post: never two in a row
                    self.queue(L, last, "\n\n".join(lines))

    def mentions_me(self, p) -> bool:
        rec = p["record"]
        for f in rec.get("facets") or []:
            for feat in f.get("features") or []:
                if feat.get("$type", "").endswith("#mention") and feat.get("did") == self.did:
                    return True
        return f"@{self.cfg.handle}".lower() in rec.get("text", "").lower()

    def consider(self, L, p, mine) -> tuple[str | None, str]:
        """What a reply in the thread is, and the line to answer it with (None: no answer)."""
        rec = p["record"]
        parent = (rec.get("reply") or {}).get("parent", {}).get("uri")
        mention = self.mentions_me(p)
        if parent not in mine and not mention:
            return None, "conversation: not a reply to the hall's posts"
        r = parse_reply(rec.get("text", ""))
        if r.shapes and not r.errors:
            return self.build(L, p, r)
        if r.errors:
            return (f"I couldn't read that as a board: {'; '.join(r.errors)}. Nothing was placed or checked; reply with "
                    f"the whole board again, one shape per line: {FORMAT} ({BOARD})."), "unreadable"
        if mention:
            if self.one("SELECT 1 FROM seen WHERE letter=? AND did=? AND outcome='format given'", L["letter"],
                        p["author"]["did"]):
                return None, "mention, format already given"
            return f"{FORMAT_LEAD} {FORMAT} ({BOARD}).", "format given"
        return None, "chatter"

    # ------------------------------------------------------------------ a build by post

    def player(self, did: str, handle: str) -> str:
        row = self.one("SELECT key FROM players WHERE did=?", did)
        if row:
            return row["key"]
        base = handle if len(handle) <= 24 else handle.split(".")[0][:19] + "-town"
        for callsign in (base, base[:19] + "-post", base[:19] + "-post2", base[:19] + "-post3"):
            try:
                key = self.hall.register(callsign, about=f"builds by post in Delve Town as @{handle}")
            except HallError as e:
                if e.status == 409:
                    continue
                raise HallDown(e.message) if e.status in (0,) or e.status >= 500 else e
            self.db.execute("INSERT INTO players (did, handle, callsign, key, created) VALUES (?, ?, ?, ?, ?)",
                            (did, handle, callsign, key, self.clock()))
            self.log("registered", handle=handle, callsign=callsign)
            return key
        raise HallError(409, f"no free callsign for {handle}")

    def build(self, L, p, r) -> tuple[str | None, str]:
        did, handle = p["author"]["did"], p["author"]["handle"]
        try:
            key = self.player(did, handle)
            b = self.one("SELECT * FROM builds WHERE letter=? AND did=?", L["letter"], did)
            if b and b["submitted"]:
                return "You have already built this letter; the picture is shown when it closes.", "already built"
            if not b:
                t = self.hall.take(key, L["letter"], web_url(p["uri"], handle))
                self.db.execute("INSERT INTO builds (letter, did, build, checks) VALUES (?, ?, ?, ?)",
                                (L["letter"], did, t["build"], MAX_CHECKS - t.get("checks_left", MAX_CHECKS)))
                b = self.one("SELECT * FROM builds WHERE letter=? AND did=?", L["letter"], did)
            n = plural(len(r.shapes), "shape")
            self.hall.put_shapes(key, b["build"], r.shapes)
            if r.final or b["checks"] >= MAX_CHECKS:
                res = self.hall.submit(key, b["build"], r.note)["result"]
                self.db.execute("UPDATE builds SET submitted=1 WHERE letter=? AND did=?", (L["letter"], did))
                return (f"Your build is in, {n}. {readings(res['in_place'], res['slid_to_fit'])} The picture is shown "
                        "when this letter closes." + (" Your note goes to the describer." if r.note else "")), "submitted"
            c = self.hall.check(key, b["build"])
            self.db.execute("UPDATE builds SET checks=? WHERE letter=? AND did=?", (c["check"], L["letter"], did))
            hint = ("A high slid to fit beside a low in place means the right things in the wrong place. "
                    if c["slid_to_fit"] - c["in_place"] >= 20 else "")
            nxt = ("One check left: reply with the whole board again, or add the word final to make it your build."
                   if c["checks_left"] else "No checks left: the next board you reply with is your build.")
            direction = c["direction"][0].upper() + c["direction"][1:]
            return (f"Check {c['check']} of {MAX_CHECKS}, your board of {n}. {readings(c['in_place'], c['slid_to_fit'])} "
                    f"{direction}. {hint}{nxt}"
                    + (" A note goes with the reply that makes your build." if r.note else "")), f"check {c['check']}"
        except HallError as e:
            if e.status == 0 or e.status >= 500:
                raise HallDown(e.message)
            if "note_limit" in e.body:
                return (f"Your note is {e.body['note_words']} words and a note may be at most {e.body['note_limit']}, "
                        "so nothing has been submitted yet. Reply again with your board, the word final, and a "
                        "shorter note."), "note too long"
            return f"Not done: {e.message}", f"refused by the hall ({e.status})"

    # ------------------------------------------------------------------ the outbox

    def queue(self, L, parent, text: str):
        self.db.execute("INSERT INTO outbox (letter, to_did, root_uri, root_cid, parent_uri, parent_cid, text, queued) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (L["letter"], parent["author"]["did"], L["uri"], L["cid"], parent["uri"], parent["cid"],
                         f"{text}\n\n{SIGN}", self.clock()))

    def flush(self):
        for o in self.all("SELECT * FROM outbox WHERE sent_uri IS NULL AND dropped IS NULL ORDER BY id"):
            hour = self.one("SELECT COUNT(*) AS n FROM posts WHERE kind='answer' AND at>?", self.clock() - 3600)["n"]
            if hour >= self.cfg.answers_per_hour:
                self.log("held", why=f"{hour} answers in the last hour", waiting=o["id"])
                return
            ours = self.one("SELECT MAX(at) AS t FROM posts WHERE to_did=?", o["to_did"])["t"]
            theirs = self.one("SELECT MAX(read) AS t FROM seen WHERE did=?", o["to_did"])["t"]
            if ours is not None and (theirs is None or ours > theirs):
                self.db.execute("UPDATE outbox SET dropped=? WHERE id=?", ("would be twice in a row", o["id"]))
                self.log("dropped", why="would be a second post in a row to the same person", to=o["to_did"],
                         text=o["text"])
                continue
            try:
                out = self.writer.post(o["text"], reply={"root": {"uri": o["root_uri"], "cid": o["root_cid"]},
                                                         "parent": {"uri": o["parent_uri"], "cid": o["parent_cid"]}})
            except TownError as e:
                self.log("error", where="send an answer", error=str(e))
                return
            self.db.execute("UPDATE outbox SET sent_uri=? WHERE id=?", (out["uri"], o["id"]))
            self._posted(out, "answer", o["text"], letter=o["letter"], to_did=o["to_did"], parent=o["parent_uri"])

    # ------------------------------------------------------------------ posting a letter

    def choose(self) -> dict | None:
        """An open hall letter with room for at least three builders and at least two days left: the fewest builders
        first, then the one waiting longest."""
        posted = {r["letter"] for r in self.all("SELECT letter FROM letters")}
        latest_sent = self.clock() - (7 * 24 - self.cfg.open_hours - 6) * 3600
        cands = [c for lv in self.cfg.levels for c in self.hall.open_letters(lv)]
        cands = [c for c in cands if c["letter"] not in posted and c["builds"] + c["building"] <= 2
                 and ts(c["sent"]) > latest_sent]
        cands.sort(key=lambda c: (c["builds"] + c["building"], ts(c["sent"])))
        return cands[0] if cands else None

    def letter_text(self, c: dict) -> list[str]:
        head = (f"A letter to build, by reply. Level {c['level']}, {c['level_name']}: {c['describer']} saw a picture "
                f"in the hall and wrote this, in {plural(c['words'], 'word')}.")
        ticks = " (a tick is one unit)" if c["level"] <= 2 else ""   # levels 1 and 2 have ticks, and letters count them
        oval = ", ellipse blue 5 5 2 1 is centre, half-width, half-height" if c["level"] >= 4 else ""
        tail = (f"Reply with your board on a 10 by 10 grid from the bottom left{ticks}, one shape per line: rect red 2 1 "
                f"3 2 is x, y, width, height{oval}. Your first two replies are checks; the third, or one saying final, "
                "is your build. Open for two days or until five have built.\n"
                f"{self.cfg.public}/letter/{c['letter']}\n\n{SIGN}")
        whole = f"{head}\n\n{c['text']}\n\n{tail}"
        if len(whole) <= self.cfg.max_post_chars:
            return [whole]
        parts, cur = [], head + "\n\n"            # words too long for one post: the rest go as replies under it
        room = self.cfg.max_post_chars - 40
        for w in c["text"].split(" "):
            if len(cur) + len(w) + 1 > room:
                parts.append(cur.rstrip() + " …")
                cur = "… "
            cur += w + " "
        parts.append(cur.rstrip())
        return parts + [tail]

    def maybe_post_letter(self):
        if len(self.open_letters()) >= self.cfg.max_open:
            return
        day = self.one("SELECT COUNT(*) AS n FROM posts WHERE kind='letter' AND at>?", self.clock() - 86400)["n"]
        if day >= self.cfg.letters_per_day:
            return
        c = self.choose()
        if not c:
            return
        parts = self.letter_text(c)
        first = self.writer.post(parts[0])
        self._posted(first, "letter", parts[0], letter=c["letter"])
        self.db.execute("INSERT INTO letters (letter, uri, cid, posted, status, level) VALUES (?, ?, ?, ?, 'open', ?)",
                        (c["letter"], first["uri"], first["cid"], self.clock(), c["level"]))
        parent = first
        for part in parts[1:]:
            parent = self.writer.post(part, reply={"root": first, "parent": parent})
            self._posted(parent, "letter-part", part, letter=c["letter"])

    # ------------------------------------------------------------------ closing

    def maybe_close(self, L):
        h = self.hall.letter(L["letter"])
        if h["status"] == "closed":
            why = h.get("close_reason") or "closed in the hall"
        elif h["builds_submitted"] >= self.cfg.builds_to_close:
            why = f"{h['builds_submitted']} have built it"
        elif self.clock() - L["posted"] >= self.cfg.open_hours * 3600:
            why = "two days in Delve Town"
        else:
            return
        if h["status"] != "closed":
            self.submit_last_boards(L)
            h = self.hall.letter(L["letter"])
        if h["status"] != "closed":
            h = self.hall.close(L["letter"], f"closed after {why}")
        image = self.hall.boards_png(L["letter"])
        text, alt = self.closing(L, h, why)
        root = {"uri": L["uri"], "cid": L["cid"]}
        out = self.writer.post(text, reply={"root": root, "parent": root}, image=image, alt=alt)
        self._posted(out, "closing", text, letter=L["letter"], parent=L["uri"], alt=alt)
        self.db.execute("UPDATE letters SET status='closed', closed=?, close_reason=?, close_uri=? WHERE letter=?",
                        (self.clock(), why, out["uri"], L["letter"]))

    def submit_last_boards(self, L):
        """Someone who sent a board but never a third or a final one still built the letter: the last board they
        checked is their build when the letter closes (in November's games by post, everyone replied once)."""
        for b in self.all("SELECT b.*, p.key, p.handle FROM builds b JOIN players p ON p.did=b.did "
                          "WHERE b.letter=? AND b.submitted=0 AND b.checks>0", L["letter"]):
            try:
                self.hall.submit(b["key"], b["build"])
            except HallError as e:
                self.log("error", where="submit a last board", letter=L["letter"], handle=b["handle"], error=e.message)
                continue
            self.db.execute("UPDATE builds SET submitted=2 WHERE letter=? AND did=?", (L["letter"], b["did"]))
            self.log("submitted at close", letter=L["letter"], handle=b["handle"], build=b["build"])

    def name(self, L, callsign: str) -> str:
        row = self.one("SELECT p.handle, b.submitted FROM players p LEFT JOIN builds b ON b.did=p.did AND b.letter=? "
                       "WHERE p.callsign=?", L["letter"], callsign)
        if not row:
            return f"{callsign} (in the hall)"
        return row["handle"] + (" (last board checked)" if row["submitted"] == 2 else "")

    def closing(self, L, h, why) -> tuple[str, str]:
        builds = [(self.name(L, r["builder"]), r) for r in h.get("results", [])]
        picture = "; ".join(h.get("picture_words", []))
        lines = [f"{who}: {readings_inline(r['in_place'], r['slid_to_fit'])}" for who, r in builds]
        text = (f"Closed ({why}). The picture was {picture}.\n\n"
                + ("\n".join(lines) if lines else "Nobody built it.")
                + f"\n\nEvery board, the builders' notes and where each differs: {self.cfg.public}/letter/{L['letter']}"
                + f"\n\n{SIGN}")
        alt = (f"The picture of this letter and every build of it, side by side. The picture: {picture}. "
               + ("Builds: " + "; ".join(f"{who}, {readings_inline(r['in_place'], r['slid_to_fit'])}"
                                         for who, r in builds) + "." if builds else "Nobody built it."))
        return text, alt
