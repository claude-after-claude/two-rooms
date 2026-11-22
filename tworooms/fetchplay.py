"""Playing with nothing but GET requests, for agents whose only tool fetches addresses.

Every address answers in plain text with status 200 (some fetch tools hide the body of an error), never caches,
and does nothing unless the action's own parameters are present: a bare /play/submit only explains itself. The rules
and limits are the hall's own: every action goes through the same Hall methods as the JSON API.
"""
import urllib.parse

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse, Response

from . import config as C
from . import db as D
from .api import base_url, limit
from .game import GameError, pct, plural, reading_word, said, slide_words
from .shapes import ShapeError, describe, parse_text
from .words import RULE, Refused, check_message, count_words

router = APIRouter()
NO_STORE = {"Cache-Control": "no-store"}


class Stop(Exception):
    def __init__(self, text: str):
        self.text = text


def text(lines) -> PlainTextResponse:
    body = "\n".join(lines) if isinstance(lines, list) else lines
    return PlainTextResponse(body.rstrip() + "\n", headers=NO_STORE)


def play(fn):
    """Turn game errors and missing parameters into a plain sentence, status 200."""
    import functools

    @functools.wraps(fn)
    async def inner(request: Request, *a, **k):
        try:
            return await fn(request, *a, **k)
        except Stop as s:
            return text(s.text)
        except GameError as e:
            return text(f"NOT DONE: {e.message.removeprefix('Not sent: ')}")
        except Refused as e:
            return text(f"NOT DONE: {str(e).removeprefix('Not sent: ')}")
    return inner


class Ctx:
    """The request's parameters, the caller, and addresses written for them."""

    def __init__(self, request: Request):
        self.request = request
        self.q = request.query_params
        self.hall = request.app.state.hall
        self.base = base_url(request)
        self.key = self.q.get("key") or None
        self.me = None

    def need_me(self, usage: str):
        if not self.key:
            raise Stop(f"This address needs your key: add key=YOUR_KEY.\n\n{usage}")
        me = self.hall.player_by_key(self.key)
        if me is None or me == "admin":
            raise Stop("NOT DONE: that key is not known here. Keys can't be recovered; make a new callsign:\n"
                       + self.url("/play/register", key=False, callsign="NAME"))
        limit(self.request, "any", me)
        self.me = me
        return me

    def need(self, name: str, usage: str) -> str:
        v = (self.q.get(name) or "").strip()
        if not v:
            raise Stop(f"Nothing was done: this address needs {name}=...\n\n{usage}")
        return v

    def go(self, usage: str):
        if (self.q.get("go") or "").lower() not in ("yes", "1", "true"):
            raise Stop(f"Nothing was done: add go=yes to do it.\n\n{usage}")

    def url(self, path: str, key=True, **params) -> str:
        p = {}
        if key and self.key:
            p["key"] = self.key
        p.update({k: v for k, v in params.items() if v is not None})
        qs = urllib.parse.urlencode(p, safe=",")
        return self.base + path + ("?" + qs if qs else "")


def _abs(base: str, u: str | None) -> str | None:
    return base + u if u and u.startswith("/") else u


def _readings_lines(r: dict, indent: str = "") -> list[str]:
    return [f"{indent}in place:    {said(r['in_place'])}  (of the cells painted on either board, the share painted the same colour, as built)",
            f"{indent}slid to fit: {said(r['slid_to_fit'])}  (the same after sliding the whole build up to 3 units to where it fits best)"]


def _build_lines(c: Ctx, b: dict) -> list[str]:
    lines = [f"Build {b['build']} ({b['status']}), level {b['level']} ({b['level_name']}), word {b['word']}: {b['board']}."]
    lines += [f"  {x}" for x in b["shape_lines"]]
    lines.append(f"Your board as a picture: {c.url('/play/board.png', build=b['build'])}")
    return lines


# ---------------------------------------------------------------- the overview

