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
    res = r["result"]
    assert res["in_place"] == 100.0 and res["slid_to_fit"] == 100.0 and res["picture_shapes"] == perfect
    assert "passed" not in res and "score" not in res and res["loss"] is None and res["others"] == 0
    assert r["waiting_on"] is None and r["next"].startswith("Nearly exact · 100% in place; nearly exact · 100% slid to fit")
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
    assert low["result"]["in_place"] < 50 and low["result"]["others"] == 1
    assert low["result"]["loss"]["colour"] == "green" and "green" in low["result"]["loss"]["sentence"]

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
    assert anon.get(f"/api/matches/{mid}")["you"]["role"] == "watching", "an anonymous visitor is not a player"
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
    assert "past nine" in bob.post(f"/api/matches/{mid}/say", {"text": "it is twelve wide"}, expect=422)["error"]
    assert st["current"]["budget"] == 2 * LEVELS[1].budget
    assert bob.get(f"/api/matches/{mid}")["current"]["describer_words_used"] == 0
    assert bob.post(f"/api/matches/{mid}/say", {"text": "x " * (2 * LEVELS[1].budget + 1)}, expect=422)["error"]

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

    st = alice.post(f"/api/matches/{mid}/say", {"text": "how big is the red one compared to the board?"})
    assert st["waiting_on"] == "bob" and "You asked bob a question" in st["next"]
    bnext = bob.get(f"/api/matches/{mid}")["next"]
    assert "alice asked" in bnext and "how big is the red one" in bnext and "Answer it" in bnext
    assert anon.get(f"/api/matches/{mid}")["you"]["role"] == "watching"
    assert "events" not in anon.get(f"/api/matches/{mid}")

    alice.post(f"/api/builds/{mid}/place", {"shape": "rect", "color": "red", "x": 1, "y": 1, "w": 3, "h": 3})
    assert alice.get(f"/api/builds/{mid}")["count"] == 1
    r = alice.post(f"/api/builds/{mid}/submit", {"note": "red was fine"})
    r1 = r["result"]
    st = alice.get(f"/api/matches/{mid}")
    assert st["round"] == 2 and st["you"]["role"] == "describer" and len(st["finished_rounds"]) == 1
    expected_level = 2 if r1["in_place"] >= 75 else 1
    assert st["current"]["level"] == expected_level
    assert st["current"]["word"] != st["finished_rounds"][0]["word"]

    rid1 = st["finished_rounds"][0]["round"]
    pub = anon.get(f"/api/rounds/{rid1}")
    assert pub["chat"][0]["text"].startswith("Two blocks") and pub["result"]["in_place"] == r1["in_place"]
    assert "checks" not in pub["result"]
    assert pub["describer_words"] == 16 and pub["builder_words"] == 10 and pub["budget"] == 2 * LEVELS[1].budget

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
        codes = [httpx.post(base + "/api/players", json={"callsign": f"x{i}"}).status_code for i in range(31)]
        assert codes[:30] == [201] * 30 and codes[30] == 429


def test_word_check_spends_nothing(server):
    base, app = server
    r = httpx.post(base + "/api/words", json={"text": "a red block, three quarters across", "budget": 6})
    assert r.json() == {"words": 6, "ok": True, "next": "It would be accepted."}
    r = httpx.post(base + "/api/words", json={"text": "a red block, three quarters across", "budget": 5})
    assert not r.json()["ok"] and "5 left" in r.json()["error"]
    r = httpx.post(base + "/api/words", json={"text": "eleven blocks"})
    assert not r.json()["ok"] and r.json()["error"].startswith("Would be refused")


