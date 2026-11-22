"""Fill a dev server with plausible play, through the API, so every page has something to show.

    uv run python scratch/seed.py --server http://127.0.0.1:8377 --db /var/tmp/tworooms-dev/dev.sqlite
Builds are the true picture with a few shapes nudged (read from the db), so scores land in the 70-100 range.
"""
import argparse
import json
import random
import sqlite3

import httpx

ap = argparse.ArgumentParser()
ap.add_argument("--server", default="http://127.0.0.1:8377")
ap.add_argument("--db", default="/var/tmp/tworooms-dev/dev.sqlite")
args = ap.parse_args()
rng = random.Random(4)
db = sqlite3.connect(args.db)


def player(name, kind, about=None):
    r = httpx.post(args.server + "/api/players", json={"callsign": name, "kind": kind, "about": about})
    r.raise_for_status()
    return {"name": name, "h": {"Authorization": "Bearer " + r.json()["key"]}}


def call(p, method, path, body=None):
    r = httpx.request(method, args.server + path, headers=p["h"], json=body, timeout=30)
    if r.status_code >= 400:
        raise SystemExit(f"{method} {path}: {r.status_code} {r.text}")
    return r.json()


def shapes_for_letter(lid):
    (pid,) = db.execute("SELECT picture_id FROM letters WHERE id=?", (lid,)).fetchone()
    return json.loads(db.execute("SELECT shapes FROM pictures WHERE id=?", (pid,)).fetchone()[0])


def shapes_for_round(rid):
    (pid,) = db.execute("SELECT picture_id FROM rounds WHERE id=?", (rid,)).fetchone()
    return json.loads(db.execute("SELECT shapes FROM pictures WHERE id=?", (pid,)).fetchone()[0])


def nudge(shapes, amount):
    out = []
    for s in shapes:
        s = json.loads(json.dumps(s))
        if rng.random() < amount:
            d = rng.choice([-0.5, -0.25, 0.25, 0.5])
            if s["shape"] == "rect":
                k = rng.choice(["x", "y"])
                s[k] = min(10 - s["w" if k == "x" else "h"], max(0, s[k] + d))
            elif s["shape"] == "ellipse":
                k = rng.choice(["cx", "cy"])
                r = s["rx" if k == "cx" else "ry"]
                s[k] = min(10 - r, max(r, s[k] + d))
            else:
                p = rng.randrange(3)
                s["points"][p][0] = min(10, max(0, s["points"][p][0] + d))
        if rng.random() > amount / 6:
            out.append(s)
    return out


TEXTS = {
    1: "Two blocks. A red one in the lower left, about a third of the board wide and a fifth tall, its left edge a tenth in. A blue one up on the right, smaller, square, its top a tenth below the top edge.",
    2: "Blocks, none overlapping. Along the bottom, a long yellow bar from the left edge to the middle. Above its right end a black square, a fifth on a side. In the upper left a green block, tall and narrow. On the right edge, a red block half the height of the board.",
    3: "Rectangles lying on each other. A big blue one in the middle, half the board wide. Over its upper left corner a red one, smaller. A yellow bar crosses the blue's bottom edge. A green square sits on the red's right side.",
    5: "A yellow triangle pointing up in the lower left, its base along the bottom edge. A blue circle overlapping its right side. Two red blocks, one at the top left, one at the far right. A green ellipse, wide, in the middle. A black right triangle in the upper right corner.",
    6: "A house. Yellow walls, a bit more than half the board wide, standing on the bottom edge in the middle. A dark red roof, as tall as a third of the walls' width. A black door in the middle, two small blue windows either side. A chimney on the right of the roof.",
    7: "A pile in the middle. Start with a large blue ellipse, a third of the board across, centred. A red triangle points down over its left half. A yellow block covers the ellipse's lower right. A black circle, small, at the top of the pile. Green slivers peek out on the left.",
}

alice = player("alice", "human", "on the porch most evenings")
bob = player("bob", "agent", "Delve Town, thread #two-rooms")
carol = player("carol", "agent")
dmitri = player("dmitri", "human")
eve = player("eve", "agent", "ask me for a live game")
everyone = [alice, bob, carol, dmitri, eve]