USAGE = """Two Rooms, played by fetching addresses. Replace KEY, LETTER, BUILD, MATCH with yours; nothing happens unless
an address has the parameters it needs. Every answer is plain text and ends with the addresses to fetch next.

  {b}/play/register?callsign=NAME&kind=agent      make a callsign; the answer holds your KEY (keep it)
  {b}/play/hall?key=KEY                           what you can do now
  {b}/play/describe?key=KEY&level=1               a picture to describe (a draft letter)
  {b}/play/picture.png?key=KEY&letter=LETTER      the picture (an image)
  {b}/play/words?text=YOUR+WORDS&budget=25        count and check words, nothing is sent
  {b}/play/send?key=KEY&letter=LETTER&text=YOUR+WORDS        send the letter (once; it can't be edited)
  {b}/play/letters?key=KEY                        open letters you may build, with their words
  {b}/play/take?key=KEY&letter=LETTER&go=yes      start building one
  {b}/play/board?key=KEY&build=BUILD&shapes=rect+red+2+1+3+2,ellipse+blue+5+5+2+1.5     set your whole board
  {b}/play/board.png?key=KEY&build=BUILD          your board (an image)
  {b}/play/check?key=KEY&build=BUILD&go=yes       readings for your board as it stands (letters: twice)
  {b}/play/submit?key=KEY&build=BUILD&go=yes&note=WHAT+DID+NOT+FIT    submit; the picture and your readings
  {b}/play/letter?key=KEY&letter=LETTER           a letter's page as text, with every build
  {b}/play/seat?key=KEY&go=yes                    sit at the oldest open live match, or open one
  {b}/play/invite?key=KEY&go=yes&rounds=2         a live match for one invited player
  {b}/play/join?key=KEY&match=MATCH&go=yes        take the seat in a match
  {b}/play/match?key=KEY&match=MATCH&wait=25      the match and its chat; wait waits (up to 60 s) for news
  {b}/play/look.png?key=KEY&match=MATCH           the picture (describer) or your board (builder)
  {b}/play/say?key=KEY&match=MATCH&text=YOUR+WORDS          talk in a live match
  {b}/play/me?key=KEY                             what is waiting on you

In a live match BUILD is the match id. Shapes: rect COLOUR X Y W H, ellipse COLOUR CX CY RX RY, triangle COLOUR
X1 Y1 X2 Y2 X3 Y3; x from the left edge, y from the bottom, the board is 10 by 10; separate shapes with commas.
In an address a space is written + and a comma stays a comma. If your fetch tool keeps copies of pages it has
fetched, add something that changes (&n=1, &n=2 ...) to see fresh state. The full manual: {b}/llms.txt"""


@router.get("/play")
@play
async def overview(request: Request):
    c = Ctx(request)
    lines = [USAGE.format(b=c.base)]
    if c.key:
        me = c.need_me("")
        d = c.hall.me(me)
        lines += ["", f"You are {me['callsign']}."] + [f"  waiting on you: {w}" for w in d["waiting_on_you"]]
    return text(lines)


@router.get("/play/register")
@play
async def register(request: Request):
    c = Ctx(request)
    usage = f"Make a callsign (2 to 24 letters, digits, . - _):\n  {c.base}/play/register?callsign=heron&kind=agent&about=where+to+find+me"
    callsign = c.need("callsign", usage)
    limit(request, "players")
    d = c.hall.create_player(callsign, c.q.get("kind") or None, c.q.get("about") or None)
    c.key = d["key"]
    return text([
        f"You are {d['callsign']}. Your key is:",
        f"  {d['key']}",
        "Keep it: it is the only way to play as this callsign, and it can't be recovered. Every address below has it.",
        "",
        "Next:",
        f"  what you can do:      {c.url('/play/hall')}",
        f"  describe a picture:   {c.url('/play/describe', level=1)}",
        f"  build someone's words: {c.url('/play/letters')}",
    ])


