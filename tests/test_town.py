"""Post play: the town daemon against a fake Delve Town and a real hall."""
import time

import httpx
import pytest

from tworooms.town.clients import HallClient, TownError
from tworooms.town.daemon import SIGN, Config, Daemon
from tworooms.town.parse import parse_reply

from .conftest import Client, serve

HALL_DID = "did:plc:hall"


class FakeTown:
    """Reader and writer in one: a thread store with the AT Protocol's shapes."""

    dry = False

    def __init__(self):
        self.posts, self.order, self.n = {}, [], 0
        self.did = HALL_DID
        self.fail_next = 0
        self.sent = []

    def _new(self, did, handle, text, reply=None, facets=None, embed=None):
        self.n += 1
        uri = f"at://{did}/town.delve.feed.post/p{self.n}"
        rec = {"text": text, "createdAt": f"2026-11-23T00:00:{self.n:02d}.000Z"}
        if reply:
            rec["reply"] = reply
        if facets:
            rec["facets"] = facets
        self.posts[uri] = {"uri": uri, "cid": f"c{self.n}", "author": {"did": did, "handle": handle}, "record": rec,
                           "embed": embed}
        self.order.append(uri)
        return self.posts[uri]

    # writer
    def post(self, text, reply=None, image=None, alt=None):
        if self.fail_next:
            self.fail_next -= 1
            raise TownError("createRecord: HTTP 500")
        p = self._new(HALL_DID, "hall.delve.town", text, reply, embed={"image": image, "alt": alt} if image else None)
        self.sent.append(p)
        return {"uri": p["uri"], "cid": p["cid"]}

    # reader
    def thread(self, uri):
        def node(u):
            kids = [x for x in self.order if (self.posts[x]["record"].get("reply") or {}).get("parent", {}).get("uri") == u]
            return {"post": self.posts[u], "replies": [node(k) for k in kids]}
        return node(uri)

    # other residents
    def say(self, handle, text, parent, mention_hall=False):
        root = (parent["record"].get("reply") or {}).get("root") or {"uri": parent["uri"], "cid": parent["cid"]}
        facets = [{"index": {"byteStart": 0, "byteEnd": 1},
                   "features": [{"$type": "town.delve.richtext.facet#mention", "did": HALL_DID}]}] if mention_hall else None
        return self._new(f"did:plc:{handle.split('.')[0]}", handle, text,
                         {"root": root, "parent": {"uri": parent["uri"], "cid": parent["cid"]}}, facets)

    def replies_to(self, p):
        """The hall's replies to a post."""
        return [self.posts[u] for u in self.order if self.posts[u]["author"]["did"] == HALL_DID
                and (self.posts[u]["record"].get("reply") or {}).get("parent", {}).get("uri") == p["uri"]]


class Clock:
    def __init__(self):
        self.t = time.time()

    def __call__(self):
        return self.t


@pytest.fixture
def world(tmp_path):
    with serve(tmp_path) as (base, app):
        town, clock = FakeTown(), Clock()
        cfg = Config(public="https://hall.example", handle="hall.delve.town", state=tmp_path / "town.sqlite",
                     max_open=2, letters_per_day=3, levels=(1, 2, 3, 4),   # the pacing tests are written for these; production allows more
                     log=tmp_path / "town.jsonl")
        d = Daemon(cfg, HallClient(base, "admin-secret"), town, town, clock=clock, out=lambda *_: None)
        yield base, app, town, d, clock


def letter(base, describer, level=1, text="Two blocks: a red one low on the left, a blue one high on the right."):
    lid = describer.post("/api/letters", {"level": level})["letter"]
    describer.post(f"/api/letters/{lid}/send", {"text": text})
    return lid


def truth(app, lid):
    from tworooms import db as D
    hall = app.state.hall
    return D.loads(hall.picture(hall.letter(lid)["picture_id"])["shapes"])


def board(shapes):
    out = []
    for s in shapes:
        if s["shape"] == "rect":
            out.append(f"rect {s['color']} {s['x']:g} {s['y']:g} {s['w']:g} {s['h']:g}")
        elif s["shape"] == "ellipse":
            out.append(f"ellipse {s['color']} {s['cx']:g} {s['cy']:g} {s['rx']:g} {s['ry']:g}")
        else:
            out.append("triangle " + s["color"] + " " + " ".join(f"{v:g}" for p in s["points"] for v in p))
    return "\n".join(out)


# ---------------------------------------------------------------- the parser

