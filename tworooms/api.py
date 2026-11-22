"""The JSON API. Thin: parse the request, call the hall, absolutise URLs, render images off the event loop."""
import asyncio
import json
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from . import db as D
from .config import LEVELS
from .game import GameError

router = APIRouter()


# ---------------------------------------------------------------- plumbing

class Notifier:
    """One asyncio.Event per match, replaced each time it fires: long-polls wait on it."""

    def __init__(self):
        self.events: dict[str, asyncio.Event] = {}

    def get(self, mid: str) -> asyncio.Event:
        ev = self.events.get(mid)
        if ev is None:
            ev = self.events[mid] = asyncio.Event()
        return ev

    def notify(self, mid: str):
        ev = self.events.pop(mid, None)
        if ev is not None:
            ev.set()


class RateLimiter:
    def __init__(self):
        self.hits: dict[tuple, deque] = defaultdict(deque)

    def check(self, bucket: str, who: str, n: int, per: float, what: str):
        q = self.hits[(bucket, who)]
        t = time.time()
        while q and q[0] < t - per:
            q.popleft()
        if len(q) >= n:
            wait = int(q[0] + per - t) + 1
            raise GameError(429, f"Too many {what} from you; try again in {wait // 60 + 1} minutes." if wait > 90
                            else f"Too many {what} from you; try again in {wait} seconds.")
        q.append(t)


LIMITS = {
    "players": [("ip", 30, 3600)],
    "letters": [("key", 40, 3600), ("ip", 80, 3600)],
    "matches": [("key", 20, 3600), ("ip", 40, 3600)],
    "any": [("key", 600, 60), ("ip", 1200, 60)],
}


def client_ip(request: Request) -> str:
    if request.app.state.trust_proxy:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


def limit(request: Request, bucket: str, me=None):
    rl = request.app.state.limiter
    what = {"players": "new callsigns", "letters": "new pictures", "matches": "new matches", "any": "requests"}[bucket]
    for scope, n, per in LIMITS[bucket]:
        if scope == "ip":
            rl.check(bucket, "ip:" + client_ip(request), n, per, what)
        elif me not in (None, "admin"):
            rl.check(bucket, f"key:{me['id']}", n, per, what)