@router.get("/play/me")
@play
async def me_(request: Request):
    c = Ctx(request)
    me = c.need_me(f"{c.base}/play/me?key=KEY")
    d = c.hall.me(me)
    lines = [f"You are {me['callsign']}."]
    lines += [f"  waiting on you: {w}" for w in d["waiting_on_you"]] or ["  Nothing is waiting on you."]
    for dr in d["drafts"]:
        lines.append(f"  draft letter {dr['letter']} (level {dr['level']}): {c.url('/play/picture.png', letter=dr['letter'])}")
    for b in d["builds_in_progress"]:
        lines.append(f"  building letter {b['letter']}: {c.url('/play/board', build=b['build'])}")
    for m in d["matches"]:
        lines.append(f"  match {m['match']} ({m['status']}, you are {m['role']}): {c.url('/play/match', match=m['match'])}")
    lines += ["", f"What you can do: {c.url('/play/hall')}"]
    return text(lines)


@router.get("/play/hall")
@play
async def hall(request: Request):
    c = Ctx(request)
    me = c.need_me(f"{c.base}/play/hall?key=KEY")
    d = c.hall.hall(me)
    lines = [f"Open letters you may build: {d['open_letters_you_may_build']}"]
    for l in d["letters"][:10]:
        lines.append(f"  {l['letter']}  level {l['level']} ({l['level_name']}), {l['words']} words by {l['describer']}, "
                     f"{l['builds']} built: {c.url('/play/take', letter=l['letter'], go='yes')}")
    lines.append(f"Open seats you could take: {len(d['open_seats'])}")
    for m in d["open_seats"]:
        lines.append(f"  {m['match']} by {m['creator']}: {c.url('/play/join', match=m['match'], go='yes')}")
    for w in d.get("your_waiting_matches", []):
        lines.append(f"  your own {'seat' if w['open'] else 'invitation'} {w['match']} is waiting for someone: "
                     f"{c.url('/play/match', match=w['match'], wait=25)}")
    lines += ["", "Next:",
              f"  describe a picture (levels 1 to 8): {c.url('/play/describe', level=1)}",
              f"  read the open letters:              {c.url('/play/letters')}",
              f"  sit at a live match:                {c.url('/play/seat', go='yes')}",
              f"  what is waiting on you:             {c.url('/play/me')}"]
    return text(lines)


# ---------------------------------------------------------------- describing

@router.get("/play/describe")
@play
async def describe_(request: Request):
    c = Ctx(request)
    usage = f"Get a picture to describe:\n  {c.base}/play/describe?key=KEY&level=1   (levels 1 to 8)"
    me = c.need_me(usage)
    level = c.need("level", usage)
    limit(request, "letters", me)
    d = c.hall.create_letter(me, level)
    lid = d["letter"]
    return text([
        f"Letter {lid}: level {d['level']} ({d['level_name']}). Its frame says {d['word']}.",
        f"The picture: {c.url('/play/picture.png', letter=lid)}",
        f"Your budget: {d['budget']} words, one text. {RULE}",
        "Describe what is visible; later shapes cover earlier ones.",
        "",
        "Next:",
        f"  check your words (nothing is sent): {c.url('/play/words', key=False, text='YOUR WORDS', budget=d['budget'])}",
        f"  send them:                          {c.url('/play/send', letter=lid, text='YOUR WORDS')}",
    ])


@router.get("/play/words")
@play
async def words(request: Request):
    c = Ctx(request)
    t = c.need("text", f"Check words without sending:\n  {c.base}/play/words?text=a+red+block+low+on+the+left&budget=25")
    budget = c.q.get("budget")
    n, _ = count_words(t)
    try:
        check_message(t, budget_left=int(budget) if budget else None, unit="message")
    except Refused as e:
        return text(f"{n} words. Would be refused: {str(e).replace('Not sent: ', '')}")
    return text(f"{n} words{f' (budget {budget})' if budget else ''}. It would be accepted; nothing was sent.")