def test_parser_is_forgiving_about_layout():
    one = parse_reply("rect red 2 1 3 2\nellipse blue 5 5 2 1.5\ntriangle green 1 1 4 1 1 5")
    assert [s["shape"] for s in one.shapes] == ["rect", "ellipse", "triangle"] and not one.errors
    for text in ("RECT Red 2 1 3 2, Ellipse BLUE 5 5 2 1.5", "rect red 2 1 3 2 + ellipse blue 5 5 2 1.5",
                 "red rect 2, 1, 3, 2; blue oval 5 5 2 1.5", "rect red x=2 y=1 w=3 h=2 / ellipse blue 5 5 2 1.5",
                 "My board, back to front:\n\nrect red 2 1 3 2\nellipse blue 5 5 2 1.5\n\nThe blue was a guess."):
        r = parse_reply(text)
        assert r.build and r.shapes[0] == {"shape": "rect", "color": "red", "x": 2, "y": 1, "w": 3, "h": 2}, text
        assert r.shapes[1]["rx"] == 2 and r.shapes[1]["ry"] == 1.5, text
    old = parse_reply("black 4.5, 5, 4.75, 4.75\ngreen 4, 2.25, 1.5, 2.5")     # as played by post in November
    assert old.build and old.shapes[0]["w"] == 4.75 and old.shapes[1]["color"] == "green"
    assert parse_reply("circle yellow 3 3 1").shapes[0]["ry"] == 1
    assert parse_reply("rect red 1/2 1 3 2").shapes[0]["x"] == 0.5


def test_parser_final_note_and_chatter():
    r = parse_reply("final\nrect red 2 1 3 2\nnote: 'a bit right' cost me the red one, rect red 9 9 9 9")
    assert r.final and len(r.shapes) == 1 and r.note.startswith("'a bit right'")
    assert not parse_reply("rect red 2 1 3 2 finally right").final
    for chatter in ("the red one was hard", "lovely letter, the blue reads well", "I scored 1306 of 1600",
                    "https://delve.town/profile/x/post/3n2 and @kit999.delve.town"):
        r = parse_reply(chatter)
        assert not r.shapes and not r.errors, chatter
    bad = parse_reply("rect red 2 1 3\nellipse blue 5 5 2 1.5")
    assert bad.shapes and not bad.build and "four numbers" in bad.errors[0]
    assert "which shape" in parse_reply("red 1 2 3").errors[0]


# ---------------------------------------------------------------- the daemon

def test_a_letter_is_posted_and_built_by_post(world):
    base, app, town, d, clock = world
    alice = Client.new(base, "alice")
    lid = letter(base, alice)
    d.tick()
    post = town.sent[0]
    t = post["record"]["text"]
    assert "Level 1, two blocks" in t and "Two blocks: a red one low" in t and "rect red 2 1 3 2 is x, y, width" in t
    assert t.index("Two blocks: a red one low") < t.index("Reply with your board") and len(t) < 600
    assert f"https://hall.example/letter/{lid}" in t and t.endswith(SIGN)

    pic = truth(app, lid)
    moved = [dict(s, x=s["x"] + 1 if s["x"] + s["w"] <= 9 else s["x"] - 1) for s in pic]
    r1 = town.say("tater.delve.town", board(moved), post)
    d.tick()
    a1 = town.replies_to(r1)
    assert len(a1) == 1 and a1[0]["record"]["text"].startswith("Check 1 of 2, your board of 2 shapes. In place: ")
    assert "). It would fit best moved" in a1[0]["record"]["text"] and "In place: of the cells" in a1[0]["record"]["text"]
    assert a1[0]["record"]["reply"]["root"]["uri"] == post["uri"]

    r2 = town.say("tater.delve.town", board(pic), a1[0])
    d.tick()
    a2 = town.replies_to(r2)[0]["record"]["text"]
    assert a2.startswith("Check 2 of 2") and "In place: 100% (nearly exact). Slid to fit: 100% (nearly exact)." in a2
    assert "No checks left" in a2 and "In place: of the cells" not in a2, "the readings are explained once"

    r3 = town.say("tater.delve.town", board(pic) + "\nnote: 'high on the right' was enough", town.replies_to(r2)[0])
    d.tick()
    a3 = town.replies_to(r3)[0]["record"]["text"]
    assert a3.startswith("Your build is in, 2 shapes. In place: 100% (nearly exact).") and "shown when this letter closes" in a3

    view = Client(base, "admin-secret").get(f"/api/letters/{lid}")
    res = view["results"][0]
    assert res["builder"] == "tater.delve.town" and res["via"] == "town" and res["note"].startswith("'high on")
    assert res["via_url"] == f"https://delve.town/profile/tater.delve.town/post/{r1['uri'].rsplit('/', 1)[1]}"
    assert [c["check"] for c in res["checks"]] == [1, 2]
    page = httpx.get(f"{base}/letter/{lid}", cookies={"tr_key": alice.key}).text
    assert "by post" in page

    r4 = town.say("tater.delve.town", board(pic), town.replies_to(r3)[0])
    d.tick()
    assert "already built" in town.replies_to(r4)[0]["record"]["text"]


