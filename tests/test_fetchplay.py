"""Playing with GET requests only, as an agent whose one tool fetches addresses."""
import re
import threading
import time
import urllib.parse

import httpx

from tworooms import db as D

from .conftest import serve


def get(base, path, **params):
    r = httpx.get(base + path, params=params, timeout=70)
    assert r.status_code == 200, (path, r.status_code, r.text)
    return r


def txt(base, path, **params) -> str:
    r = get(base, path, **params)
    assert r.headers["content-type"].startswith("text/plain") and r.headers["cache-control"] == "no-store"
    return r.text


def key_of(page: str) -> str:
    return re.search(r"Your key is:\n\s+(\S+)", page).group(1)


def test_letters_game_by_fetching(server):
    base, app = server
    a = key_of(txt(base, "/play/register", callsign="fetcher-a", kind="agent"))
    b = key_of(txt(base, "/play/register", callsign="fetcher-b"))
    page = txt(base, "/play/describe", key=a, level=1)
    lid = re.search(r"Letter (\w+):", page).group(1)
    assert f"/play/picture.png?key={a}&letter={lid}" in page and "budget: 25 words" in page
    assert get(base, "/play/picture.png", key=a, letter=lid).headers["content-type"] == "image/png"
    assert "NOT DONE" in txt(base, "/play/picture.png", key=b, letter=lid)
    assert "Would be refused" in txt(base, "/play/words", text="eleven blocks")
    assert "would be accepted" in txt(base, "/play/words", text="two blocks", budget=25)
    assert txt(base, "/play/send", key=a, letter=lid, text="It is 3 wide").startswith("NOT DONE: it contains the digit")
    words = "Two blocks. Red, low on the left; blue, high on the right."
    assert f"Letter {lid} is open" in txt(base, "/play/send", key=a, letter=lid, text=words)
    assert "already sent with these words" in txt(base, "/play/send", key=a, letter=lid, text=words)

    page = txt(base, "/play/letters", key=b)
    assert words in page and f"/play/take?key={b}&letter={lid}&go=yes" in page
    page = txt(base, "/play/take", key=b, letter=lid, go="yes")
    bid = re.search(r"Build (\w+) of letter", page).group(1)
    assert words in page
    page = txt(base, "/play/board", key=b, build=bid, shapes="rect red 1 1 3.3 2, ellipse blue 7 7 1")
    assert "now holds 2 shapes" in page and "rect red 1 1 3.25 2" in page and "Rounded to steps of 1/8" in page
    assert "NOT DONE" in txt(base, "/play/board", key=b, build=bid, shapes="rect pink 1 1 1 1")
    assert app.state.hall.build_state(app.state.hall.player_by_callsign("fetcher-b"), bid)["count"] == 2
    page = txt(base, "/play/check", key=b, build=bid, go="yes")
    assert "Check 1 of 2" in page and "direction:" in page and "Moving the whole board leaves slid to fit the same" in page
    assert get(base, "/play/board.png", key=b, build=bid).headers["content-type"] == "image/png"
    page = txt(base, "/play/submit", key=b, build=bid, go="yes", note="the blue one was a guess")
    assert "in place:" in page and "slid to fit:" in page and "Every board, side by side" in page
    assert "already submitted" in txt(base, "/play/submit", key=b, build=bid, go="yes")
    links = re.findall(r"(http://\S+\.png\S*)", page)
    assert len(links) == 2 and all(httpx.get(u).headers["content-type"] == "image/png" for u in links), links
    page = txt(base, "/play/letter", key=a, letter=lid)
    assert "fetcher-b:" in page and "the blue one was a guess" in page and "check 1:" in page
    assert "fetcher-a" in txt(base, "/play/me", key=a)
    assert "Open seats you could take" in txt(base, "/play/hall", key=a)


def test_nothing_happens_without_the_parameters(server):
    base, app = server
    hall = app.state.hall
    a = key_of(txt(base, "/play/register", callsign="carefulone"))
    for path in ("/play/register", "/play/describe", "/play/send", "/play/take", "/play/board", "/play/check",
                 "/play/submit", "/play/seat", "/play/invite", "/play/join", "/play/say", "/play/close"):
        page = txt(base, path)
        assert page.startswith(("Nothing was done", "This address needs your key")), (path, page)
    assert txt(base, "/play/describe", key=a).startswith("Nothing was done")
    lid = hall.create_letter(hall.player_by_callsign("carefulone"), 1)["letter"]
    hall.send_letter(hall.player_by_callsign("carefulone"), lid, "two blocks")
    b = key_of(txt(base, "/play/register", callsign="carefultwo"))
    assert txt(base, "/play/take", key=b, letter=lid).startswith("Nothing was done: add go=yes")
    assert hall.letter_view(None, lid)["builds_in_progress"] == 0
    assert txt(base, "/play/seat", key=b).startswith("Nothing was done")
    assert hall.one("SELECT COUNT(*) AS n FROM matches")["n"] == 0
    assert hall.one("SELECT COUNT(*) AS n FROM players")["n"] == 2
    assert "nothing at this address" in httpx.get(base + "/play/nonsense").text
    assert "/play/register?callsign=NAME" in txt(base, "/play")


def test_live_match_by_fetching(server):
    base, app = server
    a = key_of(txt(base, "/play/register", callsign="live-a"))
    b = key_of(txt(base, "/play/register", callsign="live-b"))
    page = txt(base, "/play/invite", key=a, go="yes", rounds=1)
    mid = re.search(r"Match (\w+) is waiting", page).group(1)
    page = txt(base, "/play/join", key=b, match=mid, go="yes")
    assert "You are the describer" in page and f"/play/look.png?key={b}&match={mid}" in page
    assert get(base, "/play/look.png", key=b, match=mid).headers["content-type"] == "image/png"
    got = {}

    def wait():
        t = time.time()
        got["page"] = txt(base, "/play/match", key=a, match=mid, wait=20)
        got["t"] = time.time() - t

    th = threading.Thread(target=wait)
    th.start()
    time.sleep(0.5)
    assert txt(base, "/play/say", key=b, match=mid, text="One red block, low on the left.").startswith("Sent.")
    th.join()
    assert got["t"] < 10 and "live-b (describer, 7 words): One red block" in got["page"]
    assert "not sent twice" in txt(base, "/play/say", key=b, match=mid, text="One red block, low on the left.")
    assert "Checks are for letters" in txt(base, "/play/check", key=a, build=mid, go="yes")
    txt(base, "/play/say", key=a, match=mid, text="How wide?")
    assert "live-a asked" in txt(base, "/play/match", key=b, match=mid)
    assert "now holds 1 shape" in txt(base, "/play/board", key=a, build=mid, shapes="rect red 0 0 3 2")
    page = txt(base, "/play/submit", key=a, build=mid, go="yes")
    assert "in place:" in page and "The match:" in page
    assert "finished" in txt(base, "/play/match", key=b, match=mid)


def test_fetching_keeps_the_same_limits(tmp_path):
    with serve(tmp_path, rate_limits=True) as (base, app):
        pages = [httpx.get(base + "/play/register", params={"callsign": f"f{i}"}).text for i in range(31)]
        assert all("Your key is" in p for p in pages[:30]) and pages[30].startswith("NOT DONE: Too many")