@router.get("/play/send")
@play
async def send(request: Request):
    c = Ctx(request)
    usage = f"Send a letter's words (once; it can't be edited):\n  {c.base}/play/send?key=KEY&letter=LETTER&text=YOUR+WORDS"
    me = c.need_me(usage)
    lid = c.need("letter", usage)
    t = c.need("text", usage)
    row = c.hall.letter(lid)
    if row["status"] == "open" and row["describer_id"] == me["id"] and (row["text"] or "").strip() == t.strip():
        d = c.hall.letter_view(me, lid)
        head = "This letter was already sent with these words; nothing changed."
    else:
        d = c.hall.send_letter(me, lid, t)
        head = f"Letter {lid} is open: {d['words']} words (budget {d['budget']})."
    return text([head, f"Its page: {_abs(c.base, d['url'])}", "",
                 "Up to five people will build it; you'll see every board on its page as they come in.",
                 f"  the letter, with builds so far: {c.url('/play/letter', letter=lid)}",
                 f"  build someone else's:           {c.url('/play/letters')}"])


@router.get("/play/picture.png")
@play
async def picture(request: Request):
    c = Ctx(request)
    usage = f"A letter's picture:\n  {c.base}/play/picture.png?key=KEY&letter=LETTER"
    lid = c.need("letter", usage)
    me = c.need_me(usage) if c.key else None
    row = c.hall.letter(lid)
    if not c.hall.can_see_letter_picture(me, row):
        raise Stop("NOT DONE: this picture is shown only to its describer, to those who have built the letter, and "
                   "to everyone once it closes.")
    pic = c.hall.picture(row["picture_id"])
    data = await run_in_threadpool(request.app.state.images.picture, D.loads(pic["shapes"]), row["level"], row["word"], pic["id"], None)
    return Response(data, media_type="image/png", headers=NO_STORE)


# ---------------------------------------------------------------- building

@router.get("/play/letters")
@play
async def letters(request: Request):
    c = Ctx(request)
    me = c.need_me(f"{c.base}/play/letters?key=KEY")
    level = c.q.get("level")
    d = c.hall.list_letters(me, int(level) if level and level.isdigit() else None)
    if not d["letters"]:
        return text(["No open letter is waiting for you right now.",
                     f"Describe a picture instead: {c.url('/play/describe', level=1)}"])
    lines = [f"{plural(len(d['letters']), 'open letter')} you may build:", ""]
    for l in d["letters"]:
        lines += [f"{l['letter']}  level {l['level']} ({l['level_name']}) by {l['describer']}, {l['words']} words, {l['builds']} built",
                  f"  {l['text']}",
                  f"  build it: {c.url('/play/take', letter=l['letter'], go='yes')}", ""]
    return text(lines)


@router.get("/play/take")
@play
async def take(request: Request):
    c = Ctx(request)
    usage = f"Start building a letter:\n  {c.base}/play/take?key=KEY&letter=LETTER&go=yes"
    me = c.need_me(usage)
    lid = c.need("letter", usage)
    c.go(usage)
    b = c.hall.take_letter(me, lid)
    bid = b["build"]
    return text([
        f"Build {bid} of letter {lid} (level {b['level']}, {b['level_name']}, word {b['word']}) by {b['describer']}. The words:",
        "", f"  {b['text']}", "",
        "The board is 10 by 10: x from the left edge, y from the bottom. Later shapes go on top.",
        "Set your whole board with one address (shapes separated by commas; + for spaces):",
        f"  {c.url('/play/board', build=bid, shapes='rect red 2 1 3 2,ellipse blue 5 5 2 1.5')}",
        "  rect COLOUR X Y W H | ellipse COLOUR CX CY RX RY | triangle COLOUR X1 Y1 X2 Y2 X3 Y3",
        f"See it: {c.url('/play/board.png', build=bid)}",
        f"Check it ({b.get('checks_left', 0)} left; readings and a direction, never the picture): {c.url('/play/check', build=bid, go='yes')}",
        f"Submit: {c.url('/play/submit', build=bid, go='yes', note='WHAT DID NOT FIT')}",
    ])


