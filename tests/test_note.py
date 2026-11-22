"""An over-long builder's note is refused whole, on every route, and nothing is submitted (nodus, 22 Nov 2026)."""
import httpx

from .conftest import Client

LONG = " ".join(f"word{i}" for i in range(61))
SHAPE = {"shape": "rect", "color": "red", "x": 1, "y": 1, "w": 2, "h": 2}


def letter_build(base, a, b):
    lid = a.post("/api/letters", {"level": 1})["letter"]
    a.post(f"/api/letters/{lid}/send", {"text": "two blocks"})
    bid = b.post(f"/api/letters/{lid}/builds")["build"]
    b.post(f"/api/builds/{bid}/place", SHAPE)
    return lid, bid


def says_it_all(msg: str):
    assert "61 words" in msg and "at most 60" in msg and "nothing has been submitted yet" in msg, msg
    assert 'From word 61 on it reads "word60"' in msg, msg


def test_long_note_by_api(server):
    base, app = server
    a, b = Client.new(base, "alice"), Client.new(base, "bob")
    lid, bid = letter_build(base, a, b)
    r = b.post(f"/api/builds/{bid}/submit", {"note": LONG}, expect=422)
    says_it_all(r["error"])
    assert r["submitted"] is False and r["note_words"] == 61 and r["note_limit"] == 60 and r["note"] == LONG
    st = b.get(f"/api/builds/{bid}")
    assert st["status"] == "building" and st["count"] == 1
    assert b.post(f"/api/builds/{bid}/submit", {"note": ["a list"]}, expect=422)["error"].startswith("The note is text")
    long_chars = "x" * 2001
    assert "2,001 characters" in b.post(f"/api/builds/{bid}/submit", {"note": long_chars}, expect=422)["error"]
    sixty = " ".join(["fine"] * 60)
    done = b.post(f"/api/builds/{bid}/submit", {"note": sixty})
    assert done["status"] == "submitted" and done["result"]["note"] == sixty


def test_long_note_by_fetching(server):
    base, app = server
    a, b = Client.new(base, "alice"), Client.new(base, "bob")
    lid, bid = letter_build(base, a, b)
    page = httpx.get(base + "/play/submit", params={"key": b.key, "build": bid, "go": "yes", "note": LONG}).text
    assert page.startswith("NOT DONE: Your note is 61 words")
    says_it_all(page)
    assert b.get(f"/api/builds/{bid}")["status"] == "building"


def test_long_note_by_web_form_keeps_the_words(server):
    base, app = server
    a, b = Client.new(base, "alice"), Client.new(base, "bob")
    lid, bid = letter_build(base, a, b)
    web = httpx.Client(base_url=base, cookies={"tr_key": b.key}, follow_redirects=False)
    r = web.post(f"/build/{bid}/submit", data={"note": LONG})
    assert r.status_code == 422
    says_it_all(r.text.replace("&#34;", '"').replace("&quot;", '"'))
    assert f">{LONG}</textarea>" in r.text, "the note comes back in the box"
    assert 'data-limit="60"' in r.text and 'id="notecount"' in r.text
    assert b.get(f"/api/builds/{bid}")["status"] == "building"
    r = web.post(f"/build/{bid}/submit", data={"note": "short"})
    assert r.status_code == 303 and b.get(f"/api/builds/{bid}")["status"] == "submitted"

    # a live round's builder, likewise
    m = a.post("/api/matches", {"open": False})["match"]
    b.post(f"/api/matches/{m}/join")      # bob describes round one; alice builds
    a.post(f"/api/builds/{m}/place", SHAPE)
    live = httpx.Client(base_url=base, cookies={"tr_key": a.key}, follow_redirects=False)
    r = live.post(f"/m/{m}/submit", data={"note": LONG})
    assert r.status_code == 422 and f">{LONG}</textarea>" in r.text
    says_it_all(r.text.replace("&#34;", '"').replace("&quot;", '"'))
    assert a.get(f"/api/builds/{m}")["status"] == "building"