def test_time_rules(server):
    """Idle builds give their slot back, letters close after seven days, idle matches are abandoned."""
    base, app = server
    hall = app.state.hall
    a, b, c = (Client.new(base, n) for n in ("alice", "bob", "carol"))
    lid = a.post("/api/letters", {"level": 1})["letter"]
    a.post(f"/api/letters/{lid}/send", {"text": "two blocks"})
    bid = b.post(f"/api/letters/{lid}/builds")["build"]
    day = 86400
    hall.db.execute("UPDATE builds SET updated=updated-? WHERE id=?", (2 * day, bid))
    hall.sweep(force=True)
    assert b.get(f"/api/builds/{bid}")["status"] == "expired"
    assert "expired" in b.post(f"/api/builds/{bid}/submit", expect=409)["error"]
    hall.db.execute("UPDATE letters SET sent=sent-? WHERE id=?", (8 * day, lid))
    hall.sweep(force=True)
    assert a.get(f"/api/letters/{lid}")["close_reason"] == "seven days passed"
    m = a.post("/api/matches", {"open": True})["match"]
    c.post(f"/api/matches/{m}/join")
    hall.db.execute("UPDATE matches SET updated=updated-? WHERE id=?", (8 * day, m))
    hall.sweep(force=True)
    assert a.get(f"/api/matches/{m}")["status"] == "abandoned"
    assert Client(base).get(f"/api/letters/{lid}")["status"] == "closed"


def test_stale_board_waits_on_the_builder(server):
    base, app = server
    hall = app.state.hall
    a, b = Client.new(base, "alice"), Client.new(base, "bob")
    m = a.post("/api/matches", {"open": False})["match"]
    b.post(f"/api/matches/{m}/join")
    b.post(f"/api/matches/{m}/say", {"text": "a red block"})
    a.post(f"/api/matches/{m}/say", {"text": "where?"})
    assert a.get(f"/api/matches/{m}")["waiting_on"] == "bob"
    a.post(f"/api/builds/{m}/place", {"shape": "rect", "color": "red", "x": 1, "y": 1, "w": 2, "h": 2})
    hall.db.execute("UPDATE builds SET updated=updated-90000")
    hall.db.execute("UPDATE messages SET created=created-90000")
    st = a.get(f"/api/matches/{m}")
    assert st["waiting_on"] == "alice" and "submit" in st["waiting_sentence"]

    r = httpx.post(base + "/api/words", json={"text": "five quarters of it"})
    assert not r.json()["ok"] and "counting in fractions" in r.json()["error"]


def test_two_checks_before_submit(server):
    base, app = server
    a, b, c = (Client.new(base, n) for n in ("alice", "bob", "carol"))
    lid = a.post("/api/letters", {"level": 2})["letter"]
    a.post(f"/api/letters/{lid}/send", {"text": "blocks"})
    t = b.post(f"/api/letters/{lid}/builds")
    bid = t["build"]
    assert t["checks_left"] == 2 and "check" in t["next"]
    assert "empty" in b.post(f"/api/builds/{bid}/check", expect=409)["error"]
    truth = D.loads(app.state.hall.picture(app.state.hall.letter(lid)["picture_id"])["shapes"])
    moved = [dict(s, x=s["x"] + 0.5) if s["x"] + s["w"] <= 9.5 else s for s in truth]
    b.put(f"/api/builds/{bid}/shapes", moved[:2])
    c1 = b.post(f"/api/builds/{bid}/check")
    assert c1["check"] == 1 and c1["checks_left"] == 1 and set(c1) >= {"in_place", "slid_to_fit"}
    assert "picture" not in str(sorted(c1)) and "slide" not in c1, "a check shows only the two readings"
    b.put(f"/api/builds/{bid}/shapes", truth)
    c2 = b.post(f"/api/builds/{bid}/check")
    assert c2["in_place"] == 100.0 and c2["checks_left"] == 0
    assert "both checks" in b.post(f"/api/builds/{bid}/check", expect=409)["error"]
    assert b.status(f"/api/builds/{bid}/checks/1.png") == 200
    assert c.status(f"/api/builds/{bid}/checks/1.png") == 403
    r = b.post(f"/api/builds/{bid}/submit")["result"]
    assert [x["check"] for x in r["checks"]] == [1, 2] and r["checks"][0]["in_place"] == c1["in_place"]
    view = a.get(f"/api/letters/{lid}")
    assert view["results"][0]["checks"][1]["in_place"] == 100.0
    a.post(f"/api/letters/{lid}/close")
    assert c.status(f"/api/builds/{bid}/checks/1.png") == 200


