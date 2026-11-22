"""The rules of the hall: players, letters, builds, live matches, visibility, events and `next` sentences.

Every public method returns plain dicts (JSON-ready, with site-relative URLs) or raises GameError with a sentence
saying what was wrong and what to do. Nothing here knows about HTTP.
"""
import hashlib
import random
import secrets
import time

from . import config as C
from . import db as D
from .pictures import generate_with_kind
from .reveal import loss
from .score import readings
from .shapes import ShapeError, describe, normalise
from .words import Refused, check_message, count_words


class GameError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def iso(t: float | None) -> str | None:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)) if t else None


def level_info(n: int) -> dict:
    lv = C.LEVELS[n]
    return {"level": n, "level_name": lv.name, "budget": lv.budget}


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


def pct(v) -> str:
    return "?" if v is None else f"{round(v)}%"


def reading_word(v) -> str:
    """A word for a reading, so nobody needs the scale explained."""
    if v is None:
        return ""
    return "nearly exact" if v >= 70 else "close" if v >= 50 else "recognisable" if v >= 30 else "elsewhere"


def said(v) -> str:
    """'close · 54%'"""
    return "?" if v is None else f"{reading_word(v)} · {round(v)}%"


READING_WORDS = "70% and over: nearly exact; 50 to 69: close; 30 to 49: recognisable; under 30: elsewhere."

READINGS_EXPLAINED = {
    "in_place": "Of all the cells painted on either board, the share painted the same colour, as built.",
    "slid_to_fit": "The same, after sliding the whole build (up to 3 units any way) to where it matches best: "
                   "a high one beside a low in-place means the right things in the wrong place.",
}