def test_final_long_note_and_errors(world):
    base, app, town, d, clock = world
    lid = letter(base, Client.new(base, "alice"))
    d.tick()
    post = town.sent[0]
    pic = truth(app, lid)
    long = " ".join(["word"] * 61)
    r1 = town.say("nodus.delve.town", "final\n" + board(pic) + "\nnote: " + long, post)
    d.tick()
    a1 = town.replies_to(r1)[0]["record"]["text"]
    assert a1.startswith("Your note is 61 words and a note may be at most 60, so nothing has been submitted yet")
    r2 = town.say("nodus.delve.town", "final " + board(pic) + "\nnote: shorter", town.replies_to(r1)[0])
    d.tick()
    assert town.replies_to(r2)[0]["record"]["text"].startswith("Your build is in")

    r3 = town.say("kit.delve.town", "rect red 20 1 3 2", post)                      # off the board
    d.tick()
    assert town.replies_to(r3)[0]["record"]["text"].startswith("Not done: Shape 1")
    r4 = town.say("kit.delve.town", "rect red 2 1 3\nrect blue 1 1 1 1", town.replies_to(r3)[0])
    d.tick()
    assert "couldn't read that as a board" in town.replies_to(r4)[0]["record"]["text"]


def test_who_gets_an_answer(world):
    base, app, town, d, clock = world
    letter(base, Client.new(base, "alice"))
    d.tick()
    post = town.sent[0]
    chat = town.say("meitan.delve.town", "nice one, the blue reads well", post)
    talk = town.say("tater.delve.town", "rect red 1 1 2 2 would be my guess", chat)        # to someone else
    ping = town.say("meitan.delve.town", "@hall.delve.town how do I play?", post, mention_hall=True)
    d.tick()
    assert town.replies_to(chat) == [] and town.replies_to(talk) == []
    fmt = town.replies_to(ping)[0]["record"]["text"]
    assert fmt.startswith("To build this letter, reply under it with your board") and fmt.endswith(SIGN)
    again = town.say("meitan.delve.town", "@hall.delve.town hello?", town.replies_to(ping)[0], mention_hall=True)
    d.tick()
    assert town.replies_to(again) == [], "the format is given once"
    log = (d.cfg.log).read_text()
    assert log.count('"kind": "read"') == 4 and log.count('"kind": "posted"') == 2


def test_never_twice_in_a_row_and_retry(world):
    base, app, town, d, clock = world
    lid = letter(base, Client.new(base, "alice"))
    d.tick()
    post = town.sent[0]
    pic = truth(app, lid)
    town.say("tater.delve.town", board(pic), post)
    second = town.say("tater.delve.town", board(pic), post)
    town.fail_next = 1
    d.tick()
    assert town.replies_to(second) == [], "the town refused; the answer waits"
    d.tick()
    ans = town.replies_to(second)
    assert len(ans) == 1, "one answer to the latest post, not two in a row"
    assert "Check 1 of 2" in ans[0]["record"]["text"] and "Check 2 of 2" in ans[0]["record"]["text"]
    assert len([p for p in town.sent if p["record"].get("reply", {}).get("parent", {}).get("uri", "").startswith("at://did:plc:tater")]) == 1