def test_no_checks_in_live_rounds(server):
    base, app = server
    a, b = Client.new(base, "alice"), Client.new(base, "bob")
    m = a.post("/api/matches", {"open": False})["match"]
    b.post(f"/api/matches/{m}/join")
    a.post(f"/api/builds/{m}/place", {"shape": "rect", "color": "red", "x": 1, "y": 1, "w": 2, "h": 2})
    assert "Ask the describer" in a.post(f"/api/builds/{m}/check", expect=409)["error"]
    b.post(f"/api/matches/{m}/say", {"text": " ".join(["word"] * (2 * LEVELS[1].budget))})
    assert "no words left" in a.post(f"/api/builds/{m}/check", expect=409)["error"]
    assert "questions can't be answered" in a.get(f"/api/matches/{m}")["next"]


def test_old_database_is_migrated_and_backfilled(tmp_path):
    """A database from before the two readings gets the new columns and its builds get "slid to fit"."""
    import sqlite3
    from tworooms.game import Hall
    path = tmp_path / "old.sqlite"
    with serve(tmp_path) as (base, app):
        pass
    conn = D.connect(tmp_path / "t.sqlite")
    hall = Hall(conn)
    a = hall.create_player("alice")
    b = hall.create_player("bob")
    pa, pb = hall.player_by_callsign("alice"), hall.player_by_callsign("bob")
    lid = hall.create_letter(pa, 1)["letter"]
    hall.send_letter(pa, lid, "two blocks")
    bid = hall.take_letter(pb, lid)["build"]
    truth = hall.shapes_of(hall.letter(lid)["picture_id"])
    hall.put_shapes(pb, bid, [dict(s, x=s["x"] + 1) if s["x"] + s["w"] <= 9 else dict(s, x=s["x"] - 1) for s in truth])
    hall.submit(pb, bid)
    # make it look like an old database: drop what the migration adds
    conn.execute("ALTER TABLE builds DROP COLUMN slid")
    conn.execute("ALTER TABLE builds DROP COLUMN slide_dx")
    conn.execute("ALTER TABLE builds DROP COLUMN slide_dy")
    conn.execute("ALTER TABLE pictures DROP COLUMN kind")
    conn.execute("DROP TABLE checks")
    conn.close()
    hall2 = Hall(D.connect(tmp_path / "t.sqlite"))
    row = hall2.one("SELECT * FROM builds WHERE id=?", bid)
    assert row["slid"] is not None and row["slid"] >= row["overlap"]
    r = hall2.letter_view(None, lid) if False else hall2.build_state(pb, bid)["result"]
    assert r["slid_to_fit"] == row["slid"] and r["checks"] == []


def test_place_several_at_once_and_reading_words(server):
    base, app = server
    a, b = Client.new(base, "alice"), Client.new(base, "bob")
    lid = a.post("/api/letters", {"level": 1})["letter"]
    a.post(f"/api/letters/{lid}/send", {"text": "two blocks"})
    bid = b.post(f"/api/letters/{lid}/builds")["build"]
    d = b.post(f"/api/builds/{bid}/place", [{"shape": "rect", "color": "red", "x": 1, "y": 1, "w": 2, "h": 2},
                                            {"shape": "ellipse", "color": "blue", "cx": 6.1, "cy": 6, "rx": 1, "ry": 1}])
    assert d["count"] == 2 and d["placed"] == ["1. rect red 1 1 2 2", "2. ellipse blue 6.125 6 1 1"]
    assert d["notes"] == ["shape 2: Rounded to steps of 1/8: cx 6.1 → 6.125."]
    bad = b.post(f"/api/builds/{bid}/place", [{"shape": "rect", "color": "red", "x": 1, "y": 1, "w": 1, "h": 1},
                                              {"shape": "rect", "color": "pink", "x": 1, "y": 1, "w": 1, "h": 1}], expect=422)
    assert bad["error"].startswith("Shape 2:") and "Nothing was placed" in bad["error"]
    assert b.get(f"/api/builds/{bid}")["count"] == 2
    truth = D.loads(app.state.hall.picture(app.state.hall.letter(lid)["picture_id"])["shapes"])
    b.put(f"/api/builds/{bid}/shapes", truth)
    r = b.post(f"/api/builds/{bid}/submit")
    assert r["result"]["in_place_word"] == "nearly exact" and r["next"].startswith("Nearly exact · 100% in place")
    from tworooms.game import reading_word
    assert [reading_word(v) for v in (70, 69.9, 50, 30, 29.9)] == ["nearly exact", "close", "close", "recognisable", "elsewhere"]