@router.get("/play/board")
@play
async def board(request: Request):
    c = Ctx(request)
    usage = (f"Show your board, or set all of it:\n  {c.base}/play/board?key=KEY&build=BUILD\n"
             f"  {c.base}/play/board?key=KEY&build=BUILD&shapes=rect+red+2+1+3+2,ellipse+blue+5+5+2+1.5\n"
             f"  {c.base}/play/board?key=KEY&build=BUILD&clear=yes")
    me = c.need_me(usage)
    bid = c.need("build", usage)
    notes = []
    if "shapes" in c.q:
        try:
            raw = parse_text(c.q.get("shapes") or "")
        except ShapeError as e:
            raise Stop(f"NOT DONE: {e} Nothing was changed.")
        if not raw:
            raise Stop("NOT DONE: shapes= was empty. To empty the board use clear=yes.")
        b = c.hall.put_shapes(me, bid, raw)
        notes = b.get("notes", [])
        head = f"Your board now holds {plural(b['count'], 'shape')}."
    elif (c.q.get("clear") or "").lower() in ("yes", "1", "true"):
        b = c.hall.clear(me, bid)
        head = "Your board is empty."
    else:
        b = c.hall.build_state(me, bid)
        head = "Your board (nothing changed):"
    lines = [head] + _build_lines(c, b) + [f"  {n}" for n in notes]
    if b.get("text"):
        lines += ["", "The letter's words:", f"  {b['text']}"]
    if b["status"] == "building":
        live = b["mode"] == "live"
        lines += ["", "Next:"]
        if not live and b.get("checks_left"):
            lines.append(f"  check ({b['checks_left']} left): {c.url('/play/check', build=bid, go='yes')}")
        if live:
            lines.append(f"  the chat: {c.url('/play/match', match=b['match'])}")
        lines.append(f"  submit:  {c.url('/play/submit', build=bid, go='yes', note='WHAT DID NOT FIT')}")
    return text(lines)


@router.get("/play/board.png")
@play
async def board_png(request: Request):
    c = Ctx(request)
    usage = f"Your board as an image:\n  {c.base}/play/board.png?key=KEY&build=BUILD"
    bid = c.need("build", usage)
    me = c.need_me(usage)
    b = c.hall.resolve_build(me, bid)
    if not c.hall.can_see_build(me, b):
        raise Stop("NOT DONE: this board is only visible to its builder until its result is public.")
    letter, rnd = c.hall._build_context(b)
    level = letter["level"] if letter else rnd["level"]
    g = c.q.get("grid")
    grid = (level <= 3) if g is None else g in ("1", "yes", "true")
    data = await run_in_threadpool(request.app.state.images.board, D.loads(b["shapes"]),
                                   letter["word"] if letter else rnd["word"], grid, None,
                                   f"{c.hall.callsign(b['builder_id'])}'s board")
    return Response(data, media_type="image/png", headers=NO_STORE)


@router.get("/play/diff.png")
@play
async def diff_png(request: Request):
    c = Ctx(request)
    usage = f"Where a submitted board differs from the picture:\n  {c.base}/play/diff.png?key=KEY&build=BUILD"
    bid = c.need("build", usage)
    me = c.need_me(usage) if c.key else None
    b = c.hall.resolve_build(me, bid)
    if b["status"] != "submitted":
        raise Stop("NOT DONE: the difference is drawn after the build is submitted.")
    if not (c.hall.can_see_build(me, b) and c.hall.can_see_build_picture(me, b)):
        raise Stop("NOT DONE: this shows the picture, which isn't public yet.")
    letter, rnd = c.hall._build_context(b)
    pic = c.hall.picture(letter["picture_id"] if letter else rnd["picture_id"])
    data = await run_in_threadpool(request.app.state.images.diff, D.loads(pic["shapes"]), D.loads(b["shapes"]),
                                   letter["word"] if letter else rnd["word"], None)
    return Response(data, media_type="image/png", headers=NO_STORE)


@router.get("/play/check")
@play
async def check(request: Request):
    c = Ctx(request)
    usage = f"Check your board (a letter's builder may check twice):\n  {c.base}/play/check?key=KEY&build=BUILD&go=yes"
    me = c.need_me(usage)
    bid = c.need("build", usage)
    c.go(usage)
    d = c.hall.check(me, bid)
    lines = [f"Check {d['check']} of {d['check'] + d['checks_left']} (the picture stays hidden):"]
    lines += _readings_lines(d, "  ")
    lines.append(f"  direction: {d['direction']}.")
    lines.append("  Moving the whole board leaves slid to fit the same: it is about the shapes. In place and the "
                 "direction are about where they are.")
    lines += ["", f"{plural(d['checks_left'], 'check')} left.",
              f"  change the board: {c.url('/play/board', build=bid, shapes='...')}",
              f"  submit:           {c.url('/play/submit', build=bid, go='yes', note='WHAT DID NOT FIT')}"]
    return text(lines)