def key_of(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get("tr_key")


def viewer(request: Request):
    hall = request.app.state.hall
    k = key_of(request)
    me = hall.player_by_key(k)
    if k and me is None:
        raise GameError(401, "That key is not known here. Keys can't be recovered; make a new callsign with POST /api/players.")
    limit(request, "any", me)
    return me


def need(request: Request):
    me = viewer(request)
    if me is None:
        raise GameError(401, "This needs your key: send 'Authorization: Bearer <key>'. No key yet? "
                             "POST /api/players {\"callsign\": \"...\"} gives you one.")
    if me == "admin":
        raise GameError(403, "The admin key can only hide things (POST /api/admin/hide); play with a callsign.")
    return me


async def body(request: Request) -> dict:
    raw = await request.body()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        ctype = request.headers.get("content-type", "")
        if "form" in ctype:
            form = await request.form()
            return dict(form)
        return {"_raw": raw.decode("utf-8", "replace")}
    if isinstance(data, list):
        return {"_list": data}
    if not isinstance(data, dict):
        return {"_raw": str(data)}
    return data


def base_url(request: Request) -> str:
    return request.app.state.base_url or str(request.base_url).rstrip("/")


def absolutise(obj, base: str):
    if isinstance(obj, dict):
        return {k: (base + v if isinstance(v, str) and v.startswith("/") and (k == "url" or k.endswith("_url"))
                    else absolutise(v, base)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [absolutise(v, base) for v in obj]
    return obj


def ok(request: Request, data, status: int = 200) -> JSONResponse:
    return JSONResponse(absolutise(data, base_url(request)), status_code=status)


def png(data: bytes, private: bool = True, fresh: bool = False, kind: str = "image/png") -> Response:
    cc = "no-store" if fresh else ("private, max-age=300" if private else "public, max-age=3600")
    return Response(data, media_type=kind, headers={"Cache-Control": cc})


def size_param(request: Request) -> int | None:
    s = request.query_params.get("size")
    if not s:
        return None
    try:
        return max(64, min(800, int(s)))
    except ValueError:
        raise GameError(400, "size is a whole number of pixels from 64 to 800.")


def text_of(payload: dict) -> str:
    t = payload.get("text", payload.get("_raw"))
    if not isinstance(t, str):
        raise GameError(400, 'Send the words as JSON {"text": "..."} (or as a plain text body).')
    return t


# ---------------------------------------------------------------- players and overview

@router.post("/api/players")
async def create_player(request: Request):
    # the town daemon registers a Delve Town handle's player with via "town", using the admin key
    admin = request.app.state.hall.player_by_key(key_of(request)) == "admin"
    if not admin:
        limit(request, "players")
    p = await body(request)
    return ok(request, request.app.state.hall.create_player(p.get("callsign"), p.get("kind"), p.get("about"),
                                                           p.get("via") if admin else None), 201)


@router.get("/api/me")
async def get_me(request: Request):
    return ok(request, request.app.state.hall.me(need(request)))


@router.post("/api/me")
async def update_me(request: Request):
    me = need(request)
    p = await body(request)
    return ok(request, request.app.state.hall.update_player(me, p.get("kind"), p.get("about")))


@router.get("/api/hall")
async def get_hall(request: Request):
    return ok(request, request.app.state.hall.hall(viewer(request)))


@router.get("/api/levels")
async def get_levels(request: Request):
    from .config import live_budget
    return ok(request, {"levels": [{"level": n, "name": lv.name, "budget": lv.budget, "live_budget": live_budget(n),
                                    "grid": lv.grid, "what": lv.blurb} for n, lv in LEVELS.items()]})


@router.post("/api/words")
async def check_words(request: Request):
    """Count words and apply the number rule without sending anything."""
    from .words import Refused, check_message, count_words
    me = viewer(request)
    p = await body(request)
    text = text_of(p)
    budget = p.get("budget")
    n, _ = count_words(text)
    try:
        check_message(text, budget_left=int(budget) if budget not in (None, "") else None,
                      exempt=(me["callsign"],) if me not in (None, "admin") else (), unit="message")
        return ok(request, {"words": n, "ok": True, "next": "It would be accepted."})
    except Refused as e:
        return ok(request, {"words": n, "ok": False, "error": str(e).replace("Not sent: ", "Would be refused: ")})


@router.get("/api/events")
async def get_events(request: Request, since: int = 0):
    return ok(request, request.app.state.hall.events(since))


# ---------------------------------------------------------------- letters

@router.post("/api/letters")
async def create_letter(request: Request):
    me = need(request)
    limit(request, "letters", me)
    p = await body(request)
    return ok(request, request.app.state.hall.create_letter(me, p.get("level", 1)), 201)


@router.get("/api/letters")
async def list_letters(request: Request, level: int | None = None):
    return ok(request, request.app.state.hall.list_letters(viewer(request), level))


@router.get("/api/letters/{lid}")
async def get_letter(request: Request, lid: str):
    return ok(request, request.app.state.hall.letter_view(viewer(request), lid))


@router.post("/api/letters/{lid}/send")
async def send_letter(request: Request, lid: str):
    me = need(request)
    return ok(request, request.app.state.hall.send_letter(me, lid, text_of(await body(request))))


@router.post("/api/letters/{lid}/close")
async def close_letter(request: Request, lid: str):
    me = viewer(request)
    if me is None:
        need(request)
    p = await body(request)
    return ok(request, request.app.state.hall.close_letter(me, lid, p.get("reason")))


@router.post("/api/letters/{lid}/builds")
async def take_letter(request: Request, lid: str):
    me = need(request)
    p = await body(request)
    return ok(request, request.app.state.hall.take_letter(me, lid, p.get("via_url")), 201)


@router.get("/api/letters/{lid}/picture.png")
async def letter_picture(request: Request, lid: str):
    hall = request.app.state.hall
    me = viewer(request)
    row = hall.letter(lid)
    if not hall.can_see_letter_picture(me, row):
        raise GameError(403, "This picture is shown only to its describer and to those who have built the letter, "
                             "until the letter closes.")
    pic = hall.picture(row["picture_id"])
    shapes = D.loads(pic["shapes"])
    data = await run_in_threadpool(request.app.state.images.picture, shapes, row["level"], row["word"], pic["id"],
                                   size_param(request))
    return png(data, private=row["status"] != "closed")


# ---------------------------------------------------------------- builds

@router.get("/api/builds/{bid}")
async def get_build(request: Request, bid: str):
    return ok(request, request.app.state.hall.build_state(viewer(request), bid))


@router.post("/api/builds/{bid}/place")
async def place(request: Request, bid: str):
    me = need(request)
    p = await body(request)
    return ok(request, request.app.state.hall.place(me, bid, p.get("_list", p)))


@router.post("/api/builds/{bid}/undo")
async def undo(request: Request, bid: str):
    return ok(request, request.app.state.hall.undo(need(request), bid))


@router.post("/api/builds/{bid}/clear")
async def clear(request: Request, bid: str):
    return ok(request, request.app.state.hall.clear(need(request), bid))


@router.put("/api/builds/{bid}/shapes")
async def put_shapes(request: Request, bid: str):
    me = need(request)
    p = await body(request)
    return ok(request, request.app.state.hall.put_shapes(me, bid, p.get("_list", p)))


@router.post("/api/builds/{bid}/submit")
async def submit(request: Request, bid: str):
    me = need(request)
    p = await body(request)
    return ok(request, request.app.state.hall.submit(me, bid, p.get("note") or p.get("_raw")))


@router.post("/api/builds/{bid}/check")
async def check(request: Request, bid: str):
    return ok(request, request.app.state.hall.check(need(request), bid))


@router.get("/api/builds/{bid}/checks/{n}.png")
async def check_png(request: Request, bid: str, n: int):
    hall = request.app.state.hall
    me = viewer(request)
    b = hall.resolve_build(me, bid)
    if not hall.can_see_build(me, b):
        raise GameError(403, "This board is only visible to its builder until its result is public.")
    c = hall.one("SELECT * FROM checks WHERE build_id=? AND n=?", b["id"], n)
    if not c:
        raise GameError(404, f"Build {b['id']} has no check {n}.")
    data = await run_in_threadpool(request.app.state.images.framed_board, D.loads(c["shapes"]), size_param(request))
    return png(data)


@router.get("/api/builds/{bid}/board.png")
async def board_png(request: Request, bid: str):
    hall = request.app.state.hall
    me = viewer(request)
    b = hall.resolve_build(me, bid)
    if not hall.can_see_build(me, b):
        raise GameError(403, "This board is only visible to its builder until its result is public.")
    letter, rnd = hall._build_context(b)
    level = letter["level"] if letter else rnd["level"]
    g = request.query_params.get("grid")
    grid = (level <= 3) if g is None else g.lower() in ("1", "true", "yes", "on")
    word = letter["word"] if letter else rnd["word"]
    who = f"{hall.callsign(b['builder_id'])}'s board"
    if request.query_params.get("framed") in ("1", "true", "yes"):
        data = await run_in_threadpool(request.app.state.images.framed_board, D.loads(b["shapes"]), size_param(request))
        return png(data, fresh=b["status"] == "building")
    if request.query_params.get("plain") in ("1", "true", "yes"):
        data = await run_in_threadpool(request.app.state.images.plain, D.loads(b["shapes"]), size_param(request) or 400)
        return png(data, fresh=b["status"] == "building")
    data = await run_in_threadpool(request.app.state.images.board, D.loads(b["shapes"]), word, grid, size_param(request), who)
    return png(data, fresh=b["status"] == "building")


@router.get("/api/builds/{bid}/diff.png")
async def diff_png(request: Request, bid: str):
    hall = request.app.state.hall
    me = viewer(request)
    b = hall.resolve_build(me, bid)
    if b["status"] != "submitted":
        raise GameError(409, "The difference is drawn after the build is submitted.")
    if not (hall.can_see_build(me, b) and hall.can_see_build_picture(me, b)):
        raise GameError(403, "This difference shows the picture, which isn't public yet.")
    letter, rnd = hall._build_context(b)
    pic = hall.picture(letter["picture_id"] if letter else rnd["picture_id"])
    word = letter["word"] if letter else rnd["word"]
    if request.query_params.get("framed") in ("1", "true", "yes"):
        data = await run_in_threadpool(request.app.state.images.framed_diff, D.loads(pic["shapes"]), D.loads(b["shapes"]),
                                       size_param(request))
        return png(data)
    data = await run_in_threadpool(request.app.state.images.diff, D.loads(pic["shapes"]), D.loads(b["shapes"]), word,
                                   size_param(request))
    return png(data)


# ---------------------------------------------------------------- live matches

@router.post("/api/matches")
async def create_match(request: Request):
    me = need(request)
    limit(request, "matches", me)
    p = await body(request)
    return ok(request, request.app.state.hall.create_match(me, bool(p.get("open", False)), p.get("rounds"), p.get("level")), 201)


@router.post("/api/matches/{mid}/join")
async def join_match(request: Request, mid: str):
    return ok(request, request.app.state.hall.join_match(need(request), mid))


@router.post("/api/seat")
async def seat(request: Request):
    me = need(request)
    limit(request, "matches", me)
    p = await body(request)
    return ok(request, request.app.state.hall.seat(me, p.get("level"), p.get("rounds")))


@router.get("/api/matches/{mid}")
async def get_match(request: Request, mid: str, since: int | None = None, wait: float | None = None):
    hall = request.app.state.hall
    me = viewer(request)
    ev = request.app.state.notifier.get(mid)
    st = hall.match_state(me, mid, since)
    if wait and wait > 0:
        if since is None:
            since = st["last_event"]
        if st["last_event"] <= since:
            try:
                await asyncio.wait_for(ev.wait(), timeout=min(float(wait), 60.0))
            except asyncio.TimeoutError:
                pass
            st = hall.match_state(me, mid, since)
    return ok(request, st)


@router.get("/api/matches/{mid}/picture.png")
async def match_picture(request: Request, mid: str):
    hall = request.app.state.hall
    me = viewer(request)
    m = hall.match(mid)
    rnd = hall._current_round(m)
    if not rnd:
        raise GameError(409, "No round is being played in this match. Finished rounds' pictures are at /api/rounds/<id>/picture.png.")
    if me in (None, "admin") or me["id"] != rnd["describer_id"]:
        raise GameError(403, "Only this round's describer can see its picture.")
    pic = hall.picture(rnd["picture_id"])
    data = await run_in_threadpool(request.app.state.images.picture, D.loads(pic["shapes"]), rnd["level"], rnd["word"],
                                   pic["id"], size_param(request))
    return png(data)


@router.post("/api/matches/{mid}/say")
async def say(request: Request, mid: str):
    me = need(request)
    return ok(request, request.app.state.hall.say(me, mid, text_of(await body(request))))


@router.get("/api/rounds/{rid}")
async def get_round(request: Request, rid: str):
    return ok(request, request.app.state.hall.round_view(viewer(request), rid))


@router.get("/api/rounds/{rid}/picture.png")
async def round_picture(request: Request, rid: str):
    hall = request.app.state.hall
    me = viewer(request)
    rnd = hall.one("SELECT * FROM rounds WHERE id=?", rid)
    if not rnd:
        raise GameError(404, f'There is no round "{rid}".')
    if not hall.can_see_round_picture(me, rnd):
        raise GameError(403, "This round's picture is private until the round is submitted.")
    pic = hall.picture(rnd["picture_id"])
    data = await run_in_threadpool(request.app.state.images.picture, D.loads(pic["shapes"]), rnd["level"], rnd["word"],
                                   pic["id"], size_param(request))
    return png(data, private=rnd["status"] != "finished")


@router.get("/api/players/{callsign}")
async def get_player(request: Request, callsign: str):
    viewer(request)
    return ok(request, request.app.state.hall.profile(callsign))


@router.post("/api/admin/hide")
async def admin_hide(request: Request):
    me = viewer(request)
    if me != "admin":
        raise GameError(403, "This needs the admin key.")
    p = await body(request)
    return ok(request, request.app.state.hall.hide(p.get("kind"), p.get("id"), p.get("hidden", True)))
