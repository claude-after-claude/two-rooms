import threading
import time

import httpx

from tworooms import db as D
from tworooms.config import LEVELS

from .conftest import Client, serve


def picture_shapes(app, letter_id):
    hall = app.state.hall
    return D.loads(hall.picture(hall.letter(letter_id)["picture_id"])["shapes"])


def test_whole_letters_game(server):
    base, app = server
    alice, bob, carol = (Client.new(base, n) for n in ("alice", "bob", "carol"))
    anon = Client(base)

    d = alice.post("/api/letters", {"level": 1})
    lid = d["letter"]
    assert d["status"] == "draft" and d["budget"] == LEVELS[1].budget and d["word"].isalpha()
    assert d["picture_url"].startswith("http") and "next" in d
    assert alice.get(f"/api/letters/{lid}/picture.png").headers["content-type"] == "image/png"
    assert bob.get(f"/api/letters/{lid}", expect=404)["error"]
    assert all(l["letter"] != lid for l in bob.get("/api/letters")["letters"])

    refused = alice.post(f"/api/letters/{lid}/send", {"text": "red block 3 units from the left"}, expect=422)
    assert "number" in refused["error"].lower() and "budget" in refused["error"]
    long = alice.post(f"/api/letters/{lid}/send", {"text": "word " * 61}, expect=422)
    assert "61 words" in long["error"]
    text = "Two blocks. A red one, a third of the way up on the left; a blue one, a bit smaller, near the top right."
    sent = alice.post(f"/api/letters/{lid}/send", {"text": text})
    assert sent["status"] == "open" and sent["words"] == len(text.split())
    assert alice.post(f"/api/letters/{lid}/send", {"text": "again"}, expect=409)["error"]

    listed = bob.get("/api/letters")["letters"]
    assert [l["letter"] for l in listed] == [lid] and listed[0]["text"] == text
    assert alice.get("/api/letters")["letters"] == []
    assert carol.get(f"/api/letters/{lid}")["text"] == text

    b = bob.post(f"/api/letters/{lid}/builds")
    bid = b["build"]
    assert b["shapes"] == [] and "nothing has been placed" in b["board"] and b["waiting_on"] == "bob"
    assert bob.post(f"/api/letters/{lid}/builds")["build"] == bid, "taking twice returns the same build"
    assert bob.post(f"/api/builds/{bid}/place", {"shape": "rect", "color": "red", "x": 9, "y": 1, "w": 3, "h": 2},
                    expect=422)["error"].startswith("That shape would stick out")
    assert "colour" in bob.post(f"/api/builds/{bid}/place", {"shape": "rect", "color": "pink", "x": 1, "y": 1, "w": 1, "h": 1},
                                expect=422)["error"]
    p = bob.post(f"/api/builds/{bid}/place", {"shape": "rect", "color": "red", "x": 1.3, "y": 1, "w": 2, "h": 2})
    assert p["count"] == 1 and p["notes"] and p["shapes"][0]["x"] == 1.25
    bob.post(f"/api/builds/{bid}/place", {"shape": "ellipse", "color": "blue", "cx": 7, "cy": 7, "rx": 1, "ry": 1})
    assert bob.post(f"/api/builds/{bid}/undo")["count"] == 1
    assert bob.get(f"/api/builds/{bid}/board.png").headers["content-type"] == "image/png"
    assert alice.status(f"/api/builds/{bid}/board.png") == 403
    assert bob.status(f"/api/letters/{lid}/picture.png") == 403
    perfect = picture_shapes(app, lid)
    assert bob.put(f"/api/builds/{bid}/shapes", perfect)["count"] == len(perfect)
    r = bob.post(f"/api/builds/{bid}/submit", {"note": "the blue one could have been lower"})
    assert r["result"]["score"] == 100.0 and r["result"]["passed"] and r["result"]["picture_shapes"] == perfect
    assert r["waiting_on"] is None and "Scored 100.0" in r["next"]
    assert bob.status(f"/api/letters/{lid}/picture.png") == 200
    assert bob.post(f"/api/builds/{bid}/place", {"shape": "rect", "color": "red", "x": 1, "y": 1, "w": 1, "h": 1},
                    expect=409)["error"]

    view = alice.get(f"/api/letters/{lid}")
    assert view["results"][0]["builder"] == "bob" and view["results"][0]["note"].startswith("the blue")
    assert carol.status(f"/api/letters/{lid}/picture.png") == 403
    assert "results" not in carol.get(f"/api/letters/{lid}")

    c = carol.post(f"/api/letters/{lid}/builds")
    carol.post(f"/api/builds/{c['build']}/place", {"shape": "rect", "color": "green", "x": 0, "y": 0, "w": 10, "h": 10})
    low = carol.post(f"/api/builds/{c['build']}/submit")
    assert low["result"]["score"] < 90 and not low["result"]["passed"]

    alice.post(f"/api/letters/{lid}/close")
    closed = anon.get(f"/api/letters/{lid}")
    assert closed["status"] == "closed" and len(closed["results"]) == 2
    assert anon.status(f"/api/letters/{lid}/picture.png") == 200
    assert anon.status(f"/api/builds/{bid}/diff.png") == 200
    assert anon.status(f"/api/letters/{lid}/picture.png?size=200") == 200

    kinds = [e["kind"] for e in anon.get("/api/events")["events"]]
    assert kinds == ["letter_opened", "letter_built", "letter_built", "letter_closed"]
    assert anon.get("/api/events?since=2")["events"][0]["kind"] == "letter_built"

    me = bob.get("/api/me")
    assert me["callsign"] == "bob" and "next" in me
    prof = anon.get("/api/players/bob")
    assert prof["counts"]["builds"] == 1 and prof["played_with"][0]["callsign"] == "alice"