def _result_lines(c: Ctx, r: dict, build: str, letter: str | None = None) -> list[str]:
    lines = _readings_lines(r)
    sl = r.get("slide") or {}
    if sl.get("right") or sl.get("up"):
        parts = []
        if sl["right"]:
            parts.append(f"{abs(sl['right']):g} {'right' if sl['right'] > 0 else 'left'}")
        if sl["up"]:
            parts.append(f"{abs(sl['up']):g} {'up' if sl['up'] > 0 else 'down'}")
        lines.append(f"It fit best slid {' and '.join(parts)}.")
    if r.get("loss"):
        lines += ["", r["loss"]["sentence"]]
    pic = c.url("/play/picture.png", letter=letter) if letter else _abs(c.base, r["picture_url"])
    lines += ["", f"The picture:               {pic}",
              f"Where they differ:         {c.url('/play/diff.png', build=build)}",
              f"Every board, side by side: {_abs(c.base, r['page_url'])}",
              "The picture's true shapes:"] + [f"  {x}" for x in r["picture_lines"]]
    return lines


@router.get("/play/submit")
@play
async def submit(request: Request):
    c = Ctx(request)
    usage = (f"Submit your board (once; then you see the picture):\n"
             f"  {c.base}/play/submit?key=KEY&build=BUILD&go=yes&note=WHAT+DID+NOT+FIT\n"
             "The note is optional (60 words) and is the only reply the describer gets: most useful is the one clause "
             "of their letter that did the most damage, the one you would cut or rewrite.")
    me = c.need_me(usage)
    bid = c.need("build", usage)
    c.go(usage)
    b = c.hall.resolve_build(me, bid)
    if b["status"] == "submitted" and b["builder_id"] == me["id"]:
        d = c.hall.build_state(me, b["id"])
        head = ["This build was already submitted; here is its result again."]
    else:
        d = c.hall.submit(me, bid, c.q.get("note"))
        head = []
    r = d["result"]
    lines = head + _result_lines(c, r, d["build"], d.get("letter"))
    if "others" in r:
        lines.append("You are the first to build this letter." if not r["others"] else
                     f"{plural(r['others'], 'other player')} built it too.")
    if d.get("match"):
        lines += ["", f"The match: {c.url('/play/match', match=d['match'])}"]
    else:
        lines += ["", "Next:", f"  build another: {c.url('/play/letters')}",
                  f"  describe one:  {c.url('/play/describe', level=1)}"]
    return text(lines)


@router.get("/play/letter")
@play
async def letter(request: Request):
    c = Ctx(request)
    lid = c.need("letter", f"A letter's page as text:\n  {c.base}/play/letter?key=KEY&letter=LETTER")
    me = c.need_me("") if c.key else None
    l = c.hall.letter_view(me, lid)
    lines = [f"Letter {lid} by {l['describer']}: level {l['level']} ({l['level_name']}), word {l['word']}, {l['status']}"
             + (f" ({l['close_reason']})" if l.get("close_reason") else "") + ".",
             f"  {l.get('text') or '(not sent yet)'}",
             f"{l['builds_submitted']} built, {l['builds_in_progress']} building. Page: {_abs(c.base, l['url'])}"]
    if l.get("picture_url"):
        lines.append(f"The picture: {c.url('/play/picture.png', letter=lid)}")
    for r in l.get("results", []):
        lines += ["", f"{r['builder']}: {said(r['in_place'])} in place, {said(r['slid_to_fit'])} slid to fit"]
        for ch in r.get("checks", []):
            lines.append(f"  check {ch['check']}: {said(ch['in_place'])} in place, {said(ch['slid_to_fit'])} slid to fit")
        if r.get("note"):
            lines.append(f"  note: {r['note']}")
        if r.get("loss"):
            lines.append(f"  {r['loss']['sentence']}")
    if l.get("next"):
        lines += ["", f"Next: {l['next']}"]
    if me and l["status"] == "open" and not c.hall.may_build(me, c.hall.letter(lid)):
        lines.append(f"  build it: {c.url('/play/take', letter=lid, go='yes')}")
    return text(lines)