class Hall:
    def __init__(self, conn, notify=None, admin_key: str | None = None):
        self.db = conn
        self.notify = notify or (lambda match_id: None)
        self.admin_key = admin_key
        self._last_sweep = 0.0
        self._backfill()

    def _backfill(self):
        """Builds submitted before the two readings existed get their "slid to fit" reading computed once."""
        rows = self.all("SELECT b.*, COALESCE(l.picture_id, r.picture_id) AS pic FROM builds b "
                        "LEFT JOIN letters l ON l.id=b.letter_id LEFT JOIN rounds r ON r.id=b.round_id "
                        "WHERE b.status='submitted' AND b.slid IS NULL")
        if not rows:
            return
        with D.tx(self.db):
            for b in rows:
                res = readings(self.shapes_of(b["pic"]), D.loads(b["shapes"]))
                self.db.execute("UPDATE builds SET score=?, overlap=?, slid=?, slide_dx=?, slide_dy=? WHERE id=?",
                                (res["cells_match"], res["in_place"], res["slid_to_fit"],
                                 round(res["slide"]["right"] * 8), round(res["slide"]["up"] * 8), b["id"]))

    # ------------------------------------------------------------ helpers

    def one(self, sql, *args):
        return self.db.execute(sql, args).fetchone()

    def all(self, sql, *args):
        return self.db.execute(sql, args).fetchall()

    def player(self, pid):
        return self.one("SELECT * FROM players WHERE id=?", pid) if pid else None

    def callsign(self, pid) -> str | None:
        p = self.player(pid)
        return p["callsign"] if p else None

    def is_admin(self, viewer) -> bool:
        return bool(viewer is not None and viewer == "admin")

    def event(self, kind: str, data: dict, public: bool, match_id: str | None = None) -> int:
        cur = self.db.execute(
            "INSERT INTO events (match_id, public, kind, data, created) VALUES (?, ?, ?, ?, ?)",
            (match_id, int(public), kind, D.dumps(data), D.now()))
        if match_id:
            self.notify(match_id)
        return cur.lastrowid

    # ------------------------------------------------------------ players

    def create_player(self, callsign: str, kind: str | None = None, about: str | None = None) -> dict:
        callsign = (callsign or "").strip()
        if not (C.CALLSIGN_MIN <= len(callsign) <= C.CALLSIGN_MAX) or not all(
                ch.isascii() and (ch.isalnum() or ch in ".-_") for ch in callsign):
            raise GameError(400, f"A callsign is {C.CALLSIGN_MIN} to {C.CALLSIGN_MAX} characters: letters, digits, "
                                 "'.', '-' or '_'. For example \"heron\" or \"fable52\".")
        if kind not in (None, "", "agent", "human"):
            raise GameError(400, 'kind is "agent" or "human" (or leave it out).')
        about = (about or "").strip() or None
        if about and len(about) > C.ABOUT_MAX:
            raise GameError(400, f"about is at most {C.ABOUT_MAX} characters.")
        if self.one("SELECT 1 FROM players WHERE callsign_lc=?", callsign.lower()):
            raise GameError(409, f'The callsign "{callsign}" is taken. Pick another one.')
        key = "tr_" + secrets.token_urlsafe(24)
        with D.tx(self.db):
            self.db.execute(
                "INSERT INTO players (callsign, callsign_lc, key_hash, kind, about, created) VALUES (?, ?, ?, ?, ?, ?)",
                (callsign, callsign.lower(), hash_key(key), kind or None, about, D.now()))
        return {
            "callsign": callsign, "key": key,
            "note": "Keep this key: it is the only way to act as this callsign, and there is no way to recover it.",
            "next": "Send the key as 'Authorization: Bearer <key>' from now on. GET /api/hall to see what you can do.",
        }

    def player_by_key(self, key: str | None):
        if not key:
            return None
        if self.admin_key and secrets.compare_digest(key, self.admin_key):
            return "admin"
        return self.one("SELECT * FROM players WHERE key_hash=?", hash_key(key))

    def player_by_callsign(self, callsign: str):
        return self.one("SELECT * FROM players WHERE callsign_lc=?", (callsign or "").lower())

    def update_player(self, me, kind=None, about=None) -> dict:
        if kind not in (None, "", "agent", "human"):
            raise GameError(400, 'kind is "agent" or "human".')
        if about is not None and len(about) > C.ABOUT_MAX:
            raise GameError(400, f"about is at most {C.ABOUT_MAX} characters.")
        with D.tx(self.db):
            if kind is not None:
                self.db.execute("UPDATE players SET kind=? WHERE id=?", (kind or None, me["id"]))
            if about is not None:
                self.db.execute("UPDATE players SET about=? WHERE id=?", (about.strip() or None, me["id"]))
        p = self.player(me["id"])
        return {"callsign": p["callsign"], "kind": p["kind"], "about": p["about"]}

    # ------------------------------------------------------------ pictures

    def picture(self, pid):
        return self.one("SELECT * FROM pictures WHERE id=?", pid)

    def shapes_of(self, picture_id) -> list[dict]:
        return D.loads(self.picture(picture_id)["shapes"])

    def new_picture(self, level: int):
        """A fresh picture. At levels 6 and 8, not a template used by any of the last few pictures at that level."""
        recent = {r["kind"] for r in self.all("SELECT kind FROM pictures WHERE level=? AND kind IS NOT NULL "
                                              "ORDER BY id DESC LIMIT 6", level)}
        for _ in range(12):
            seed = secrets.randbelow(2 ** 31)
            if self.one("SELECT 1 FROM pictures WHERE level=? AND seed=?", level, seed):
                continue
            shapes, kind = generate_with_kind(level, seed)
            if kind is None or not any(k in recent for k in kind.split(" and ")):
                break
        cur = self.db.execute("INSERT INTO pictures (level, seed, shapes, kind, created) VALUES (?, ?, ?, ?, ?)",
                              (level, seed, D.dumps(shapes), kind, D.now()))
        return self.picture(cur.lastrowid)

    def seen(self, player_id, picture_id) -> bool:
        return bool(self.one("SELECT 1 FROM seen WHERE player_id=? AND picture_id=?", player_id, picture_id))

    def mark_seen(self, player_id, picture_id):
        self.db.execute("INSERT OR IGNORE INTO seen (player_id, picture_id) VALUES (?, ?)", (player_id, picture_id))

    def _picture_for_describer(self, me, level: int):
        """Sometimes hand out a picture that another describer already has (up to 3 describers, never said)."""
        fresh_draft = D.now() - 2 * 86400
        rows = self.all(
            """SELECT p.id, COUNT(l.id) AS n FROM pictures p JOIN letters l ON l.picture_id = p.id
               WHERE p.level=? AND l.status != 'discarded' AND (l.status != 'draft' OR l.created > ?)
               GROUP BY p.id HAVING n < ? ORDER BY p.created""", level, fresh_draft, C.DESCRIBERS_PER_PICTURE)
        rows = [r for r in rows if not self.seen(me["id"], r["id"])]
        if rows and random.random() < 1 / 3:
            return self.picture(rows[0]["id"])
        return self.new_picture(level)

    # ------------------------------------------------------------ letters

    def letter(self, lid):
        row = self.one("SELECT * FROM letters WHERE id=?", lid)
        if not row:
            raise GameError(404, f'There is no letter "{lid}". GET /api/letters lists the open ones.')
        return row

    def _letter_counts(self, lid) -> tuple[int, int]:
        """(submitted builds, builds in progress that still hold a slot)"""
        sub = self.one("SELECT COUNT(*) AS n FROM builds WHERE letter_id=? AND status='submitted'", lid)["n"]
        act = self.one("SELECT COUNT(*) AS n FROM builds WHERE letter_id=? AND status='building'", lid)["n"]
        return sub, act

    def create_letter(self, me, level) -> dict:
        try:
            level = int(level)
        except (TypeError, ValueError):
            raise GameError(400, "level is a whole number from 1 to 8.")
        if level not in C.LEVELS:
            raise GameError(400, "level is a whole number from 1 to 8 (1 is two blocks, 8 is a whole scene).")
        drafts = self.all("SELECT id, word FROM letters WHERE describer_id=? AND status='draft'", me["id"])
        if len(drafts) >= C.MAX_DRAFTS:
            ids = ", ".join(d["id"] for d in drafts)
            raise GameError(409, f"You already have {len(drafts)} unsent drafts ({ids}). Send one "
                                 "(POST /api/letters/<id>/send) or discard one (POST /api/letters/<id>/close) first.")
        with D.tx(self.db):
            pic = self._picture_for_describer(me, level)
            avoid = {d["word"] for d in drafts}
            lid = D.new_id(self.db)
            self.db.execute(
                "INSERT INTO letters (id, picture_id, describer_id, level, word, status, created) "
                "VALUES (?, ?, ?, ?, ?, 'draft', ?)", (lid, pic["id"], me["id"], level, D.choose_word(avoid), D.now()))
            self.mark_seen(me["id"], pic["id"])
        return self.letter_view(me, lid)

    def send_letter(self, me, lid, text) -> dict:
        row = self.letter(lid)
        if row["describer_id"] != me["id"]:
            raise GameError(403, "Only the letter's describer can send it.")
        if row["status"] != "draft":
            raise GameError(409, "This letter was already sent; a sent letter cannot be edited.")
        budget = C.LEVELS[row["level"]].budget
        try:
            n = check_message(text, budget_left=budget, exempt=(me["callsign"],), unit="letter")
        except Refused as e:
            raise GameError(422, str(e))
        with D.tx(self.db):
            self.db.execute("UPDATE letters SET status='open', text=?, words=?, sent=? WHERE id=?",
                            (text.strip(), n, D.now(), lid))
            self.event("letter_opened", {"letter": lid, "level": row["level"], "describer": me["callsign"],
                                         "url": f"/letter/{lid}"}, public=True)
        return self.letter_view(me, lid)

    def close_letter(self, me, lid) -> dict:
        row = self.letter(lid)
        if not self.is_admin(me) and row["describer_id"] != me["id"]:
            raise GameError(403, "Only the letter's describer can close it.")
        if row["status"] == "draft":
            with D.tx(self.db):
                self.db.execute("UPDATE letters SET status='discarded', closed=? WHERE id=?", (D.now(), lid))
            return {"letter": lid, "status": "discarded",
                    "next": "The draft is discarded. POST /api/letters {level} for a new picture."}
        if row["status"] != "open":
            raise GameError(409, f"This letter is already {row['status']}.")
        with D.tx(self.db):
            self._close(lid, "closed by its describer")
        return self.letter_view(me, lid)

    def _close(self, lid, reason):
        self.db.execute("UPDATE letters SET status='closed', closed=?, close_reason=? WHERE id=?", (D.now(), reason, lid))
        self.db.execute("UPDATE builds SET status='cancelled', updated=? WHERE letter_id=? AND status='building'",
                        (D.now(), lid))
        sub, _ = self._letter_counts(lid)
        self.event("letter_closed", {"letter": lid, "builds": sub, "reason": reason, "url": f"/letter/{lid}"}, public=True)

    def may_build(self, me, row) -> str | None:
        """None if `me` may take this letter, else the reason why not."""
        if row["status"] != "open":
            return "This letter is no longer open."
        if row["describer_id"] == me["id"]:
            return "You wrote this letter; someone else has to build it."
        if self.one("SELECT 1 FROM builds WHERE letter_id=? AND builder_id=?", row["id"], me["id"]):
            return "You have already built this letter."
        if self.seen(me["id"], row["picture_id"]):
            return "You have already seen this letter's picture (through another letter or round), so you can't build it."
        sub, act = self._letter_counts(row["id"])
        if sub + act >= C.LETTER_MAX_BUILDS:
            return f"This letter already has {C.LETTER_MAX_BUILDS} builders."
        if row["sent"] and row["sent"] < D.now() - C.LETTER_OPEN_DAYS * 86400:
            return "This letter is past its seven days and takes no new builders."
        return None

    def list_letters(self, me, level=None, limit: int = 50) -> dict:
        self.sweep()
        sql = "SELECT * FROM letters WHERE status='open' AND hidden=0"
        args = []
        if level:
            sql += " AND level=?"
            args.append(int(level))
        rows = self.all(sql + " ORDER BY sent DESC", *args)
        out = []
        for r in rows:
            if me and me != "admin" and self.may_build(me, r):
                continue
            out.append(self._letter_card(r))
            if len(out) >= limit:
                break
        if me and me != "admin":
            nxt = ("Pick one and take it: POST /api/letters/<id>/builds. You'll get its words and an empty board."
                   if out else "No letter is waiting for you right now. Describe a picture instead: POST /api/letters {\"level\": 1}.")
        else:
            nxt = "Make a callsign (POST /api/players) to build one of these."
        return {"letters": out, "count": len(out), "next": nxt}

    def _letter_card(self, r) -> dict:
        sub, act = self._letter_counts(r["id"])
        return {
            "letter": r["id"], **level_info(r["level"]), "describer": self.callsign(r["describer_id"]),
            "text": r["text"], "words": r["words"], "builds": sub, "building": act, "sent": iso(r["sent"]),
            "url": f"/letter/{r['id']}",
        }

    def can_see_letter_picture(self, viewer, row) -> bool:
        if self.is_admin(viewer):
            return True
        if row["status"] == "closed" and not row["hidden"]:
            return True
        if viewer is None:
            return False
        if row["describer_id"] == viewer["id"]:
            return True
        return bool(self.one("SELECT 1 FROM builds WHERE letter_id=? AND builder_id=? AND status='submitted'",
                             row["id"], viewer["id"]))

    def letter_view(self, viewer, lid) -> dict:
        self.sweep()
        r = self.letter(lid)
        mine = viewer not in (None, "admin") and r["describer_id"] == viewer["id"]
        if r["status"] in ("draft", "discarded") and not (mine or self.is_admin(viewer)):
            raise GameError(404, f'There is no letter "{lid}".')
        if r["hidden"] and not (mine or self.is_admin(viewer)):
            raise GameError(404, f'There is no letter "{lid}".')
        out = {
            "letter": lid, **level_info(r["level"]), "status": r["status"], "describer": self.callsign(r["describer_id"]),
            "word": r["word"], "url": f"/letter/{lid}", "created": iso(r["created"]), "sent": iso(r["sent"]),
        }
        if r["status"] != "draft":
            out.update(text=r["text"], words=r["words"])
        sub, act = self._letter_counts(lid)
        out.update(builds_submitted=sub, builds_in_progress=act)
        see = self.can_see_letter_picture(viewer, r)
        if see:
            out["picture_url"] = f"/api/letters/{lid}/picture.png"
            builds = self.all("SELECT * FROM builds WHERE letter_id=? AND status='submitted' ORDER BY submitted", lid)
            out["results"] = [self._result_card(b, r["picture_id"]) for b in builds]
            if r["status"] == "closed":
                out["same_picture"] = [
                    {"letter": o["id"], "describer": self.callsign(o["describer_id"]), "url": f"/letter/{o['id']}"}
                    for o in self.all("SELECT * FROM letters WHERE picture_id=? AND id!=? AND status='closed' AND hidden=0",
                                      r["picture_id"], lid)]
        if r["status"] == "closed":
            out["closed"] = iso(r["closed"])
            out["close_reason"] = r["close_reason"]
        my_build = None
        if viewer not in (None, "admin"):
            my_build = self.one("SELECT * FROM builds WHERE letter_id=? AND builder_id=? ORDER BY created DESC LIMIT 1",
                                lid, viewer["id"])
            if my_build:
                out["your_build"] = {"build": my_build["id"], "status": my_build["status"], "url": f"/api/builds/{my_build['id']}"}
        # what to do next
        if mine and r["status"] == "draft":
            out["picture_url"] = f"/api/letters/{lid}/picture.png"
            out["next"] = (f"Look at the picture (GET {out['picture_url']}); its frame says {r['word']}. Describe what is "
                           f"visible in at most {C.LEVELS[r['level']].budget} words: count up to nine, halves, thirds and "
                           f"quarters, no digits. Check it with POST /api/words, then POST /api/letters/{lid}/send "
                           "{\"text\": \"...\"}. One text; it cannot be edited after sending.")
        elif mine and r["status"] == "open":
            out["next"] = (f"Your letter is open: {plural(sub, 'build')} so far, {act} in progress. It closes after "
                           f"{C.LETTER_MAX_BUILDS} builds or seven days, or when you POST /api/letters/{lid}/close. "
                           "Meanwhile you could build someone else's letter (GET /api/letters).")
        elif my_build and my_build["status"] == "building":
            out["next"] = f"You are building this letter: build {my_build['id']}. GET /api/builds/{my_build['id']}."
        elif viewer not in (None, "admin") and r["status"] == "open":
            why = self.may_build(viewer, r)
            out["next"] = (f"Build it: POST /api/letters/{lid}/builds. You'll get an empty board to place shapes on."
                           if not why else why)
        elif viewer is None and r["status"] == "open":
            out["next"] = "Make a callsign (POST /api/players {\"callsign\": \"...\"}) to build this letter."
        return out

    @staticmethod
    def _readings(row) -> dict:
        return {"in_place": row["overlap"], "slid_to_fit": row["slid"],
                "in_place_word": reading_word(row["overlap"]), "slid_to_fit_word": reading_word(row["slid"]),
                "slide": {"right": (row["slide_dx"] or 0) / 8, "up": (row["slide_dy"] or 0) / 8}}

    def _checks(self, b) -> list[dict]:
        return [{"check": c["n"], "in_place": c["in_place"], "slid_to_fit": c["slid"], "at": iso(c["created"]),
                 "in_place_word": reading_word(c["in_place"]), "slid_to_fit_word": reading_word(c["slid"]),
                 "board_url": f"/api/builds/{b['id']}/checks/{c['n']}.png"}
                for c in self.all("SELECT * FROM checks WHERE build_id=? ORDER BY n", b["id"])]

    def _result_card(self, b, picture_id) -> dict:
        shapes = D.loads(b["shapes"])
        pic = self.shapes_of(picture_id)
        return {
            "build": b["id"], "builder": self.callsign(b["builder_id"]), **self._readings(b),
            "loss": loss(pic, shapes), "checks": self._checks(b), "details": {"cells_match": b["score"]},
            "board_url": f"/api/builds/{b['id']}/board.png", "diff_url": f"/api/builds/{b['id']}/diff.png",
            "note": b["note"], "shapes": shapes, "submitted": iso(b["submitted"]),
        }

    def take_letter(self, me, lid) -> dict:
        self.sweep()
        r = self.letter(lid)
        existing = self.one("SELECT * FROM builds WHERE letter_id=? AND builder_id=? AND status='building'", lid, me["id"])
        if existing:
            return self.build_state(me, existing["id"])
        why = self.may_build(me, r)
        if why:
            raise GameError(409, why)
        with D.tx(self.db):
            bid = D.new_id(self.db)
            t = D.now()
            self.db.execute("INSERT INTO builds (id, letter_id, builder_id, status, created, updated) "
                            "VALUES (?, ?, ?, 'building', ?, ?)", (bid, lid, me["id"], t, t))
        return self.build_state(me, bid)

    # ------------------------------------------------------------ builds (both modes)

    def resolve_build(self, me, bid):
        """A build id, or a match id meaning the current round's build in that match."""
        b = self.one("SELECT * FROM builds WHERE id=?", bid)
        if b:
            return b
        m = self.one("SELECT * FROM matches WHERE id=?", bid)
        if m:
            rnd = self._current_round(m)
            if not rnd:
                raise GameError(409, "This match has no round being played.")
            if me is None or me == "admin" or rnd["builder_id"] != me["id"]:
                who = self.callsign(rnd["builder_id"])
                raise GameError(403, f"You are not the builder in this round; {who} is.")
            return self.one("SELECT * FROM builds WHERE id=?", rnd["build_id"])
        raise GameError(404, f'There is no build or match "{bid}".')

    def _build_context(self, b):
        if b["letter_id"]:
            return self.letter(b["letter_id"]), None
        rnd = self.one("SELECT * FROM rounds WHERE id=?", b["round_id"])
        return None, rnd

    def can_see_build(self, viewer, b) -> bool:
        if self.is_admin(viewer):
            return True
        letter, rnd = self._build_context(b)
        if viewer not in (None, "admin") and b["builder_id"] == viewer["id"]:
            return True
        if b["status"] != "submitted":
            return False
        if letter:
            return self.can_see_letter_picture(viewer, letter)
        return rnd["status"] == "finished" and not rnd["hidden"] or (
            viewer not in (None, "admin") and viewer["id"] in (rnd["describer_id"], rnd["builder_id"]))

    def can_see_build_picture(self, viewer, b) -> bool:
        letter, rnd = self._build_context(b)
        if letter:
            return self.can_see_letter_picture(viewer, letter)
        return self.can_see_round_picture(viewer, rnd)

    def _mine(self, me, b):
        if me is None or me == "admin" or b["builder_id"] != me["id"]:
            raise GameError(403, "Only its builder can change a build.")
        if b["status"] != "building":
            msg = {"submitted": "This build was already submitted.",
                   "cancelled": "This build was cancelled: its letter was closed by the describer before you submitted.",
                   "expired": "This build expired after a day without activity, and its letter's slot went to someone else."}
            raise GameError(409, msg.get(b["status"], "This build can no longer change."))

    def build_state(self, me, bid) -> dict:
        b = self.resolve_build(me, bid)
        if not self.can_see_build(me, b):
            raise GameError(403, "This build is only visible to its builder until its result is public.")
        letter, rnd = self._build_context(b)
        shapes = D.loads(b["shapes"])
        level = letter["level"] if letter else rnd["level"]
        out = {
            "build": b["id"], "mode": "letter" if letter else "live", "status": b["status"], **level_info(level),
            "word": letter["word"] if letter else rnd["word"],
            "shapes": shapes, "shape_lines": [f"{i + 1}. {describe(s)}" for i, s in enumerate(shapes)],
            "count": len(shapes), "max_shapes": C.MAX_BUILD_SHAPES,
            "board": "empty: nothing has been placed yet" if not shapes else plural(len(shapes), "shape") + " placed",
            "board_url": f"/api/builds/{b['id']}/board.png" + ("?grid=1" if level <= 3 else ""),
            "builder": self.callsign(b["builder_id"]),
        }
        if letter:
            out.update(letter=letter["id"], text=letter["text"], words=letter["words"], describer=self.callsign(letter["describer_id"]),
                       letter_url=f"/letter/{letter['id']}", checks=self._checks(b))
            out["checks_left"] = C.MAX_CHECKS - len(out["checks"]) if b["status"] == "building" else 0
        else:
            out.update(match=rnd["match_id"], round=rnd["n"], round_id=rnd["id"], describer=self.callsign(rnd["describer_id"]),
                       budget=C.live_budget(level))
        if b["status"] == "building":
            out["waiting_on"] = self.callsign(b["builder_id"]) if letter else self._round_waiting_on(rnd)
            where = "the letter" if letter else "the chat (GET /api/matches/" + rnd["match_id"] + ")"
            checks = ""
            if letter and out["checks_left"]:
                checks = (f" You have {plural(out['checks_left'], 'check')} left: POST /api/builds/{b['id']}/check gives "
                          "the two readings for the board as it stands, without showing the picture.")
            out["next"] = (
                f"Read {where} and place shapes: POST /api/builds/{b['id']}/place with e.g. "
                '{"shape": "rect", "color": "red", "x": 2, "y": 1, "w": 3, "h": 2}. x runs from the left edge, y from '
                f"the bottom, the board is 10 by 10. Look at your board (GET {out['board_url']}), fix with undo or PUT "
                f"/shapes, then POST /api/builds/{b['id']}/submit (optionally {{\"note\": \"what did not fit\"}})."
            ) + checks if not shapes else (
                f"{plural(len(shapes), 'shape')} placed. Compare your board (GET {out['board_url']}) with the words; "
                f"place, undo or replace shapes, then POST /api/builds/{b['id']}/submit when it matches"
                + (" (or ask the describer a question first: POST /api/matches/" + rnd["match_id"] + "/say)." if rnd else ".")
            ) + checks
        else:
            out["waiting_on"] = None
        if b["status"] == "submitted":
            out["result"] = self._result(b)
        return out

    def _result(self, b) -> dict:
        letter, rnd = self._build_context(b)
        pic_id = letter["picture_id"] if letter else rnd["picture_id"]
        pic, shapes = self.shapes_of(pic_id), D.loads(b["shapes"])
        lost = loss(pic, shapes)
        res = {
            **self._readings(b),
            "readings_explained": READINGS_EXPLAINED,
            "details": {"cells_match": b["score"], "cells_differ": lost["cells_differ"] if lost else 0},
            "loss": lost,
            "picture_url": f"/api/letters/{letter['id']}/picture.png" if letter else f"/api/rounds/{rnd['id']}/picture.png",
            "board_url": f"/api/builds/{b['id']}/board.png", "diff_url": f"/api/builds/{b['id']}/diff.png",
            "picture_shapes": pic, "build_shapes": shapes, "note": b["note"],
            "page_url": f"/letter/{letter['id']}" if letter else f"/round/{rnd['id']}",
        }
        if letter:
            res["checks"] = self._checks(b)
            res["others"] = self.one("SELECT COUNT(*) AS n FROM builds WHERE letter_id=? AND status='submitted' AND id!=?",
                                     letter["id"], b["id"])["n"]
        res["picture_lines"] = [f"{i + 1}. {describe(s)}" for i, s in enumerate(pic)]
        return res

    def _set_shapes(self, b, shapes):
        if len(shapes) > C.MAX_BUILD_SHAPES:
            raise GameError(422, f"A build holds at most {C.MAX_BUILD_SHAPES} shapes. Undo or replace some first.")
        self.db.execute("UPDATE builds SET shapes=?, updated=? WHERE id=?", (D.dumps(shapes), D.now(), b["id"]))

    def place(self, me, bid, raw) -> dict:
        """One shape, or a list of shapes placed in order on top of what is there."""
        b = self.resolve_build(me, bid)
        self._mine(me, b)
        if isinstance(raw, dict) and isinstance(raw.get("shapes"), list):
            raw = raw["shapes"]
        many = raw if isinstance(raw, list) else [raw]
        if not many:
            raise GameError(422, "Nothing to place: send one shape, or a list of shapes.")
        before = D.loads(b["shapes"])
        new, notes = [], []
        for i, r in enumerate(many):
            try:
                s, n = normalise(r)
            except ShapeError as e:
                raise GameError(422, (f"Shape {i + 1}: {e}" if len(many) > 1 else str(e)) + " Nothing was placed.")
            new.append(s)
            notes += [f"shape {len(before) + i + 1}: {x}" if len(many) > 1 else x for x in n]
        shapes = before + new
        with D.tx(self.db):
            self._set_shapes(b, shapes)
        out = self.build_state(me, b["id"])
        lines = [f"{len(before) + i + 1}. {describe(s)}" for i, s in enumerate(new)]
        out["placed"] = lines[0] if len(lines) == 1 else lines
        if notes:
            out["notes"] = notes
        return out

    def undo(self, me, bid) -> dict:
        b = self.resolve_build(me, bid)
        self._mine(me, b)
        shapes = D.loads(b["shapes"])
        if not shapes:
            raise GameError(409, "Nothing to undo: the board is empty.")
        removed = shapes.pop()
        with D.tx(self.db):
            self._set_shapes(b, shapes)
        out = self.build_state(me, b["id"])
        out["removed"] = describe(removed)
        return out

    def clear(self, me, bid) -> dict:
        b = self.resolve_build(me, bid)
        self._mine(me, b)
        with D.tx(self.db):
            self._set_shapes(b, [])
        return self.build_state(me, b["id"])

    def put_shapes(self, me, bid, raw_list) -> dict:
        b = self.resolve_build(me, bid)
        self._mine(me, b)
        if isinstance(raw_list, dict) and "shapes" in raw_list:
            raw_list = raw_list["shapes"]
        if not isinstance(raw_list, list):
            raise GameError(422, "PUT /shapes takes a JSON list of shapes (drawing order, later ones on top).")
        shapes, notes = [], []
        for i, raw in enumerate(raw_list):
            try:
                s, n = normalise(raw)
            except ShapeError as e:
                raise GameError(422, f"Shape {i + 1}: {e}")
            shapes.append(s)
            notes += [f"shape {i + 1}: {x}" for x in n]
        with D.tx(self.db):
            self._set_shapes(b, shapes)
        out = self.build_state(me, b["id"])
        if notes:
            out["notes"] = notes
        return out

    def submit(self, me, bid, note=None) -> dict:
        b = self.resolve_build(me, bid)
        self._mine(me, b)
        note = (note or "").strip() or None
        note_words = None
        if note:
            note_words, _ = count_words(note)
            if note_words > C.NOTE_WORDS:
                raise GameError(422, f"The note is {note_words} words; it may be at most {C.NOTE_WORDS}. Nothing was submitted.")
            if len(note) > C.MAX_MESSAGE_CHARS:
                raise GameError(422, "The note is too long. Nothing was submitted.")
        letter, rnd = self._build_context(b)
        pic_id = letter["picture_id"] if letter else rnd["picture_id"]
        shapes = D.loads(b["shapes"])
        res = readings(self.shapes_of(pic_id), shapes)
        with D.tx(self.db):
            t = D.now()
            self.db.execute("UPDATE builds SET status='submitted', note=?, note_words=?, score=?, overlap=?, slid=?, "
                            "slide_dx=?, slide_dy=?, submitted=?, updated=? WHERE id=?",
                            (note, note_words, res["cells_match"], res["in_place"], res["slid_to_fit"],
                             round(res["slide"]["right"] * 8), round(res["slide"]["up"] * 8), t, t, b["id"]))
            self.mark_seen(me["id"], pic_id)
            if letter:
                self.event("letter_built", {"letter": letter["id"], "build": b["id"], "builder": me["callsign"],
                                            "describer": self.callsign(letter["describer_id"]), "url": f"/letter/{letter['id']}"},
                           public=True)
                sub, _ = self._letter_counts(letter["id"])
                if sub >= C.LETTER_MAX_BUILDS:
                    self._close(letter["id"], f"{C.LETTER_MAX_BUILDS} builds")
            else:
                self._finish_round(rnd, res)
        out = self.build_state(me, b["id"])
        r = out["result"]
        said_ = f"{said(r['in_place'])} in place; {said(r['slid_to_fit'])} slid to fit."
        said_ = said_[0].upper() + said_[1:]
        if letter:
            others = ("You are its first builder." if not r["others"] else
                      f"{plural(r['others'], 'other player')} built this letter too.")
            out["next"] = (f"{said_} {others} See the picture beside every board at {r['page_url']}. Then build another "
                           "letter (GET /api/letters) or describe a picture (POST /api/letters {\"level\": N}).")
        else:
            m = self.one("SELECT * FROM matches WHERE id=?", rnd["match_id"])
            nxt = self._current_round(m)
            if m["status"] == "finished" or not nxt:
                then = "That was the last round."
            else:
                change = ("one level harder" if nxt["level"] > rnd["level"] else
                          "one level easier" if nxt["level"] < rnd["level"] else "at the same level")
                then = (f"Round {nxt['n']} has started {change}, with roles swapped: GET /api/matches/{m['id']}.")
            out["next"] = f"{said_} {then}"
        return out

    def check(self, me, bid) -> dict:
        """A letter's builder may ask twice for the two readings of the board as it stands, before the final submit."""
        b = self.resolve_build(me, bid)
        self._mine(me, b)
        letter, rnd = self._build_context(b)
        if not letter:
            used = self.one("SELECT COALESCE(SUM(words), 0) AS n FROM messages WHERE round_id=? AND role='describer'",
                            rnd["id"])["n"]
            if used >= C.live_budget(rnd["level"]):
                raise GameError(409, "Checks are for letters; in a live round the conversation is the feedback. The "
                                     "describer has no words left this round, so submit when you are ready.")
            raise GameError(409, "Checks are for letters; in a live round the conversation is the feedback. Ask the "
                                 f"describer: POST /api/matches/{rnd['match_id']}/say.")
        shapes = D.loads(b["shapes"])
        if not shapes:
            raise GameError(409, "The board is empty; place something before checking.")
        done = self.one("SELECT COUNT(*) AS n FROM checks WHERE build_id=?", b["id"])["n"]
        if done >= C.MAX_CHECKS:
            raise GameError(409, f"You have used both checks. Submit when you are ready: POST /api/builds/{b['id']}/submit.")
        res = readings(self.shapes_of(letter["picture_id"]), shapes)
        with D.tx(self.db):
            self.db.execute("INSERT INTO checks (build_id, n, shapes, in_place, slid, slide_dx, slide_dy, created) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (b["id"], done + 1, D.dumps(shapes), res["in_place"], res["slid_to_fit"],
                             round(res["slide"]["right"] * 8), round(res["slide"]["up"] * 8), D.now()))
            self.db.execute("UPDATE builds SET updated=? WHERE id=?", (D.now(), b["id"]))
        left = C.MAX_CHECKS - done - 1
        return {
            "build": b["id"], "check": done + 1, "checks_left": left,
            "in_place": res["in_place"], "slid_to_fit": res["slid_to_fit"], "readings_explained": READINGS_EXPLAINED,
            "in_place_word": reading_word(res["in_place"]), "slid_to_fit_word": reading_word(res["slid_to_fit"]),
            "board_url": f"/api/builds/{b['id']}/checks/{done + 1}.png", "waiting_on": me["callsign"],
            "next": (f"Check {done + 1}: {said(res['in_place'])} in place, {said(res['slid_to_fit'])} slid to fit. "
                     + ("A high slid-to-fit with a low in-place means the right things in the wrong place. "
                        if res["slid_to_fit"] - res["in_place"] >= 20 else "")
                     + (f"{plural(left, 'check')} left. " if left else "No checks left. ")
                     + f"Change the board if you like, then POST /api/builds/{b['id']}/submit."),
        }

    # ------------------------------------------------------------ live matches

    def match(self, mid):
        m = self.one("SELECT * FROM matches WHERE id=?", mid)
        if not m:
            raise GameError(404, f'There is no match "{mid}".')
        return m

    def _current_round(self, m):
        return self.one("SELECT * FROM rounds WHERE match_id=? AND status='playing' ORDER BY n DESC LIMIT 1", m["id"])

    def create_match(self, me, open_: bool = False, rounds=None, level=None) -> dict:
        try:
            rounds = int(rounds) if rounds not in (None, "") else C.DEFAULT_ROUNDS
            level = int(level) if level not in (None, "") else 1
        except (TypeError, ValueError):
            raise GameError(400, "rounds and level are whole numbers.")
        if not 1 <= rounds <= C.MAX_ROUNDS:
            raise GameError(400, f"rounds is from 1 to {C.MAX_ROUNDS}.")
        if level not in C.LEVELS:
            raise GameError(400, "level is from 1 to 8.")
        with D.tx(self.db):
            mid = D.new_id(self.db)
            t = D.now()
            self.db.execute("INSERT INTO matches (id, creator_id, open, rounds, start_level, status, created, updated) "
                            "VALUES (?, ?, ?, ?, ?, 'waiting', ?, ?)", (mid, me["id"], int(bool(open_)), rounds, level, t, t))
            self.event("match_created", {"match": mid}, public=False, match_id=mid)
            if open_:
                self.event("seat_open", {"match": mid, "creator": me["callsign"], "level": level, "rounds": rounds,
                                         "url": f"/m/{mid}"}, public=True)
        out = self.match_state(me, mid)
        out["invite_url"] = f"/m/{mid}"
        return out

    def join_match(self, me, mid) -> dict:
        m = self.match(mid)
        if m["creator_id"] == me["id"] or m["guest_id"] == me["id"]:
            if m["status"] == "waiting":
                raise GameError(409, "This is your own match; it needs someone else to take the seat. Share the invite link.")
            return self.match_state(me, mid)
        if m["status"] != "waiting":
            raise GameError(409, "This match's seat is already taken.")
        with D.tx(self.db):
            self.db.execute("UPDATE matches SET guest_id=?, status='playing', updated=? WHERE id=?", (me["id"], D.now(), mid))
            self.event("joined", {"player": me["callsign"]}, public=False, match_id=mid)
            # the one who just arrived is present, so they describe first
            self._start_round(self.match(mid), 1, m["start_level"], describer=me["id"], builder=m["creator_id"])
        return self.match_state(me, mid)

    def seat(self, me, level=None, rounds=None) -> dict:
        self.sweep()
        rows = self.all("SELECT * FROM matches WHERE status='waiting' AND open=1 AND creator_id!=? AND hidden=0 "
                        "ORDER BY created", me["id"])
        if rows:
            out = self.join_match(me, rows[0]["id"])
            out["seated"] = "You took the seat at the oldest open match."
            return out
        mine = self.one("SELECT * FROM matches WHERE status='waiting' AND open=1 AND creator_id=?", me["id"])
        if mine:
            out = self.match_state(me, mine["id"])
            out["seated"] = "You already have an open match waiting for someone; this is it."
            return out
        out = self.create_match(me, True, rounds, level)
        out["seated"] = "No open match was waiting, so one was created for you; it is listed in the hall."
        return out

    def _start_round(self, m, n, level, describer, builder):
        pic = self.new_picture(level)
        prev = self.one("SELECT word FROM rounds WHERE match_id=? ORDER BY n DESC LIMIT 1", m["id"])
        rid, bid = D.new_id(self.db), None
        bid = D.new_id(self.db)
        while bid == rid:
            bid = D.new_id(self.db)
        t = D.now()
        word = D.choose_word({prev["word"]} if prev else set())
        self.db.execute("INSERT INTO builds (id, round_id, builder_id, status, created, updated) VALUES (?, ?, ?, 'building', ?, ?)",
                        (bid, rid, builder, t, t))
        self.db.execute("INSERT INTO rounds (id, match_id, n, level, picture_id, word, describer_id, builder_id, build_id, "
                        "status, started) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'playing', ?)",
                        (rid, m["id"], n, level, pic["id"], word, describer, builder, bid, t))
        self.mark_seen(describer, pic["id"])
        self.db.execute("UPDATE matches SET updated=? WHERE id=?", (t, m["id"]))
        self.event("round_started", {"round": n, "level": level, "word": word, "describer": self.callsign(describer),
                                     "builder": self.callsign(builder)}, public=False, match_id=m["id"])

    def _finish_round(self, rnd, res):
        t = D.now()
        self.db.execute("UPDATE rounds SET status='finished', finished=? WHERE id=?", (t, rnd["id"]))
        self.mark_seen(rnd["builder_id"], rnd["picture_id"])
        m = self.match(rnd["match_id"])
        self.event("round_finished", {"round": rnd["n"], "round_id": rnd["id"], "in_place": res["in_place"],
                                      "in_place_word": reading_word(res["in_place"]),
                                      "slid_to_fit_word": reading_word(res["slid_to_fit"]),
                                      "slid_to_fit": res["slid_to_fit"], "url": f"/round/{rnd['id']}"},
                   public=False, match_id=m["id"])
        self.event("round_finished", {"round": rnd["id"], "match": m["id"], "level": rnd["level"],
                                      "in_place": res["in_place"], "slid_to_fit": res["slid_to_fit"],
                                      "describer": self.callsign(rnd["describer_id"]), "builder": self.callsign(rnd["builder_id"]),
                                      "url": f"/round/{rnd['id']}"}, public=True)
        if rnd["n"] >= m["rounds"]:
            self.db.execute("UPDATE matches SET status='finished', finished=?, updated=? WHERE id=?", (t, t, m["id"]))
            self.event("match_finished", {"match": m["id"]}, public=False, match_id=m["id"])
            return
        level = rnd["level"]
        if res["in_place"] >= C.LEVEL_UP_AT:
            level = min(8, level + 1)
        elif res["in_place"] < C.LEVEL_DOWN_BELOW:
            level = max(1, level - 1)
        self._start_round(m, rnd["n"] + 1, level, describer=rnd["builder_id"], builder=rnd["describer_id"])

    def _round_messages(self, rid):
        return self.all("SELECT * FROM messages WHERE round_id=? ORDER BY id", rid)

    def _round_waiting_on(self, rnd) -> str | None:
        if rnd is None or rnd["status"] != "playing":
            return None
        b = self.one("SELECT * FROM builds WHERE id=?", rnd["build_id"])
        msgs = self._round_messages(rnd["id"])
        last = max([b["updated"]] + [m["created"] for m in msgs])
        if D.loads(b["shapes"]) and last < D.now() - C.STALE_BOARD_HOURS * 3600:
            return self.callsign(rnd["builder_id"])
        if not msgs or msgs[-1]["role"] == "builder":
            return self.callsign(rnd["describer_id"])
        return self.callsign(rnd["builder_id"])

    def say(self, me, mid, text) -> dict:
        m = self.match(mid)
        rnd = self._current_round(m)
        if not rnd:
            raise GameError(409, "No round is being played in this match, so there is nobody to talk to.")
        if me["id"] not in (rnd["describer_id"], rnd["builder_id"]):
            raise GameError(403, "Only the two players can talk in a match.")
        role = "describer" if me["id"] == rnd["describer_id"] else "builder"
        budget_left = None
        if role == "describer":
            used = self.one("SELECT COALESCE(SUM(words), 0) AS n FROM messages WHERE round_id=? AND role='describer'", rnd["id"])["n"]
            budget_left = C.live_budget(rnd["level"]) - used
            if budget_left <= 0:
                raise GameError(422, "Not sent: you have used this round's whole word budget. The builder has to "
                                     "work with what you said and submit.")
        names = (self.callsign(m["creator_id"]), self.callsign(m["guest_id"]))
        try:
            n = check_message(text, budget_left=budget_left, exempt=names, unit="round")
        except Refused as e:
            raise GameError(422, str(e))
        with D.tx(self.db):
            t = D.now()
            cur = self.db.execute("INSERT INTO messages (round_id, player_id, role, text, words, created) VALUES (?, ?, ?, ?, ?, ?)",
                                  (rnd["id"], me["id"], role, text.strip(), n, t))
            self.db.execute("UPDATE matches SET updated=? WHERE id=?", (t, mid))
            self.event("said", {"round": rnd["n"], "from": me["callsign"], "role": role, "text": text.strip(), "words": n,
                                "message": cur.lastrowid}, public=False, match_id=mid)
        return self.match_state(me, mid)

    def can_see_round_picture(self, viewer, rnd) -> bool:
        if self.is_admin(viewer):
            return True
        if viewer not in (None, "admin") and viewer["id"] == rnd["describer_id"]:
            return True
        if rnd["status"] == "finished":
            if viewer not in (None, "admin") and viewer["id"] == rnd["builder_id"]:
                return True
            return not rnd["hidden"]
        return False

    def round_view(self, viewer, rid) -> dict:
        rnd = self.one("SELECT * FROM rounds WHERE id=?", rid)
        if not rnd:
            raise GameError(404, f'There is no round "{rid}".')
        players = (rnd["describer_id"], rnd["builder_id"])
        is_player = viewer not in (None, "admin") and viewer["id"] in players
        if rnd["status"] != "finished" and not (is_player or self.is_admin(viewer)):
            raise GameError(403, "This round is still being played; its picture and chat are private until it is submitted.")
        if rnd["hidden"] and not (is_player or self.is_admin(viewer)):
            raise GameError(404, f'There is no round "{rid}".')
        b = self.one("SELECT * FROM builds WHERE id=?", rnd["build_id"])
        msgs = self._round_messages(rid)
        out = {
            "round": rid, "match": rnd["match_id"], "n": rnd["n"], **level_info(rnd["level"]),
            "budget": C.live_budget(rnd["level"]), "status": rnd["status"],
            "word": rnd["word"], "describer": self.callsign(rnd["describer_id"]), "builder": self.callsign(rnd["builder_id"]),
            "chat": [self._msg(x) for x in msgs],
            "describer_words": sum(x["words"] for x in msgs if x["role"] == "describer"),
            "builder_words": sum(x["words"] for x in msgs if x["role"] == "builder"),
            "url": f"/round/{rid}", "match_url": f"/m/{rnd['match_id']}",
            "started": iso(rnd["started"]), "finished": iso(rnd["finished"]),
        }
        if rnd["status"] == "finished":
            out["result"] = self._result(b)
        return out

    def _msg(self, x) -> dict:
        return {"from": self.callsign(x["player_id"]), "role": x["role"], "text": x["text"], "words": x["words"],
                "at": iso(x["created"]), "id": x["id"]}

    def match_state(self, viewer, mid, since: int | None = None) -> dict:
        self.sweep()
        m = self.match(mid)
        me_id = viewer["id"] if viewer not in (None, "admin") else None
        is_player = me_id is not None and me_id in (m["creator_id"], m["guest_id"])
        if m["hidden"] and not (is_player or self.is_admin(viewer)):
            raise GameError(404, f'There is no match "{mid}".')
        rnd = self._current_round(m)
        creator, guest = self.callsign(m["creator_id"]), self.callsign(m["guest_id"])
        rounds_done = self.all("SELECT * FROM rounds WHERE match_id=? AND status='finished' ORDER BY n", mid)
        out = {
            "match": mid, "status": m["status"], "rounds": m["rounds"], "open": bool(m["open"]),
            "players": [p for p in (creator, guest) if p], "created_by": creator, "url": f"/m/{mid}",
            "round": rnd["n"] if rnd else (rounds_done[-1]["n"] if rounds_done else 0),
            "finished_rounds": [{
                "round": r["id"], "n": r["n"], **level_info(r["level"]), "word": r["word"],
                "describer": self.callsign(r["describer_id"]), "builder": self.callsign(r["builder_id"]),
                **self._readings(self.one("SELECT * FROM builds WHERE id=?", r["build_id"])), "url": f"/round/{r['id']}",
                "build": r["build_id"],
            } for r in rounds_done if not r["hidden"] or is_player],
        }
        role = None
        if is_player and rnd:
            role = "describer" if me_id == rnd["describer_id"] else "builder"
        out["you"] = {"callsign": viewer["callsign"] if me_id else None,
                      "role": role or ("player" if is_player else "watching")}
        waiting_on = self._round_waiting_on(rnd) if rnd else None
        out["waiting_on"] = waiting_on
        if rnd:
            b = self.one("SELECT * FROM builds WHERE id=?", rnd["build_id"])
            used = self.one("SELECT COALESCE(SUM(words), 0) AS n FROM messages WHERE round_id=? AND role='describer'", rnd["id"])["n"]
            cur = {
                "round_id": rnd["id"], "n": rnd["n"], **level_info(rnd["level"]),
                "describer": self.callsign(rnd["describer_id"]), "builder": self.callsign(rnd["builder_id"]),
                "budget": C.live_budget(rnd["level"]),
                "describer_words_used": used, "describer_words_left": C.live_budget(rnd["level"]) - used,
                "shapes_on_board": len(D.loads(b["shapes"])) if (role == "builder") else None,
            }
            if is_player:
                cur["word"] = rnd["word"]
                cur["chat"] = [self._msg(x) for x in self._round_messages(rnd["id"])]
                if role == "describer":
                    cur["picture_url"] = f"/api/matches/{mid}/picture.png"
                else:
                    cur["build"] = b["id"]
                    cur["board_url"] = f"/api/builds/{b['id']}/board.png" + ("?grid=1" if rnd["level"] <= 3 else "")
                    cur["shapes"] = D.loads(b["shapes"])
            out["current"] = cur
        # events since
        if is_player or self.is_admin(viewer):
            q = "SELECT * FROM events WHERE match_id=?"
            args = [mid]
            if since is not None:
                q += " AND id>?"
                args.append(int(since))
            evs = self.all(q + " ORDER BY id", *args)
            out["events"] = [{"id": e["id"], "kind": e["kind"], **D.loads(e["data"]), "at": iso(e["created"])} for e in evs]
        last = self.one("SELECT MAX(id) AS n FROM events WHERE match_id=?", mid)["n"] or 0
        out["last_event"] = last
        out["next"] = self._match_next(m, rnd, role, is_player, waiting_on, viewer)
        out["waiting_sentence"] = self._waiting_sentence(m, rnd, waiting_on)
        if waiting_on and me_id and waiting_on == viewer["callsign"]:
            out["waiting_sentence"] = self._your_move(rnd, role)
        return out

    def _your_move(self, rnd, role) -> str:
        msgs = self._round_messages(rnd["id"])
        other = self.callsign(rnd["builder_id"] if role == "describer" else rnd["describer_id"])
        if role == "describer":
            if not msgs:
                return f"Your move: describe the picture to {other}."
            return f"Your move: {other} asked something; answer it."
        board = self.one("SELECT * FROM builds WHERE id=?", rnd["build_id"])
        if D.loads(board["shapes"]) and max([board["updated"]] + [x["created"] for x in msgs]) < D.now() - C.STALE_BOARD_HOURS * 3600:
            return "Your move: nothing has moved for a day; submit your board when you're ready."
        return f"Your move: build from {other}'s words, ask a question, or submit."

    def _waiting_sentence(self, m, rnd, waiting_on) -> str:
        if m["status"] == "waiting":
            return ("Waiting for someone to take the open seat." if m["open"]
                    else "Waiting for the invited player to take the seat.")
        if m["status"] == "finished":
            return "The match is over."
        if m["status"] == "abandoned":
            return "This match was abandoned after seven days without a move."
        if not rnd:
            return ""
        d, b = self.callsign(rnd["describer_id"]), self.callsign(rnd["builder_id"])
        msgs = self._round_messages(rnd["id"])
        if waiting_on == b:
            board = self.one("SELECT * FROM builds WHERE id=?", rnd["build_id"])
            stale = D.loads(board["shapes"]) and max([board["updated"]] + [x["created"] for x in msgs]) < D.now() - C.STALE_BOARD_HOURS * 3600
            if stale:
                return f"Waiting on {b}, the builder, to submit the board (nothing has moved for a day)."
            return f"Waiting on {b}, the builder: build from {d}'s words, ask a question, or submit."
        if not msgs:
            return f"Waiting on {d}, the describer, to describe the picture."
        return f"Waiting on {d}, the describer, to answer {b}."

    def _match_next(self, m, rnd, role, is_player, waiting_on, viewer) -> str:
        mid = m["id"]
        if m["status"] == "waiting":
            if is_player:
                return (f"Waiting for someone to take the seat. Give them the link /m/{mid} (or they POST /api/matches/{mid}/join)."
                        f" Then GET /api/matches/{mid}?wait=60 to wait for them.")
            if viewer not in (None, "admin"):
                return f"Take the seat: POST /api/matches/{mid}/join."
            return "Make a callsign (POST /api/players), then POST /api/matches/" + mid + "/join to take the seat."
        if m["status"] in ("finished", "abandoned"):
            return f"The match is over; every round is at /m/{mid}. Start another: POST /api/seat or POST /api/matches."
        if not is_player:
            return f"Round {rnd['n'] if rnd else '?'} is being played; its picture and chat are shown once it is submitted."
        words_left = C.live_budget(rnd["level"]) - self.one(
            "SELECT COALESCE(SUM(words), 0) AS n FROM messages WHERE round_id=? AND role='describer'", rnd["id"])["n"]
        wait = f" When you have nothing to add, GET /api/matches/{mid}?since=<last_event>&wait=60 waits for the next move."
        msgs = self._round_messages(rnd["id"])
        d_name, b_name = self.callsign(rnd["describer_id"]), self.callsign(rnd["builder_id"])
        if role == "describer":
            if waiting_on == d_name and msgs and msgs[-1]["role"] == "builder":
                if words_left <= 0:
                    return (f"{b_name} asked: \"{msgs[-1]['text']}\" You have no words left this round, so they must "
                            "work with what you said." + wait)
                return (f"{b_name} asked: \"{msgs[-1]['text']}\" Answer it: POST /api/matches/{mid}/say "
                        f"{{\"text\": \"...\"}} ({words_left} words left this round)." + wait)
            if waiting_on == d_name:
                keep = max(1, round(C.live_budget(rnd["level"]) / 4))
                return (f"You are the describer. Look at the picture (GET /api/matches/{mid}/picture.png; its frame says "
                        f"{rnd['word']}) and describe it: POST /api/matches/{mid}/say {{\"text\": \"...\"}}. You have "
                        f"{words_left} words for the whole round, answers to {b_name}'s questions included: keep about "
                        f"{keep} back. Count to nine, cut in halves, thirds and quarters, no digits." + wait)
            return (f"You are the describer. {b_name} has your words; answer their questions when they ask "
                    f"({words_left} words left this round)." + wait)
        if waiting_on == b_name:
            ask = (f", ask questions (POST /api/matches/{mid}/say)" if words_left > 0 else
                   f" ({d_name} has no words left this round, so questions can't be answered)")
            return (f"You are the builder. Read the chat, place shapes (POST /api/builds/{mid}/place), look at your board "
                    f"(GET /api/builds/{mid}/board.png){ask}, then POST /api/builds/{mid}/submit." + wait)
        if not any(x["role"] == "describer" for x in msgs):
            return (f"You are the builder. {d_name} hasn't described the picture yet; wait for their words."
                    + wait + f" You can place shapes meanwhile: POST /api/builds/{mid}/place.")
        return (f"You are the builder. You asked {d_name} a question; wait for the answer."
                + wait + f" You can keep building meanwhile: POST /api/builds/{mid}/place.")

    def matches_waiting(self, exclude_id=None) -> list[dict]:
        rows = self.all("SELECT * FROM matches WHERE status='waiting' AND open=1 AND hidden=0 ORDER BY created")
        return [{"match": r["id"], "creator": self.callsign(r["creator_id"]), "rounds": r["rounds"],
                 **level_info(r["start_level"]), "budget": C.live_budget(r["start_level"]), "created": iso(r["created"]),
                 "url": f"/m/{r['id']}"}
                for r in rows if r["creator_id"] != exclude_id]

    # ------------------------------------------------------------ overview

    def me(self, me) -> dict:
        self.sweep()
        pid = me["id"]
        drafts = self.all("SELECT * FROM letters WHERE describer_id=? AND status='draft' ORDER BY created", pid)
        open_ = self.all("SELECT * FROM letters WHERE describer_id=? AND status='open' ORDER BY sent DESC", pid)
        builds = self.all("SELECT * FROM builds WHERE builder_id=? AND status='building' AND letter_id IS NOT NULL", pid)
        matches = self.all("SELECT * FROM matches WHERE (creator_id=? OR guest_id=?) AND status IN ('waiting', 'playing') "
                           "ORDER BY updated DESC", pid, pid)
        waiting = []
        for d in drafts:
            waiting.append(f"Draft letter {d['id']} (level {d['level']}, word {d['word']}): look at its picture and send "
                           f"its words: POST /api/letters/{d['id']}/send.")
        for b in builds:
            waiting.append(f"Build {b['id']} of letter {b['letter_id']} is in progress: GET /api/builds/{b['id']}.")
        ms = []
        for m in matches:
            st = self.match_state(me, m["id"])
            ms.append({"match": m["id"], "status": m["status"], "players": st["players"], "role": st["you"]["role"],
                       "round": st["round"], "waiting_on": st["waiting_on"], "url": f"/m/{m['id']}"})
            if st["waiting_on"] == me["callsign"]:
                waiting.append(f"Match {m['id']}: {st['waiting_sentence']} GET /api/matches/{m['id']}.")
        out = {
            "callsign": me["callsign"], "kind": me["kind"], "about": me["about"], "profile_url": f"/p/{me['callsign']}",
            "drafts": [{"letter": d["id"], **level_info(d["level"]), "word": d["word"],
                        "picture_url": f"/api/letters/{d['id']}/picture.png"} for d in drafts],
            "open_letters": [self._letter_card(r) for r in open_],
            "builds_in_progress": [{"build": b["id"], "letter": b["letter_id"], "url": f"/api/builds/{b['id']}"} for b in builds],
            "matches": ms,
            "waiting_on_you": waiting,
        }
        out["next"] = waiting[0] if waiting else (
            "Nothing is waiting on you. GET /api/hall to see what you can do: describe a picture, build a letter, "
            "or sit at a live match.")
        return out

    def hall(self, me) -> dict:
        self.sweep()
        letters = self.list_letters(me)["letters"]
        seats = self.matches_waiting(exclude_id=me["id"] if me not in (None, "admin") else None)
        by_level = {}
        for l in letters:
            by_level[l["level"]] = by_level.get(l["level"], 0) + 1
        out = {
            "levels": [{**level_info(n), "what": lv.blurb} for n, lv in C.LEVELS.items()],
            "open_letters_you_may_build": len(letters), "by_level": by_level, "letters": letters[:20],
            "open_seats": seats, "recent": self.recent(10),
        }
        if me in (None, "admin"):
            out["next"] = "Make a callsign: POST /api/players {\"callsign\": \"...\"}. The manual is at /llms.txt."
        else:
            opts = ["describe a picture (POST /api/letters {\"level\": 1})"]
            if letters:
                opts.append(f"build one of {plural(len(letters), 'open letter')} (POST /api/letters/<id>/builds)")
            if seats:
                opts.append(f"sit at an open live match, {len(seats)} waiting (POST /api/seat)")
            else:
                opts.append("start a live match (POST /api/seat, or POST /api/matches {\"open\": false} to invite someone)")
            out["next"] = "You can " + "; ".join(opts) + "."
        return out

    def recent(self, limit=12, level=None, mode=None, before: float | None = None) -> list[dict]:
        """Finished live rounds and closed letters, newest first, as wall items."""
        items = []
        if mode in (None, "letters"):
            sql = "SELECT * FROM letters WHERE status='closed' AND hidden=0"
            args = []
            if level:
                sql += " AND level=?"; args.append(level)
            if before:
                sql += " AND closed<?"; args.append(before)
            for r in self.all(sql + " ORDER BY closed DESC LIMIT ?", *args, limit):
                bs = self.all("SELECT * FROM builds WHERE letter_id=? AND status='submitted' ORDER BY overlap DESC", r["id"])
                items.append({
                    "kind": "letter", "id": r["id"], "t": r["closed"], "when": iso(r["closed"]), **level_info(r["level"]),
                    "describer": self.callsign(r["describer_id"]), "builders": [self.callsign(b["builder_id"]) for b in bs],
                    "readings": [self._readings(b) for b in bs], "words": r["words"], "text": r["text"],
                    "picture_url": f"/api/letters/{r['id']}/picture.png",
                    "board_url": f"/api/builds/{bs[0]['id']}/board.png" if bs else None, "url": f"/letter/{r['id']}",
                })
        if mode in (None, "live"):
            sql = ("SELECT r.*, b.overlap AS overlap, b.slid AS slid, b.slide_dx AS slide_dx, b.slide_dy AS slide_dy "
                   "FROM rounds r JOIN builds b ON b.id=r.build_id JOIN matches m ON m.id=r.match_id "
                   "WHERE r.status='finished' AND r.hidden=0 AND m.hidden=0")
            args = []
            if level:
                sql += " AND r.level=?"; args.append(level)
            if before:
                sql += " AND r.finished<?"; args.append(before)
            for r in self.all(sql + " ORDER BY r.finished DESC LIMIT ?", *args, limit):
                items.append({
                    "kind": "round", "id": r["id"], "t": r["finished"], "when": iso(r["finished"]), **level_info(r["level"]),
                    "describer": self.callsign(r["describer_id"]), "builders": [self.callsign(r["builder_id"])],
                    "readings": [self._readings(r)], "picture_url": f"/api/rounds/{r['id']}/picture.png",
                    "board_url": f"/api/builds/{r['build_id']}/board.png", "url": f"/round/{r['id']}", "match": r["match_id"],
                    "words": self.one("SELECT COALESCE(SUM(words),0) AS n FROM messages WHERE round_id=? AND role='describer'", r["id"])["n"],
                })
        items.sort(key=lambda x: -x["t"])
        return items[:limit]

    def profile(self, callsign) -> dict:
        p = self.player_by_callsign(callsign)
        if not p or p["hidden"]:
            raise GameError(404, f'There is no player "{callsign}".')
        pid = p["id"]
        letters = self.all("SELECT * FROM letters WHERE describer_id=? AND status IN ('open', 'closed') AND hidden=0 "
                           "ORDER BY sent DESC", pid)
        builds = self.all("SELECT b.*, l.status AS lstatus, l.level AS level, l.describer_id AS did FROM builds b "
                          "JOIN letters l ON l.id=b.letter_id WHERE b.builder_id=? AND b.status='submitted' AND l.hidden=0 "
                          "ORDER BY b.submitted DESC", pid)
        rounds = self.all("SELECT r.*, b.overlap AS overlap, b.slid AS slid, b.slide_dx AS slide_dx, b.slide_dy AS slide_dy "
                          "FROM rounds r JOIN builds b ON b.id=r.build_id "
                          "WHERE (r.describer_id=? OR r.builder_id=?) AND r.status='finished' AND r.hidden=0 "
                          "ORDER BY r.finished DESC", pid, pid)
        partners = {}

        def meet(other_id, how):
            if other_id and other_id != pid:
                name = self.callsign(other_id)
                partners.setdefault(name, set()).add(how)

        for b in builds:
            meet(b["did"], "built their letter")
        for l in letters:
            for b in self.all("SELECT builder_id FROM builds WHERE letter_id=? AND status='submitted'", l["id"]):
                meet(b["builder_id"], "built a letter of theirs")
        for r in rounds:
            meet(r["builder_id"] if r["describer_id"] == pid else r["describer_id"], "played live")
        return {
            "callsign": p["callsign"], "kind": p["kind"], "about": p["about"], "since": iso(p["created"]),
            "counts": {"letters": len(letters), "builds": len(builds), "live_rounds": len(rounds)},
            "letters": [{**self._letter_card(l), "status": l["status"]} for l in letters],
            "builds": [{"build": b["id"], "letter": b["letter_id"], **level_info(b["level"]),
                        "describer": self.callsign(b["did"]),
                        **(self._readings(b) if b["lstatus"] == "closed" else {"in_place": None, "slid_to_fit": None}),
                        "board_url": f"/api/builds/{b['id']}/board.png" if b["lstatus"] == "closed" else None,
                        "url": f"/letter/{b['letter_id']}"} for b in builds],
            "live_rounds": [{"round": r["id"], **level_info(r["level"]), "role": "describer" if r["describer_id"] == pid else "builder",
                             "with": self.callsign(r["builder_id"] if r["describer_id"] == pid else r["describer_id"]),
                             **self._readings(r), "url": f"/round/{r['id']}"} for r in rounds],
            "played_with": sorted(({"callsign": k, "how": sorted(v)} for k, v in partners.items()), key=lambda x: x["callsign"].lower()),
        }

    def events(self, since=0, limit=200) -> dict:
        rows = self.all("SELECT * FROM events WHERE public=1 AND id>? ORDER BY id LIMIT ?", int(since or 0), limit)
        evs = [{"id": e["id"], "kind": e["kind"], **D.loads(e["data"]), "at": iso(e["created"])} for e in rows]
        return {"events": evs, "last": evs[-1]["id"] if evs else int(since or 0)}

    # ------------------------------------------------------------ housekeeping

    def sweep(self, force=False):
        """Expire idle letter builds, close letters past their time, abandon idle matches. Cheap; runs lazily."""
        t = D.now()
        if not force and t - self._last_sweep < 20:
            return
        self._last_sweep = t
        with D.tx(self.db):
            self.db.execute("UPDATE builds SET status='expired' WHERE status='building' AND letter_id IS NOT NULL AND updated<?",
                            (t - C.BUILD_IDLE_HOURS * 3600,))
            old = self.all("SELECT id FROM letters WHERE status='open' AND sent<?", t - C.LETTER_OPEN_DAYS * 86400)
            for r in old:
                _, act = self._letter_counts(r["id"])
                if act == 0:
                    self._close(r["id"], "seven days passed")
            idle = self.all("SELECT id FROM matches WHERE status IN ('waiting', 'playing') AND updated<?", t - C.MATCH_IDLE_DAYS * 86400)
            for m in idle:
                self.db.execute("UPDATE matches SET status='abandoned', updated=? WHERE id=?", (t, m["id"]))
                self.db.execute("UPDATE rounds SET status='abandoned' WHERE match_id=? AND status='playing'", (m["id"],))
                self.event("match_abandoned", {"match": m["id"]}, public=False, match_id=m["id"])

    def hide(self, kind, oid, hidden=True) -> dict:
        table = {"letter": "letters", "round": "rounds", "match": "matches", "player": "players"}.get(kind)
        if not table:
            raise GameError(400, 'kind is "letter", "round", "match" or "player".')
        col = "callsign_lc" if kind == "player" else "id"
        val = oid.lower() if kind == "player" else oid
        with D.tx(self.db):
            n = self.db.execute(f"UPDATE {table} SET hidden=? WHERE {col}=?", (int(bool(hidden)), val)).rowcount
        if not n:
            raise GameError(404, f"No {kind} {oid}.")
        return {"kind": kind, "id": oid, "hidden": bool(hidden)}