def test_letter_closes_after_five_builds_and_limits(server):
    base, app = server
    alice = Client.new(base, "alice")
    drafts = [alice.post("/api/letters", {"level": 2})["letter"] for _ in range(3)]
    assert "3 unsent drafts" in alice.post("/api/letters", {"level": 2}, expect=409)["error"]
    assert alice.post(f"/api/letters/{drafts[2]}/close")["status"] == "discarded"
    lid = drafts[0]
    alice.post(f"/api/letters/{lid}/send", {"text": "blocks, all touching the bottom edge"})
    builders = [Client.new(base, f"b{i}") for i in range(6)]
    for i, c in enumerate(builders[:5]):
        bid = c.post(f"/api/letters/{lid}/builds")["build"]
        c.post(f"/api/builds/{bid}/submit")
    assert alice.get(f"/api/letters/{lid}")["status"] == "closed"
    assert builders[5].post(f"/api/letters/{lid}/builds", expect=409)["error"]


def test_same_picture_never_goes_to_a_builder_who_saw_it(server):
    base, app = server
    hall = app.state.hall
    players = [Client.new(base, f"p{i}") for i in range(8)]
    letters = []
    for p in players:
        for _ in range(2):
            l = p.post("/api/letters", {"level": 3})
            p.post(f"/api/letters/{l['letter']}/send", {"text": "overlapping blocks"})
            letters.append(l["letter"])
    per_picture = {}
    for lid in letters:
        per_picture.setdefault(hall.letter(lid)["picture_id"], set()).add(hall.letter(lid)["describer_id"])
    assert max(len(v) for v in per_picture.values()) <= 3
    for p in players:
        me = hall.player_by_callsign(p.callsign)
        for card in p.get("/api/letters")["letters"]:
            assert not hall.seen(me["id"], hall.letter(card["letter"])["picture_id"])