@router.get("/play/close")
@play
async def close(request: Request):
    c = Ctx(request)
    usage = f"Close your open letter now, or discard a draft:\n  {c.base}/play/close?key=KEY&letter=LETTER&go=yes"
    me = c.need_me(usage)
    lid = c.need("letter", usage)
    c.go(usage)
    d = c.hall.close_letter(me, lid)
    return text(f"Letter {lid} is {d['status']}.")


# ---------------------------------------------------------------- live

def _match_lines(c: Ctx, st: dict) -> list[str]:
    mid = st["match"]
    cur = st.get("current")
    head = f"Match {mid} · {st['status']}"
    if cur:
        head += f" · round {cur['n']} of {st['rounds']} · level {cur['level']} ({cur['level_name']})"
        if cur.get("word"):
            head += f" · this round's word is {cur['word']}"
    lines = [head, st.get("waiting_sentence", "")]
    role = st["you"]["role"]
    if cur and role in ("describer", "builder"):
        lines.append(f"You are the {role}. {cur['describer']} describes, {cur['builder']} builds. "
                     f"Describer's words: {cur['describer_words_used']} used, {cur['describer_words_left']} left this round.")
        lines.append("Chat this round:" if cur.get("chat") else "Chat this round: nothing yet.")
        lines += [f"  {m['from']} ({m['role']}, {m['words']} words): {m['text']}" for m in cur.get("chat", [])]
        if role == "describer":
            lines.append(f"The picture: {c.url('/play/look.png', match=mid)}")
        else:
            lines.append(f"Your board: {len(cur.get('shapes', []))} shapes. See it: {c.url('/play/look.png', match=mid)}")
    for r in st.get("finished_rounds", []):
        lines.append(f"  round {r['n']}: level {r['level']}, {r['describer']} → {r['builder']}, "
                     f"{said(r['in_place'])} in place, {said(r['slid_to_fit'])} slid to fit  {_abs(c.base, r['url'])}")
    lines += ["", "Next:"]
    if st["status"] == "waiting":
        lines.append(f"  someone takes the seat with: {c.base}/play/join?key=THEIR_KEY&match={mid}&go=yes")
        lines.append(f"  wait for them: {c.url('/play/match', match=mid, wait=25)}")
    elif cur and role == "describer":
        lines.append(f"  say something: {c.url('/play/say', match=mid, text='YOUR WORDS')}")
        lines.append(f"  wait for news: {c.url('/play/match', match=mid, wait=25)}")
    elif cur and role == "builder":
        lines.append(f"  set your board: {c.url('/play/board', build=mid, shapes='rect red 2 1 3 2')}")
        lines.append(f"  ask a question: {c.url('/play/say', match=mid, text='YOUR QUESTION')}")
        lines.append(f"  submit:         {c.url('/play/submit', build=mid, go='yes')}")
        lines.append(f"  wait for news:  {c.url('/play/match', match=mid, wait=25)}")
    else:
        lines.append(f"  play again: {c.url('/play/seat', go='yes')}")
    lines.append("(Add something that changes, like &n=2, if your fetch tool shows you an old copy.)")
    return lines


@router.get("/play/match")
@play
async def match(request: Request):
    import asyncio
    c = Ctx(request)
    usage = f"A live match and its chat:\n  {c.base}/play/match?key=KEY&match=MATCH&wait=25   (wait is optional, up to 60 s)"
    mid = c.need("match", usage)
    me = c.need_me(usage)
    ev = request.app.state.notifier.get(mid)
    st = c.hall.match_state(me, mid)
    wait = c.q.get("wait")
    if wait:
        try:
            w = max(0.0, min(60.0, float(wait)))
        except ValueError:
            w = 0
        if w:
            try:
                await asyncio.wait_for(ev.wait(), timeout=w)
            except asyncio.TimeoutError:
                pass
            st = c.hall.match_state(me, mid)
    return text(_match_lines(c, st))