def test_letters_are_paced_and_closed(world):
    base, app, town, d, clock = world
    alice, bob = Client.new(base, "alice"), Client.new(base, "bob")
    lids = [letter(base, alice, 1), letter(base, bob, 2), letter(base, alice, 3), letter(base, bob, 4),
            letter(base, alice, 5)]
    for _ in range(3):
        d.tick()
    first = [p for p in town.sent if "reply" not in p["record"]]
    assert len(first) == 2, "at most two open at a time"
    assert not any(f"/letter/{lids[4]}" in p["record"]["text"] for p in first), "level 5 is not posted"

    pic = truth(app, lids[0]) if f"/letter/{lids[0]}" in first[0]["record"]["text"] else None
    clock.t += 49 * 3600
    d.tick()
    closings = [p for p in town.sent if p["embed"]]
    assert len(closings) == 2
    c = closings[0]
    assert c["embed"]["image"][:8] == b"\x89PNG\r\n\x1a\n"
    assert c["record"]["text"].startswith("Closed (two days in Delve Town). The picture was a ")
    assert "The picture of this letter and every build of it" in c["embed"]["alt"] and "Nobody built it." in c["embed"]["alt"]
    admin = Client(base, "admin-secret")
    lid0 = d.one("SELECT letter FROM letters ORDER BY posted LIMIT 1")["letter"]
    v = admin.get(f"/api/letters/{lid0}")
    assert v["status"] == "closed" and v["close_reason"] == "closed after two days in Delve Town"
    assert pic is None or v["picture_words"]
    assert len([p for p in town.sent if "reply" not in p["record"]]) == 3, "one new letter per tick"
    d.tick()
    assert len([p for p in town.sent if "reply" not in p["record"]]) == 4, "two more once those closed"
    for _ in range(3):
        clock.t += 49 * 3600 / 4
        d.tick()
    assert len([p for p in town.sent if "reply" not in p["record"]]) <= 4 + 0, "no candidates left at levels 1-4"


def test_a_letter_built_in_the_hall_closes_in_the_town(world):
    base, app, town, d, clock = world
    lid = letter(base, Client.new(base, "alice"))
    d.tick()
    post = town.sent[0]
    town.say("tater.delve.town", board(truth(app, lid)) + " final", post)
    d.tick()
    for name in ("b1", "b2", "b3", "b4"):
        p = Client.new(base, name)
        bid = p.post(f"/api/letters/{lid}/builds")["build"]
        p.put(f"/api/builds/{bid}/shapes", truth(app, lid))
        p.post(f"/api/builds/{bid}/submit")
    d.tick()
    closing = [p for p in town.sent if p["embed"]][0]
    text = closing["record"]["text"]
    assert text.startswith("Closed (5 builds).") and "tater.delve.town: in place 100% (nearly exact)" in text
    assert "b1 (in the hall): in place 100%" in text
    assert "tater.delve.town, in place 100% (nearly exact), slid to fit 100% (nearly exact)" in closing["embed"]["alt"]


def test_only_the_admin_registers_town_players(world):
    base, app, town, d, clock = world
    r = httpx.post(base + "/api/players", json={"callsign": "faker", "via": "town"})
    assert r.status_code == 201
    assert app.state.hall.player_by_callsign("faker")["via"] is None
    lid = letter(base, Client.new(base, "alice"))
    faker = Client(base, r.json()["key"])
    bid = faker.post(f"/api/letters/{lid}/builds", {"via_url": "https://delve.town/profile/x/post/y"})["build"]
    row = app.state.hall.one("SELECT via, via_url FROM builds WHERE id=?", bid)
    assert row["via"] is None and row["via_url"] is None
    assert httpx.get(f"{base}/og/boards/{lid}.png").status_code == 403


def test_a_checked_board_counts_when_the_letter_closes(world):
    base, app, town, d, clock = world
    lid = letter(base, Client.new(base, "alice"))
    d.tick()
    post = town.sent[0]
    r = town.say("tater.delve.town", board(truth(app, lid)), post)
    d.tick()
    assert town.replies_to(r)[0]["record"]["text"].startswith("Check 1 of 2")
    clock.t += 49 * 3600
    d.tick()
    closing = [p for p in town.sent if p["embed"]][0]["record"]["text"]
    assert "tater.delve.town (last board checked): in place 100% (nearly exact), slid to fit 100% (nearly exact)" in closing
    v = Client(base, "admin-secret").get(f"/api/letters/{lid}")
    assert v["status"] == "closed" and v["results"][0]["builder"] == "tater.delve.town"


def test_long_words_go_on_as_replies(world):
    base, app, town, d, clock = world
    d.cfg.max_post_chars = 300
    words = " ".join(["blue block low and wide, red block high and narrow;"] * 4)
    lid = letter(base, Client.new(base, "alice"), level=2, text=words)
    d.tick()
    first, *rest = town.sent
    assert "reply" not in first["record"] and len(rest) >= 2
    assert all(p["record"]["reply"]["root"]["uri"] == first["uri"] for p in rest)
    assert all(len(p["record"]["text"]) <= 300 for p in town.sent[:-1])
    said_words = " ".join(p["record"]["text"] for p in town.sent[:-1]).split("in 40 words.", 1)[1]
    assert said_words.replace("…", " ").split() == words.split()
    assert rest[-1]["record"]["text"].endswith(SIGN) and f"/letter/{lid}" in rest[-1]["record"]["text"]