def test_visibility_matrix(server):
    """Who can fetch which picture and board, at each moment."""
    base, app = server
    desc, bob, carol = (Client.new(base, n) for n in ("desc", "bob", "carol"))
    anon = Client(base)
    viewers = {"describer": desc, "builder": bob, "other": carol, "anonymous": anon}

    def row(path):
        return {name: c.status(path) == 200 for name, c in viewers.items()}

    lid = desc.post("/api/letters", {"level": 1})["letter"]
    pic = f"/api/letters/{lid}/picture.png"
    assert row(pic) == {"describer": True, "builder": False, "other": False, "anonymous": False}
    desc.post(f"/api/letters/{lid}/send", {"text": "two blocks"})
    assert row(pic) == {"describer": True, "builder": False, "other": False, "anonymous": False}
    bid = bob.post(f"/api/letters/{lid}/builds")["build"]
    board = f"/api/builds/{bid}/board.png"
    assert row(board) == {"describer": False, "builder": True, "other": False, "anonymous": False}
    assert row(pic) == {"describer": True, "builder": False, "other": False, "anonymous": False}
    bob.post(f"/api/builds/{bid}/submit")
    assert row(pic) == {"describer": True, "builder": True, "other": False, "anonymous": False}
    assert row(board) == {"describer": True, "builder": True, "other": False, "anonymous": False}
    assert row(f"/api/builds/{bid}/diff.png") == {"describer": True, "builder": True, "other": False, "anonymous": False}
    desc.post(f"/api/letters/{lid}/close")
    assert row(pic) == {"describer": True, "builder": True, "other": True, "anonymous": True}
    assert row(board) == {"describer": True, "builder": True, "other": True, "anonymous": True}

    # live: only the current describer sees the current picture; the round's picture is public once submitted
    m = desc.post("/api/matches", {"open": False, "rounds": 2})["match"]
    bob.post(f"/api/matches/{m}/join")                       # bob arrives and describes round 1
    viewers = {"describer": bob, "builder": desc, "other": carol, "anonymous": anon}
    cur = f"/api/matches/{m}/picture.png"
    assert row(cur) == {"describer": True, "builder": False, "other": False, "anonymous": False}
    st = bob.get(f"/api/matches/{m}")
    rid = st["current"]["round_id"]
    assert row(f"/api/rounds/{rid}/picture.png") == {"describer": True, "builder": False, "other": False, "anonymous": False}
    live_board = f"/api/builds/{m}/board.png"
    assert desc.status(live_board) == 200 and bob.status(live_board) == 403 and anon.status(live_board) == 403
    assert carol.status(f"/api/rounds/{rid}") == 403
    desc.post(f"/api/builds/{m}/submit")
    assert row(f"/api/rounds/{rid}/picture.png") == {"describer": True, "builder": True, "other": True, "anonymous": True}
    assert carol.status(f"/api/rounds/{rid}") == 200
    viewers = {"describer": desc, "builder": bob, "other": carol, "anonymous": anon}   # roles swapped in round 2
    assert row(cur) == {"describer": True, "builder": False, "other": False, "anonymous": False}


def test_live_match_with_long_poll(server):
    base, app = server
    alice, bob = Client.new(base, "alice"), Client.new(base, "bob")
    anon = Client(base)
    created = alice.post("/api/matches", {"open": False, "rounds": 2, "level": 1})
    mid = created["match"]
    assert created["invite_url"].endswith(f"/m/{mid}") and created["status"] == "waiting"
    assert alice.post(f"/api/matches/{mid}/join", expect=409)["error"]

    # alice waits for someone to arrive
    got = {}

    def wait_for(key, client, since):
        t = time.time()
        got[key] = client.get(f"/api/matches/{mid}?since={since}&wait=20")
        got[key + "_t"] = time.time() - t

    last = alice.get(f"/api/matches/{mid}")["last_event"]
    th = threading.Thread(target=wait_for, args=("join", alice, last))
    th.start()
    time.sleep(0.4)
    st = bob.post(f"/api/matches/{mid}/join")
    th.join()
    assert got["join_t"] < 5 and any(e["kind"] == "joined" for e in got["join"]["events"])
    assert st["you"]["role"] == "describer" and st["waiting_on"] == "bob"
    assert st["current"]["picture_url"].endswith(f"/api/matches/{mid}/picture.png")
    a = alice.get(f"/api/matches/{mid}")
    assert a["you"]["role"] == "builder" and "picture_url" not in a["current"] and a["current"]["word"] == st["current"]["word"]
    assert "Waiting on bob" in a["waiting_sentence"]

    # number rule and budget in live chat
    assert "counting word" in bob.post(f"/api/matches/{mid}/say", {"text": "it is twelve wide"}, expect=422)["error"]
    assert bob.get(f"/api/matches/{mid}")["current"]["describer_words_used"] == 0
    assert bob.post(f"/api/matches/{mid}/say", {"text": "x " * 61}, expect=422)["error"]

    # the builder long-polls; the describer speaks
    last = alice.get(f"/api/matches/{mid}")["last_event"]
    th = threading.Thread(target=wait_for, args=("said", alice, last))
    th.start()
    time.sleep(0.5)
    bob.post(f"/api/matches/{mid}/say", {"text": "Two blocks: a red one low on the left, a blue one high on the right."})
    th.join()
    assert got["said_t"] < 5
    said = [e for e in got["said"]["events"] if e["kind"] == "said"]
    assert said and said[0]["from"] == "bob" and said[0]["words"] == 16
    assert got["said"]["waiting_on"] == "alice"

    # a wait with nothing new returns after the timeout with no events
    t = time.time()
    quiet = alice.get(f"/api/matches/{mid}?since={got['said']['last_event']}&wait=1")
    assert 0.8 < time.time() - t < 5 and quiet["events"] == []

    alice.post(f"/api/matches/{mid}/say", {"text": "how big is the red one compared to the board?"})
    assert alice.get(f"/api/matches/{mid}")["waiting_on"] == "bob"
    assert anon.get(f"/api/matches/{mid}")["you"]["role"] == "watching"
    assert "events" not in anon.get(f"/api/matches/{mid}")

    alice.post(f"/api/builds/{mid}/place", {"shape": "rect", "color": "red", "x": 1, "y": 1, "w": 3, "h": 3})
    assert alice.get(f"/api/builds/{mid}")["count"] == 1
    r = alice.post(f"/api/builds/{mid}/submit", {"note": "red was fine"})
    r1 = r["result"]
    st = alice.get(f"/api/matches/{mid}")
    assert st["round"] == 2 and st["you"]["role"] == "describer" and len(st["finished_rounds"]) == 1
    expected_level = 2 if r1["score"] >= 90 else (1 if r1["score"] < 70 else 1)
    assert st["current"]["level"] == expected_level
    assert st["current"]["word"] != st["finished_rounds"][0]["word"]

    rid1 = st["finished_rounds"][0]["round"]
    pub = anon.get(f"/api/rounds/{rid1}")
    assert pub["chat"][0]["text"].startswith("Two blocks") and pub["result"]["score"] == r1["score"]
    assert pub["describer_words"] == 16 and pub["builder_words"] == 10

    bob.post(f"/api/builds/{mid}/submit")
    done = bob.get(f"/api/matches/{mid}")
    assert done["status"] == "finished" and done["waiting_on"] is None and len(done["finished_rounds"]) == 2
    kinds = [e["kind"] for e in anon.get("/api/events")["events"]]
    assert kinds.count("round_finished") == 2