@router.get("/play/look.png")
@play
async def look(request: Request):
    c = Ctx(request)
    usage = f"The picture (if you describe) or your board (if you build):\n  {c.base}/play/look.png?key=KEY&match=MATCH"
    mid = c.need("match", usage)
    me = c.need_me(usage)
    m = c.hall.match(mid)
    rnd = c.hall._current_round(m)
    if not rnd:
        raise Stop("NOT DONE: no round is being played in this match.")
    if me["id"] == rnd["describer_id"]:
        pic = c.hall.picture(rnd["picture_id"])
        data = await run_in_threadpool(request.app.state.images.picture, D.loads(pic["shapes"]), rnd["level"], rnd["word"], pic["id"], None)
    elif me["id"] == rnd["builder_id"]:
        b = c.hall.one("SELECT * FROM builds WHERE id=?", rnd["build_id"])
        data = await run_in_threadpool(request.app.state.images.board, D.loads(b["shapes"]), rnd["word"], rnd["level"] <= 3,
                                       None, f"{me['callsign']}'s board")
    else:
        raise Stop("NOT DONE: you are not playing in this round.")
    return Response(data, media_type="image/png", headers=NO_STORE)


@router.get("/play/say")
@play
async def say(request: Request):
    c = Ctx(request)
    usage = f"Talk in a live match:\n  {c.base}/play/say?key=KEY&match=MATCH&text=YOUR+WORDS"
    me = c.need_me(usage)
    mid = c.need("match", usage)
    t = c.need("text", usage)
    rnd = c.hall._current_round(c.hall.match(mid))
    last = c.hall.one("SELECT * FROM messages WHERE round_id=? ORDER BY id DESC LIMIT 1", rnd["id"]) if rnd else None
    if last and last["player_id"] == me["id"] and last["text"] == t.strip() and last["created"] > D.now() - 600:
        st = c.hall.match_state(me, mid)
        return text(["You said exactly this a moment ago; it was not sent twice."] + _match_lines(c, st))
    st = c.hall.say(me, mid, t)
    return text(["Sent."] + _match_lines(c, st))


@router.get("/play/seat")
@play
async def seat(request: Request):
    c = Ctx(request)
    usage = f"Sit at the oldest open live match, or open one:\n  {c.base}/play/seat?key=KEY&go=yes   (optional: level=1&rounds=4)"
    me = c.need_me(usage)
    c.go(usage)
    limit(request, "matches", me)
    st = c.hall.seat(me, c.q.get("level"), c.q.get("rounds"))
    return text([st.get("seated", "")] + _match_lines(c, st))


@router.get("/play/invite")
@play
async def invite(request: Request):
    c = Ctx(request)
    usage = f"Start a live match for one invited player:\n  {c.base}/play/invite?key=KEY&go=yes   (optional: rounds=4&level=1)"
    me = c.need_me(usage)
    c.go(usage)
    limit(request, "matches", me)
    st = c.hall.create_match(me, (c.q.get("open") or "").lower() in ("yes", "1", "true"), c.q.get("rounds"), c.q.get("level"))
    return text([f"Match {st['match']} is waiting. Give this page to the one you invite: {_abs(c.base, st['invite_url'])}",
                 f"An agent who can only fetch joins with: {c.base}/play/join?key=THEIR_KEY&match={st['match']}&go=yes"]
                + _match_lines(c, st))


@router.get("/play/join")
@play
async def join(request: Request):
    c = Ctx(request)
    usage = f"Take the seat in a match (whoever joins describes first):\n  {c.base}/play/join?key=KEY&match=MATCH&go=yes"
    me = c.need_me(usage)
    mid = c.need("match", usage)
    c.go(usage)
    st = c.hall.join_match(me, mid)
    return text(_match_lines(c, st))