# letters: some closed with several builds, some open
for i, (describer, level) in enumerate([(alice, 1), (bob, 2), (carol, 3), (alice, 6), (dmitri, 5), (eve, 7), (bob, 6), (carol, 1)]):
    d = call(describer, "POST", "/api/letters", {"level": level})
    lid = d["letter"]
    call(describer, "POST", f"/api/letters/{lid}/send", {"text": TEXTS.get(level, TEXTS[1])})
    others = [p for p in everyone if p is not describer]
    rng.shuffle(others)
    n_builders = [3, 5, 2, 4, 1, 2, 0, 1][i]
    truth = shapes_for_letter(lid)
    for p in others[:n_builders]:
        try:
            b = call(p, "POST", f"/api/letters/{lid}/builds")
        except SystemExit as e:
            print("skip", e)
            continue
        call(p, "PUT", f"/api/builds/{b['build']}/shapes", nudge(truth, rng.uniform(0.1, 0.7)))
        note = rng.choice([None, None, "You said the blue one was square; at that size it couldn't touch the top.",
                           "The bar's length was the hard part: 'to the middle' could be either side of it."])
        call(p, "POST", f"/api/builds/{b['build']}/submit", {"note": note} if note else {})
    if i in (0, 2, 3, 5):
        st = call(describer, "GET", f"/api/letters/{lid}")
        if st["status"] == "open":
            call(describer, "POST", f"/api/letters/{lid}/close")

# a live match played to the end
m = call(alice, "POST", "/api/matches", {"open": False, "rounds": 3, "level": 2})["match"]
call(eve, "POST", f"/api/matches/{m}/join")
lines = {
    "describer": ["Blocks. A long green bar lies along the top edge, from the left to a bit past the middle.",
                  "Below it on the right, a red square, a fifth on a side, and a yellow block under that, touching it.",
                  "Yes: the black one is in the lower left corner, about a quarter of the board wide."],
    "builder": ["Is the red square touching the right edge?", "Got it. Where is the last one?"],
}
for rnd in range(3):
    st = call(alice, "GET", f"/api/matches/{m}")
    cur = st["current"]
    d, b = (alice, eve) if cur["describer"] == "alice" else (eve, alice)
    call(d, "POST", f"/api/matches/{m}/say", {"text": lines["describer"][0]})
    call(b, "POST", f"/api/matches/{m}/say", {"text": lines["builder"][0]})
    call(d, "POST", f"/api/matches/{m}/say", {"text": lines["describer"][1]})
    call(b, "POST", f"/api/matches/{m}/say", {"text": lines["builder"][1]})
    call(d, "POST", f"/api/matches/{m}/say", {"text": lines["describer"][2]})
    truth = shapes_for_round(cur["round_id"])
    call(b, "PUT", f"/api/builds/{m}/shapes", nudge(truth, [0.2, 0.5, 0.3][rnd]))
    call(b, "POST", f"/api/builds/{m}/submit", {"note": "The yellow was lower than I thought."} if rnd == 1 else {})

# a match in progress (bob describing to carol), an open seat, an invitation
m2 = call(carol, "POST", "/api/matches", {"open": False, "rounds": 4, "level": 3})["match"]
call(bob, "POST", f"/api/matches/{m2}/join")
call(bob, "POST", f"/api/matches/{m2}/say", {"text": "Rectangles on top of each other: a wide blue one across the middle, half the board wide, a third tall."})
call(carol, "PUT", f"/api/builds/{m2}/shapes", [{"shape": "rect", "color": "blue", "x": 2.5, "y": 3.5, "w": 5, "h": 3.25}])
call(carol, "POST", f"/api/matches/{m2}/say", {"text": "Where does it sit vertically, and what is on top of it?"})
call(dmitri, "POST", "/api/seat", {"level": 1, "rounds": 4})
inv = call(eve, "POST", "/api/matches", {"open": False, "rounds": 2, "level": 4})
# drafts and a build in progress for alice
dr = call(alice, "POST", "/api/letters", {"level": 4})
open_letters = call(alice, "GET", "/api/letters")["letters"]
if open_letters:
    call(alice, "POST", f"/api/letters/{open_letters[0]['letter']}/builds")
keys = {p["name"]: p["h"]["Authorization"][7:] for p in everyone}
print(json.dumps({"keys": keys, "live_finished": m, "live_playing": m2, "invite": inv["match"], "draft": dr["letter"]}, indent=1))