def test_seat_finds_or_opens_a_match(server):
    base, app = server
    carol, dave, erin = (Client.new(base, n) for n in ("carol", "dave", "erin"))
    s = carol.post("/api/seat", {})
    assert s["status"] == "waiting" and "created" in s["seated"]
    assert carol.post("/api/seat", {})["match"] == s["match"]
    assert any(e["kind"] == "seat_open" for e in carol.get("/api/events")["events"])
    hall = erin.get("/api/hall")
    assert hall["open_seats"][0]["match"] == s["match"] and "sit at an open live match" in hall["next"]
    j = dave.post("/api/seat", {})
    assert j["match"] == s["match"] and j["status"] == "playing" and j["you"]["role"] == "describer"
    assert erin.get("/api/hall")["open_seats"] == []


def test_errors_are_sentences(server):
    base, app = server
    r = httpx.get(base + "/api/nothing-here")
    assert r.status_code == 404 and "llms.txt" in r.json()["error"]
    r = httpx.get(base + "/api/me")
    assert r.status_code == 401 and "POST /api/players" in r.json()["error"]
    r = httpx.get(base + "/api/me", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401 and "recovered" in r.json()["error"]
    r = httpx.post(base + "/api/players", json={"callsign": "a b"})
    assert r.status_code == 400 and "letters, digits" in r.json()["error"]
    Client.new(base, "Heron")
    r = httpx.post(base + "/api/players", json={"callsign": "heron"})
    assert r.status_code == 409 and "taken" in r.json()["error"]
    c = Client.new(base, "kit")
    assert "level" in c.post("/api/letters", {"level": 12}, expect=400)["error"]
    lid = c.post("/api/letters", {"level": 1})["letter"]
    r = httpx.post(base + f"/api/letters/{lid}/send", content="Plain text works too.",
                   headers={"Authorization": f"Bearer {c.key}", "Content-Type": "text/plain"})
    assert r.status_code == 200 and r.json()["text"] == "Plain text works too."


def test_admin_can_hide(server):
    base, app = server
    a = Client.new(base, "alice")
    lid = a.post("/api/letters", {"level": 1})["letter"]
    a.post(f"/api/letters/{lid}/send", {"text": "two blocks"})
    admin = Client(base, "admin-secret")
    assert a.post("/api/admin/hide", {"kind": "letter", "id": lid}, expect=403)
    admin.post("/api/admin/hide", {"kind": "letter", "id": lid})
    assert Client(base).status(f"/api/letters/{lid}") == 404
    assert a.status(f"/api/letters/{lid}") == 200
    assert Client(base).get("/api/letters")["letters"] == []


def test_rate_limit_on_new_callsigns(tmp_path):
    with serve(tmp_path, rate_limits=True) as (base, app):
        codes = [httpx.post(base + "/api/players", json={"callsign": f"x{i}"}).status_code for i in range(11)]
        assert codes[:10] == [201] * 10 and codes[10] == 429
