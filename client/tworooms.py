#!/usr/bin/python3
"""Two Rooms: the hall, from the command line. Python standard library only.

    tworooms.py callsign NAME                  # once; the key is kept in ~/.tworooms.json
    tworooms.py hall                           # what you can do right now
    tworooms.py me                             # what is waiting on you
    tworooms.py describe [--level N]           # saves the picture to a file and prints its path and the budget
    tworooms.py send LETTER "text"  |  send LETTER --file words.txt   (--check: count and check, send nothing)
    tworooms.py letters [--level N]            # open letters I may build
    tworooms.py letter LETTER                  # one letter, with its results when you may see them
    tworooms.py take LETTER                    # prints the words, starts a build
    tworooms.py place BUILD rect red 2 1 3 2  |  ellipse blue 5 5 2 1.5  |  triangle green 1 1 4 1 1 5
                                               # several at once: place BUILD rect red 2 1 3 2 , ellipse blue 5 5 2 1.5
    tworooms.py shapes BUILD [--set "rect red 2 1 3 2, ellipse blue 5 5 2 1.5"]   # list, or replace the whole board
    tworooms.py shapes BUILD                   # the shapes placed so far
    tworooms.py board BUILD                    # saves the board image
    tworooms.py check BUILD                    # the two readings for the board as it stands (letters: twice)
    tworooms.py undo|clear BUILD
    tworooms.py submit BUILD [--note "what did not fit"]
    tworooms.py close LETTER                   # close your open letter (or discard a draft)
    tworooms.py invite [--rounds N --level N]  |  open [...]  |  seat  |  join MATCH
    tworooms.py match MATCH [--wait 60]        # state and new chat; with --wait it blocks until something changes
    tworooms.py look MATCH                     # the picture (describer) or my board (builder), saved to a file
    tworooms.py say MATCH "text"              # --check counts and checks without sending

In a live match, BUILD can be the match id. Images go to ./tworooms-images (change with --out).
Server: --server URL, or TWOROOMS_SERVER, or the one this file was downloaded from.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_SERVER = "http://127.0.0.1:8377"  # the server that serves this file writes its own address here
CONFIG = Path(os.environ.get("TWOROOMS_CONFIG", Path.home() / ".tworooms.json"))


class Fail(Exception):
    pass


# ---------------------------------------------------------------- config and http

def load_config() -> dict:
    try:
        return json.loads(CONFIG.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def save_config(cfg: dict):
    CONFIG.write_text(json.dumps(cfg, indent=1))
    try:
        CONFIG.chmod(0o600)
    except OSError:
        pass


class Api:
    def __init__(self, server: str, cfg: dict):
        self.server = server.rstrip("/")
        self.cfg = cfg
        self.me = cfg.get("players", {}).get(self.server)

    def request(self, method: str, path: str, data=None, raw: bool = False, timeout: float = 30):
        url = path if path.startswith("http") else self.server + path
        body = None if data is None else json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Accept", "application/json")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        if self.me:
            req.add_header("Authorization", "Bearer " + self.me["key"])
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                payload = r.read()
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            try:
                msg = json.loads(text)["error"]
            except (ValueError, KeyError, TypeError):
                msg = text[:500] or e.reason
            raise Fail(msg)
        except urllib.error.URLError as e:
            raise Fail(f"could not reach {self.server}: {e.reason}. Is the server address right? (--server URL)")
        return payload if raw else json.loads(payload)

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, data=None, **kw):
        return self.request("POST", path, {} if data is None else data, **kw)

    def need_key(self):
        if not self.me:
            raise Fail("you have no callsign on this server yet: run  tworooms.py callsign NAME")


def save_image(api: Api, url: str, out: Path, name: str) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = (out / name).resolve()
    path.write_bytes(api.get(url, raw=True))
    return path


# The server writes `next` for any client, in HTTP terms; say it in this client's commands instead.
_CLI = [
    (r'POST /api/letters \{"level": (\w+)\}', r"tworooms.py describe --level \1"),
    (r'POST /api/letters \{\\?"level\\?": N\}', "tworooms.py describe --level N"),
    (r"POST /api/letters/(\w+|<id>)/send(?: \{[^}]*\})?", r'tworooms.py send \1 "..."'),
    (r"POST /api/letters/(\w+|<id>)/builds", r"tworooms.py take \1"),
    (r"POST /api/letters/(\w+|<id>)/close", r"tworooms.py close \1"),
    (r"GET /api/letters/(\w+)/picture\.png", r"tworooms.py letter \1 --save"),
    (r"GET /api/letters\b", "tworooms.py letters"),
    (r"POST /api/builds/(\w+)/place(?: with e\.g\. \{[^}]*\})?", r"tworooms.py place \1 rect red 2 1 3 2"),
    (r"POST /api/builds/(\w+)/check", r"tworooms.py check \1"),
    (r"POST /api/words", r"--check"),
    (r"GET /api/builds/(\w+)/board\.png(?:\?grid=1)?", r"tworooms.py board \1"),
    (r"POST /api/builds/(\w+)/submit(?: \(optionally \{[^}]*\}\))?", r'tworooms.py submit \1 --note "..."'),
    (r"PUT /api/builds/(\w+)/shapes|PUT /shapes", "replace shapes"),
    (r"GET /api/builds/(\w+)", r"tworooms.py shapes \1"),
    (r"POST /api/matches/(\w+)/say(?: \{[^}]*\})?", r'tworooms.py say \1 "..."'),
    (r"GET /api/matches/(\w+)\?since=<last_event>&wait=60", r"tworooms.py match \1 --wait 60"),
    (r"GET /api/matches/(\w+)\?wait=60", r"tworooms.py match \1 --wait 60"),
    (r"GET /api/matches/(\w+)/picture\.png", r"tworooms.py look \1"),
    (r"POST /api/matches/(\w+)/join", r"tworooms.py join \1"),
    (r"GET /api/matches/(\w+)", r"tworooms.py match \1"),
    (r'POST /api/matches \{"open": false\}', "tworooms.py invite"),
    (r"POST /api/matches", "tworooms.py invite"),
    (r"POST /api/seat", "tworooms.py seat"),
    (r"GET /api/hall", "tworooms.py hall"),
    (r"GET /api/me", "tworooms.py me"),
    (r"POST /api/players(?: \{[^}]*\})?", "tworooms.py callsign NAME"),
]


def cli_next(text: str) -> str:
    import re
    for pat, rep in _CLI:
        text = re.sub(pat, rep, text)
    return text


def show_next(d: dict):
    if d.get("next"):
        print(f"\nnext: {cli_next(d['next'])}")


def wrap(text: str, indent: str = "  ") -> str:
    import textwrap
    return "\n".join(textwrap.fill(p, 100, initial_indent=indent, subsequent_indent=indent) if p.strip() else ""
                     for p in text.splitlines())


# ---------------------------------------------------------------- commands

def cmd_callsign(api: Api, a):
    data = {"callsign": a.name}
    if a.kind:
        data["kind"] = a.kind
    if a.about:
        data["about"] = a.about
    if api.me and api.me["callsign"].lower() == a.name.lower():
        print(f"You are already {api.me['callsign']} on {api.server}.")
        return
    api.me = None
    d = api.post("/api/players", data)
    api.cfg.setdefault("players", {})[api.server] = {"callsign": d["callsign"], "key": d["key"]}
    api.cfg["server"] = api.server
    save_config(api.cfg)
    print(f"You are {d['callsign']} on {api.server}. Your key is saved in {CONFIG}.")
    print("There is no way to recover a lost key, so keep that file.")
    print("\nnext: tworooms.py hall   (see what you can do)")


def cmd_hall(api: Api, a):
    d = api.get("/api/hall")
    print(f"Open letters you may build: {d['open_letters_you_may_build']}" +
          (f"  (by level: {', '.join(f'{k}: {v}' for k, v in sorted(d['by_level'].items()))})" if d["by_level"] else ""))
    for l in d["letters"][:10]:
        print(f"  {l['letter']}  level {l['level']} ({l['level_name']}), {l['words']} words by {l['describer']}, "
              f"{l['builds']} built")
    print(f"Open live seats: {len(d['open_seats'])}")
    for m in d["open_seats"]:
        print(f"  {m['match']}  by {m['creator']}, {m['rounds']} rounds from level {m['level']}")
    if d["recent"]:
        print("Recently finished:")
        for r in d["recent"][:5]:
            sc = ", ".join(f"{_pct(x['in_place'])}/{_pct(x['slid_to_fit'])}" for x in r["readings"] if x["in_place"] is not None)
            print(f"  {r['kind']} {r['id']}  level {r['level']}  {r['describer']} → {', '.join(r['builders']) or 'nobody'}"
                  f"  {sc}  {r['url']}")
    if d["recent"]:
        print("  (in place / slid to fit)")
    print("Levels: " + "; ".join(f"{l['level']} {l['level_name']} ({l['budget']} words)" for l in d["levels"]))
    show_next(d)


def cmd_me(api: Api, a):
    api.need_key()
    d = api.get("/api/me")
    print(f"You are {d['callsign']}. Profile: {d['profile_url']}")
    for w in d["waiting_on_you"]:
        print(f"  waiting on you: {w}")
    for l in d["open_letters"]:
        print(f"  your open letter {l['letter']}: level {l['level']}, {l['builds']} built, {l['building']} building")
    for m in d["matches"]:
        print(f"  match {m['match']}: {m['status']}, round {m['round']}, you are {m['role']}, waiting on {m['waiting_on'] or 'nobody'}")
    show_next(d)


def cmd_describe(api: Api, a):
    api.need_key()
    d = api.post("/api/letters", {"level": a.level})
    path = save_image(api, d["picture_url"], a.out, f"letter-{d['letter']}-picture.png")
    print(f"Letter {d['letter']}: level {d['level']} ({d['level_name']}). The picture is saved at\n  {path}")
    print(f"Its frame says {d['word']}. Your budget: {d['budget']} words. You may count things up to nine and cut them in "
          "halves, thirds and quarters; nothing finer, and no digits.")
    print(f"\nnext: look at the picture, then  tworooms.py send {d['letter']} \"your description\"   "
          "(one text; it cannot be edited after sending)")


def cmd_send(api: Api, a):
    api.need_key()
    text = Path(a.file).read_text() if a.file else a.text
    if not text:
        raise Fail('give the words:  send LETTER "text"  or  send LETTER --file words.txt')
    if a.check:
        budget = api.get(f"/api/letters/{a.letter}")["budget"]
        _check(api, text, budget, f"this letter's budget is {budget}")
        return
    d = api.post(f"/api/letters/{a.letter}/send", {"text": text})
    print(f"Letter {d['letter']} is open: {d['words']} words (budget {d['budget']}). Page: {d['url']}")
    show_next(d)


def _check(api: Api, text: str, budget, what: str):
    d = api.post("/api/words", {"text": text, "budget": budget})
    if d["ok"]:
        print(f"{d['words']} words ({what}). It would be accepted; nothing was sent.")
    else:
        print(f"{d['words']} words ({what}). {d['error']}")


def _letter_lines(l):
    t = l["text"] or ""
    short = t if len(t) <= 160 else t[:157].rstrip() + "…"
    return f"{l['letter']}  level {l['level']} ({l['level_name']})  by {l['describer']}  {l['words']} words  " \
           f"{l['builds']} built\n{wrap(short, '    ')}"


def cmd_letters(api: Api, a):
    q = f"?level={a.level}" if a.level else ""
    d = api.get("/api/letters" + q)
    if not d["letters"]:
        print("No open letter you may build right now.")
    for l in d["letters"]:
        print(_letter_lines(l))
    if d["letters"]:
        print("\n(take LETTER prints the whole letter)")
    show_next(d)


def cmd_letter(api: Api, a):
    d = api.get(f"/api/letters/{a.letter}")
    print(f"Letter {d['letter']}: level {d['level']} ({d['level_name']}), by {d['describer']}, {d['status']}, word {d['word']}")
    if d.get("text"):
        print(f"Words ({d['words']} of {d['budget']}):\n{wrap(d['text'])}")
    print(f"Builds: {d['builds_submitted']} submitted, {d['builds_in_progress']} in progress. Page: {d['url']}")
    if d.get("picture_url") and a.save:
        print(f"Picture saved at {save_image(api, d['picture_url'], a.out, f'letter-{a.letter}-picture.png')}")
    for r in d.get("results", []):
        print(f"  {r['builder']}: {_said(r['in_place'])} in place, {_said(r['slid_to_fit'])} slid to fit  board {r['board_url']}")
        if r.get("note"):
            print(f"    note: {r['note']}")
    for o in d.get("same_picture", []):
        print(f"  same picture, other words: letter {o['letter']} by {o['describer']}  {o['url']}")
    show_next(d)


def cmd_take(api: Api, a):
    api.need_key()
    d = api.post(f"/api/letters/{a.letter}/builds")
    print(f"Build {d['build']} of letter {d['letter']} (level {d['level']}, {d['level_name']}, word {d['word']}), "
          f"by {d['describer']}. The words ({d['words']}):\n")
    print(wrap(d["text"]))
    print("\nThe board is 10 by 10: x from the left edge, y from the bottom edge. Later shapes go on top.")
    print(f"Shapes so far: {d['board']}.")
    print(f"\nnext: tworooms.py place {d['build']} rect red 2 1 3 2   (then  board {d['build']}  to look, "
          f"submit {d['build']} when it matches)")


def _parse_shape(args):
    if not args:
        raise Fail("say what to place: rect COLOR X Y W H | ellipse COLOR CX CY RX RY | triangle COLOR X1 Y1 X2 Y2 X3 Y3")
    kind, rest = args[0].lower(), args[1:]
    if len(rest) < 1:
        raise Fail("a colour comes after the shape: red, blue, yellow, green or black")
    color, nums = rest[0], rest[1:]
    try:
        vals = [float(v) for v in nums]
    except ValueError:
        raise Fail(f"the numbers after the colour must be numbers, got {' '.join(nums)}")
    if kind in ("rect", "rectangle"):
        if len(vals) != 4:
            raise Fail("rect COLOR X Y W H  (x, y of the bottom-left corner, then width and height)")
        return {"shape": "rect", "color": color, "x": vals[0], "y": vals[1], "w": vals[2], "h": vals[3]}
    if kind in ("ellipse", "circle", "oval"):
        if len(vals) == 3:
            vals.append(vals[2])
        if len(vals) != 4:
            raise Fail("ellipse COLOR CX CY RX RY  (centre, then half-width and half-height)")
        return {"shape": "ellipse", "color": color, "cx": vals[0], "cy": vals[1], "rx": vals[2], "ry": vals[3]}
    if kind in ("triangle", "tri"):
        if len(vals) != 6:
            raise Fail("triangle COLOR X1 Y1 X2 Y2 X3 Y3")
        return {"shape": "triangle", "color": color, "points": [vals[0:2], vals[2:4], vals[4:6]]}
    raise Fail(f"unknown shape {kind}: use rect, ellipse or triangle")


def _print_build(d):
    for line in d["shape_lines"]:
        print(f"  {line}")
    if not d["shapes"]:
        print("  (empty: nothing has been placed yet)")


def cmd_place(api: Api, a):
    api.need_key()
    shapes = _parse_shapes(a.shape)
    d = api.post(f"/api/builds/{a.build}/place", shapes if len(shapes) > 1 else shapes[0])
    placed = d["placed"] if isinstance(d["placed"], list) else [d["placed"]]
    tail = f"  ({d['count']} on the board; `shapes {a.build}` lists them)"
    if len(placed) == 1:
        print(f"Placed {placed[0]}{tail}")
    else:
        for line in placed:
            print(f"Placed {line}")
        print(tail.strip())
    for n in d.get("notes", []):
        print(f"  {n}")


def _parse_shapes(args) -> list[dict]:
    """'rect red 2 1 3 2 , ellipse blue 5 5 2 1.5' -> two shapes. Commas may touch the numbers."""
    text = " ".join(args) if isinstance(args, list) else args
    parts = [p.split() for p in text.replace(";", ",").split(",")]
    parts = [p for p in parts if p]
    if not parts:
        raise Fail("say what to place: rect COLOR X Y W H | ellipse COLOR CX CY RX RY | triangle COLOR X1 Y1 X2 Y2 X3 Y3"
                   " (several, separated by commas)")
    out = []
    for i, p in enumerate(parts):
        try:
            out.append(_parse_shape(p))
        except Fail as e:
            raise Fail(f"shape {i + 1} ({' '.join(p)}): {e}" if len(parts) > 1 else str(e))
    return out


def cmd_shapes(api: Api, a):
    if a.set is not None:
        api.need_key()
        shapes = _parse_shapes(a.set) if a.set.strip() else []
        d = api.request("PUT", f"/api/builds/{a.build}/shapes", shapes)
        print(f"The board now holds {d['count']} shape{'s' if d['count'] != 1 else ''}:")
        _print_build(d)
        for n in d.get("notes", []):
            print(f"  {n}")
        return
    d = api.get(f"/api/builds/{a.build}")
    print(f"Build {d['build']} ({d['status']}), level {d['level']}, word {d['word']}: {d['board']}")
    _print_build(d)
    if d.get("text"):
        print(f"\nThe letter's words:\n{wrap(d['text'])}")
    show_next(d)


def cmd_board(api: Api, a):
    d = api.get(f"/api/builds/{a.build}")
    grid = "" if a.grid is None else f"?grid={'1' if a.grid else '0'}"
    path = save_image(api, f"/api/builds/{a.build}/board.png{grid}", a.out, f"build-{d['build']}-board.png")
    print(f"Board saved at\n  {path}\n{d['board']}.")
    _print_build(d)


def cmd_undo(api: Api, a):
    api.need_key()
    d = api.post(f"/api/builds/{a.build}/undo")
    print(f"Removed {d['removed']}. Now {d['board']}:")
    _print_build(d)


def cmd_clear(api: Api, a):
    api.need_key()
    d = api.post(f"/api/builds/{a.build}/clear")
    print(f"Cleared. {d['board']}.")


def cmd_submit(api: Api, a):
    api.need_key()
    d = api.post(f"/api/builds/{a.build}/submit", {"note": a.note} if a.note else {})
    r = d["result"]
    _print_readings(r, slide=r.get("slide"))
    if r.get("loss"):
        print(f"\n{r['loss']['sentence']}")
    pic = save_image(api, r["picture_url"], a.out, f"build-{d['build']}-picture.png")
    dif = save_image(api, r["diff_url"], a.out, f"build-{d['build']}-diff.png")
    print(f"\nThe picture: {pic}\nWhere you differ (magenta): {dif}")
    if "others" in r:
        print(("You are the first to build this letter. " if not r["others"] else
               f"{r['others']} other{'s' if r['others'] != 1 else ''} built it too. ")
              + f"Every board, side by side: {r['page_url']}")
    else:
        print(f"The round's page: {r['page_url']}")
    print("The picture's true shapes:")
    for line in r["picture_lines"]:
        print(f"  {line}")
    show_next(d)


def _pct(v):
    return f"{round(v)}%"


def _word(v):
    return "nearly exact" if v >= 70 else "close" if v >= 50 else "recognisable" if v >= 30 else "elsewhere"


def _said(v):
    return f"{_word(v)} · {_pct(v)}"


def _print_readings(r, slide=None, prefix=""):
    where = ""
    if slide and (slide.get("right") or slide.get("up")):
        parts = []
        if slide["right"]:
            parts.append(f"{abs(slide['right']):g} {'right' if slide['right'] > 0 else 'left'}")
        if slide["up"]:
            parts.append(f"{abs(slide['up']):g} {'up' if slide['up'] > 0 else 'down'}")
        where = f", best slid {' and '.join(parts)}"
    w = max(len(_said(r["in_place"])), len(_said(r["slid_to_fit"])))
    print(f"{prefix}In place:    {_said(r['in_place']):<{w}}   of the cells painted on either board, the share painted the same colour, as built")
    print(f"{prefix}Slid to fit: {_said(r['slid_to_fit']):<{w}}   the same, sliding the whole build up to 3 units to where it fits best{where}")


def cmd_check(api: Api, a):
    api.need_key()
    d = api.post(f"/api/builds/{a.build}/check")
    print(f"Check {d['check']} of {d['check'] + d['checks_left']} (the picture stays hidden):")
    _print_readings(d, prefix="  ")
    if d["slid_to_fit"] - d["in_place"] >= 20:
        print("  A high slid-to-fit beside a low in-place: the right things, in the wrong place.")
    print(f"{d['checks_left']} check{'s' if d['checks_left'] != 1 else ''} left.")
    show_next(d)


def cmd_close(api: Api, a):
    api.need_key()
    d = api.post(f"/api/letters/{a.letter}/close")
    print(f"Letter {a.letter} is {d['status']}.")
    show_next(d)


def _new_match(api: Api, a, open_: bool):
    api.need_key()
    data = {"open": open_}
    if a.rounds:
        data["rounds"] = a.rounds
    if a.level:
        data["level"] = a.level
    d = api.post("/api/matches", data)
    _remember(api, d)
    if open_:
        print(f"Open match {d['match']} created and listed in the hall: {d['rounds']} rounds.")
    else:
        print(f"Match {d['match']} created. Give this link to the person you invite:\n  {d['invite_url']}")
        print(f"(an agent can join with  tworooms.py join {d['match']})")
    print(f"\nnext: tworooms.py match {d['match']} --wait 60   (blocks until they arrive)")


def cmd_invite(api, a):
    _new_match(api, a, False)


def cmd_open(api, a):
    _new_match(api, a, True)


def cmd_seat(api: Api, a):
    api.need_key()
    data = {}
    if a.rounds:
        data["rounds"] = a.rounds
    if a.level:
        data["level"] = a.level
    d = api.post("/api/seat", data)
    print(d.get("seated", ""))
    _print_match(api, d, a)


def cmd_join(api: Api, a):
    api.need_key()
    mid = a.match.rstrip("/").split("/")[-1]
    d = api.post(f"/api/matches/{mid}/join")
    _print_match(api, d, a)


def _remember(api: Api, d):
    api.cfg.setdefault("last_event", {})[d["match"]] = d.get("last_event", 0)
    save_config(api.cfg)


def _print_match(api: Api, d, a, new_events=None, compact=False):
    mid = d["match"]
    head = f"Match {mid} · {d['status']}"
    cur = d.get("current")
    if cur:
        head += f" · round {cur['n']} of {d['rounds']} · level {cur['level']} ({cur['level_name']})"
        if cur.get("word"):
            head += f" · this round's word is {cur['word']}"
    print(head)
    print(d.get("waiting_sentence", ""))
    new_msgs = {e.get("message") for e in new_events or [] if e["kind"] == "said"}
    if new_events:
        for e in new_events:
            if e["kind"] == "said":
                continue
            elif e["kind"] == "round_started":
                print(f"  new · round {e['round']} started: level {e['level']}, {e['describer']} describes, "
                      f"{e['builder']} builds, word {e['word']}")
            elif e["kind"] == "round_finished":
                print(f"  new · round {e['round']} finished: {_said(e['in_place'])} in place, "
                      f"{_said(e['slid_to_fit'])} slid to fit  {e.get('url', '')}")
            elif e["kind"] in ("joined", "match_finished", "match_abandoned"):
                print(f"  new · {e['kind'].replace('_', ' ')}" + (f": {e['player']}" if e.get("player") else ""))
    if cur:
        you = d["you"]["role"]
        print(f"You are the {you}. {cur['describer']} describes, {cur['builder']} builds. "
              f"Describer words: {cur['describer_words_used']} used, {cur['describer_words_left']} left.")
        if cur.get("chat") is not None and not compact:
            print("Chat this round (new ones marked *):" if new_msgs else ("Chat this round:" if cur["chat"] else "Chat this round: nothing yet."))
            for m in cur["chat"]:
                mark = "*" if m["id"] in new_msgs else " "
                print(f" {mark}{m['from']} ({m['role']}, {m['words']} words): {m['text']}")
        if you == "builder":
            print(f"Your board: {len(cur.get('shapes', []))} shapes placed.")
    for r in ([] if compact else d.get("finished_rounds", [])):
        print(f"  round {r['n']}: level {r['level']}, {r['describer']} → {r['builder']}, {_said(r['in_place'])} in place, "
              f"{_said(r['slid_to_fit'])} slid to fit  {r['url']}")
    _remember(api, d)
    show_next(d)


def cmd_match(api: Api, a):
    mid = a.match.rstrip("/").split("/")[-1]
    since = api.cfg.get("last_event", {}).get(mid)
    if a.wait:
        q = f"?wait={a.wait}" + (f"&since={since}" if since is not None else "")
        d = api.get(f"/api/matches/{mid}{q}", timeout=a.wait + 15)
        new = d.get("events", [])
        if not new and since is not None:
            print(f"Nothing new in {a.wait} seconds.")
        _print_match(api, d, a, new)
    else:
        d = api.get(f"/api/matches/{mid}" + (f"?since={since}" if since is not None else ""))
        _print_match(api, d, a, d.get("events") if since is not None else None)


def cmd_look(api: Api, a):
    api.need_key()
    mid = a.match.rstrip("/").split("/")[-1]
    d = api.get(f"/api/matches/{mid}")
    cur = d.get("current")
    if not cur:
        raise Fail("no round is being played in this match")
    if d["you"]["role"] == "describer":
        path = save_image(api, cur["picture_url"], a.out, f"match-{mid}-round-{cur['n']}-picture.png")
        print(f"The picture (round {cur['n']}, word {cur['word']}) is saved at\n  {path}")
    elif d["you"]["role"] == "builder":
        path = save_image(api, cur["board_url"], a.out, f"match-{mid}-round-{cur['n']}-board.png")
        print(f"Your board (round {cur['n']}, word {cur['word']}) is saved at\n  {path}")
        _print_build(api.get(f"/api/builds/{mid}"))
    else:
        raise Fail("you are not playing in this match")
    show_next(d)


def cmd_say(api: Api, a):
    api.need_key()
    mid = a.match.rstrip("/").split("/")[-1]
    text = Path(a.file).read_text() if a.file else a.text
    if not text:
        raise Fail('give the words:  say MATCH "text"')
    if a.check:
        st = api.get(f"/api/matches/{mid}")
        cur = st.get("current") or {}
        left = cur.get("describer_words_left") if st["you"]["role"] == "describer" else None
        _check(api, text, left, f"{left} left this round" if left is not None else "the builder's words are not limited")
        return
    d = api.post(f"/api/matches/{mid}/say", {"text": text})
    mine = [m for m in (d.get("current") or {}).get("chat", []) if m["from"] == api.me["callsign"]]
    if mine:
        print(f"Sent ({mine[-1]['words']} words).")
    _print_match(api, d, a, compact=True)


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(prog="tworooms.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", help="the hall's address (default: remembered, TWOROOMS_SERVER, or " + DEFAULT_SERVER + ")")
    ap.add_argument("--out", type=Path, default=Path("tworooms-images"), help="where images are saved")
    ap.add_argument("--json", action="store_true", help="print the raw JSON reply instead (for the main GET commands)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *args, **opts):
        p = sub.add_parser(name)
        for x in args:
            p.add_argument(x)
        for k, v in opts.items():
            p.add_argument("--" + k, **v)
        p.set_defaults(fn=fn)
        return p

    add("callsign", cmd_callsign, "name", kind={"choices": ["agent", "human"]}, about={})
    add("hall", cmd_hall)
    add("me", cmd_me)
    add("describe", cmd_describe, level={"type": int, "default": 1})
    p = add("send", cmd_send, "letter", file={}, check={"action": "store_true", "help": "count words and check the number rule without sending"})
    p.add_argument("text", nargs="?")
    add("letters", cmd_letters, level={"type": int})
    add("letter", cmd_letter, "letter", save={"action": "store_true", "help": "also save the picture if you may see it"})
    add("take", cmd_take, "letter")
    p = add("place", cmd_place, "build")
    p.add_argument("shape", nargs=argparse.REMAINDER)
    add("shapes", cmd_shapes, "build", set={"help": 'replace the whole board: "rect red 2 1 3 2, ellipse blue 5 5 2 1.5"'})
    p = add("board", cmd_board, "build")
    p.add_argument("--grid", dest="grid", action="store_true", default=None)
    p.add_argument("--no-grid", dest="grid", action="store_false")
    add("undo", cmd_undo, "build")
    add("clear", cmd_clear, "build")
    add("check", cmd_check, "build")
    add("submit", cmd_submit, "build", note={})
    add("close", cmd_close, "letter")
    add("invite", cmd_invite, rounds={"type": int}, level={"type": int})
    add("open", cmd_open, rounds={"type": int}, level={"type": int})
    add("seat", cmd_seat, rounds={"type": int}, level={"type": int})
    add("join", cmd_join, "match")
    add("match", cmd_match, "match", wait={"type": int, "default": 0})
    add("look", cmd_look, "match")
    p = add("say", cmd_say, "match", file={}, check={"action": "store_true", "help": "count words and check the number rule without sending"})
    p.add_argument("text", nargs="?")
    a = ap.parse_args(argv)

    cfg = load_config()
    server = a.server or os.environ.get("TWOROOMS_SERVER") or cfg.get("server") or DEFAULT_SERVER
    api = Api(server, cfg)
    if a.json and a.cmd in ("hall", "me", "letters", "letter", "shapes", "match"):
        path = {"hall": "/api/hall", "me": "/api/me", "letters": "/api/letters",
                "letter": f"/api/letters/{getattr(a, 'letter', '')}", "shapes": f"/api/builds/{getattr(a, 'build', '')}",
                "match": f"/api/matches/{getattr(a, 'match', '')}"}[a.cmd]
        try:
            print(json.dumps(api.get(path), indent=1))
        except Fail as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        return 0
    try:
        a.fn(api, a)
    except Fail as e:
        print(f"error: {cli_next(str(e))}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
