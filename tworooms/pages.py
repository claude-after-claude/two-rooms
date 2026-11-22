"""Server-rendered pages. Readable without JavaScript, except the builder's canvas and the live room's updates."""
import html
import re
import urllib.parse
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from . import config as C
from . import db as D
from .api import base_url, limit
from .game import GameError
from .score import compare
from .shapes import describe
from .words import ALWAYS_ALLOWED, BEFORE_FRACTION_ONLY, REFUSED_BASE

HERE = Path(__file__).parent
CLIENT = HERE.parent / "client" / "tworooms.py"
templates = Jinja2Templates(directory=HERE / "templates")
VERSION = "1"
router = APIRouter()

EXAMPLE = {
    "picture": [
        {"shape": "rect", "color": "green", "x": 1, "y": 5, "w": 5, "h": 4},
        {"shape": "rect", "color": "yellow", "x": 2, "y": 1, "w": 4, "h": 2},
        {"shape": "rect", "color": "black", "x": 7, "y": 0, "w": 2, "h": 2},
        {"shape": "rect", "color": "red", "x": 7, "y": 3, "w": 3, "h": 5},
    ],
    "build": [
        {"shape": "rect", "color": "green", "x": 1, "y": 5, "w": 5, "h": 4},
        {"shape": "rect", "color": "yellow", "x": 3, "y": 1, "w": 3, "h": 2},
        {"shape": "rect", "color": "red", "x": 7, "y": 3, "w": 3, "h": 5},
        {"shape": "rect", "color": "black", "x": 7.5, "y": 0, "w": 2, "h": 2},
    ],
    "text": ("A large green block in the upper left: a tenth of the way in from the left, its top a tenth below the "
             "top edge, half the board wide and two fifths tall. Under it, a yellow bar, a little narrower, with the "
             "same right edge, a fifth tall, a tenth up from the bottom. On the right, a red block touching the right "
             "edge, three tenths wide and half the board tall, its bottom level with the yellow's top. Below the red, "
             "a small black square sitting on the bottom edge, a fifth on a side, roughly under the red's middle."),
    "word": "HERON",
}


# ---------------------------------------------------------------- helpers

def page_viewer(request: Request):
    hall = request.app.state.hall
    me = hall.player_by_key(request.cookies.get("tr_key"))
    return None if me == "admin" else me


def page_need(request: Request):
    me = page_viewer(request)
    if me is None:
        raise _Redirect("/start?next=" + urllib.parse.quote(request.url.path))
    limit(request, "any", me)
    return me


class _Redirect(Exception):
    def __init__(self, url):
        self.url = url


def render(request: Request, name: str, code: int = 200, **kw) -> HTMLResponse:
    ctx = {"me": page_viewer(request), "base": base_url(request), "path": request.url.path, "v": VERSION,
           "levels": list(C.LEVELS.values())}
    ctx.update(kw)
    return templates.TemplateResponse(request, name, ctx, status_code=code)


def error_page(request: Request, status: int, message: str):
    if status == 401 and not request.url.path.startswith("/api/"):
        return RedirectResponse("/start?next=" + urllib.parse.quote(request.url.path), status_code=303)
    return render(request, "error.html", code=status, status=status, message=message)


def go(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def safe_next(n: str | None) -> str:
    n = n or "/"
    return n if n.startswith("/") and not n.startswith("//") else "/"


async def form(request: Request) -> dict:
    return dict(await request.form())


def set_key_cookie(resp: Response, request: Request, key: str):
    resp.set_cookie("tr_key", key, max_age=10 * 365 * 86400, httponly=True, samesite="lax",
                    secure=request.url.scheme == "https")


def guarded(fn):
    """Turn _Redirect into a redirect for page handlers (GameError is handled app-wide)."""
    import functools

    @functools.wraps(fn)
    async def inner(*a, **k):
        try:
            return await fn(*a, **k)
        except _Redirect as r:
            return go(r.url)
    return inner


# ---------------------------------------------------------------- the hall and players

@router.get("/", response_class=HTMLResponse)
@guarded
async def hall_page(request: Request):
    hall = request.app.state.hall
    me = page_viewer(request)
    res = compare(EXAMPLE["picture"], EXAMPLE["build"])
    letters = hall.list_letters(me, limit=1000)["letters"]
    seats = hall.matches_waiting(exclude_id=me["id"] if me else None)
    from .words import count_words
    example = {"text": EXAMPLE["text"], "words": count_words(EXAMPLE["text"])[0], "score": res["score"]}
    return render(request, "hall.html", example=example, n_letters=len(letters), seats=seats, recent=hall.recent(8))


@router.get("/start", response_class=HTMLResponse)
async def start_page(request: Request, next: str = "/"):
    return render(request, "start.html", next=safe_next(next))


@router.post("/start")
async def start_post(request: Request):
    f = await form(request)
    nxt = safe_next(f.get("next"))
    limit(request, "players")
    try:
        d = request.app.state.hall.create_player(f.get("callsign"), f.get("kind") or None, f.get("about") or None)
    except GameError as e:
        return render(request, "start.html", code=e.status, error=e.message, next=nxt)
    me = request.app.state.hall.player_by_callsign(d["callsign"])
    resp = render(request, "start.html", new_key=d["key"], next=nxt, me=me)
    set_key_cookie(resp, request, d["key"])
    return resp


@router.post("/signin")
async def signin(request: Request):
    f = await form(request)
    nxt = safe_next(f.get("next"))
    key = (f.get("key") or "").strip()
    me = request.app.state.hall.player_by_key(key)
    if me is None or me == "admin":
        return render(request, "start.html", code=401, error="That key is not known here.", next=nxt)
    resp = go(nxt)
    set_key_cookie(resp, request, key)
    return resp


@router.post("/signout")
async def signout(request: Request):
    resp = go("/")
    resp.delete_cookie("tr_key")
    return resp


@router.get("/p/{callsign}", response_class=HTMLResponse)
async def profile_page(request: Request, callsign: str):
    p = request.app.state.hall.profile(callsign)
    me = page_viewer(request)
    return render(request, "profile.html", p=p, is_me=bool(me and me["callsign"] == p["callsign"]))


@router.post("/me")
@guarded
async def profile_post(request: Request):
    me = page_need(request)
    f = await form(request)
    request.app.state.hall.update_player(me, f.get("kind", ""), f.get("about", ""))
    return go(f"/p/{me['callsign']}")


# ---------------------------------------------------------------- letters

@router.get("/describe", response_class=HTMLResponse)
@guarded
async def describe_page(request: Request, level: int = 1):
    me = page_need(request)
    d = request.app.state.hall.me(me)
    return render(request, "describe.html", here="describe", drafts=d["drafts"], mine=d["open_letters"], chosen=level)


@router.post("/describe")
@guarded
async def describe_post(request: Request):
    me = page_need(request)
    limit(request, "letters", me)
    f = await form(request)
    d = request.app.state.hall.create_letter(me, f.get("level", 1))
    return go(f"/describe/{d['letter']}")


@router.get("/describe/{lid}", response_class=HTMLResponse)
@guarded
async def draft_page(request: Request, lid: str):
    me = page_need(request)
    hall = request.app.state.hall
    row = hall.letter(lid)
    if row["describer_id"] != me["id"] or row["status"] != "draft":
        return go(f"/letter/{lid}")
    return render(request, "draft.html", here="describe", l=hall.letter_view(me, lid))


@router.post("/describe/{lid}/send")
@guarded
async def draft_send(request: Request, lid: str):
    me = page_need(request)
    hall = request.app.state.hall
    f = await form(request)
    try:
        hall.send_letter(me, lid, f.get("text", ""))
    except GameError as e:
        if e.status == 422:
            return render(request, "draft.html", code=422, here="describe", l=hall.letter_view(me, lid),
                          text=f.get("text", ""), error=e.message)
        raise
    return go(f"/letter/{lid}?sent=1")


@router.post("/letter/{lid}/close")
@guarded
async def letter_close(request: Request, lid: str):
    me = page_need(request)
    d = request.app.state.hall.close_letter(me, lid)
    return go("/describe" if d["status"] == "discarded" else f"/letter/{lid}")


@router.get("/letter/{lid}", response_class=HTMLResponse)
async def letter_page(request: Request, lid: str, sent: int = 0, built: str | None = None):
    hall = request.app.state.hall
    me = page_viewer(request)
    row = hall.letter(lid)
    if me and row["describer_id"] == me["id"] and row["status"] == "draft":
        return go(f"/describe/{lid}")
    l = hall.letter_view(me, lid)
    for r in l.get("results", []):
        r["lines"] = [f"{i + 1}. {describe(s)}" for i, s in enumerate(r["shapes"])]
    pic_lines = [f"{i + 1}. {describe(s)}" for i, s in enumerate(hall.shapes_of(row["picture_id"]))] if l.get("picture_url") else []
    why = hall.may_build(me, row) if me else None
    flash = "Your letter is open. Builders will find it under build; you'll see each board here as it comes in." if sent else None
    mine_r = [r for r in l.get("results", []) if me and r["builder"] == me["callsign"]]
    if built and mine_r:
        r = mine_r[0]
        flash = (f"Your board scored {r['score']} ({'it passes' if r['passed'] else '90 passes'}). The picture is above; "
                 f"magenta marks the {r['cells_differ']} cells where your board differs. Your note, if any, is the only reply "
                 f"{l['describer']} will get.")
    return render(request, "letter.html", l=l, mine=bool(me and row["describer_id"] == me["id"]), can_build=bool(me and not why),
                  why=why, picture_lines=pic_lines, flash=flash)


@router.get("/build", response_class=HTMLResponse)
async def build_list(request: Request, level: int | None = None):
    hall = request.app.state.hall
    me = page_viewer(request)
    letters = hall.list_letters(me, level, limit=200)["letters"]
    building = []
    if me:
        building = [b for b in hall.me(me)["builds_in_progress"]]
    return render(request, "build.html", here="build", letters=letters, level=level, building=building)


@router.post("/build/{lid}/take")
@guarded
async def build_take(request: Request, lid: str):
    me = page_need(request)
    b = request.app.state.hall.take_letter(me, lid)
    return go(f"/build/{b['build']}")


@router.get("/build/{bid}", response_class=HTMLResponse)
@guarded
async def build_page(request: Request, bid: str):
    me = page_need(request)
    hall = request.app.state.hall
    b = hall.build_state(me, bid)
    if b["mode"] == "live":
        return go(f"/m/{b['match']}")
    if b["status"] != "building" or b["builder"] != me["callsign"]:
        return go(f"/letter/{b['letter']}#b-{bid}")
    return render(request, "buildpage.html", here="build", b=b, grid=b["level"] <= 3)


@router.post("/build/{bid}/submit")
@guarded
async def build_submit(request: Request, bid: str):
    me = page_need(request)
    f = await form(request)
    d = request.app.state.hall.submit(me, bid, f.get("note"))
    return go(f"/letter/{d['letter']}?built={bid}#b-{bid}")


# ---------------------------------------------------------------- live

@router.get("/live", response_class=HTMLResponse)
async def live_page(request: Request):
    hall = request.app.state.hall
    me = page_viewer(request)
    mine = hall.me(me)["matches"] if me else []
    return render(request, "live.html", here="live", mine=mine, seats=hall.matches_waiting(exclude_id=me["id"] if me else None))


@router.post("/seat")
@guarded
async def seat_post(request: Request):
    me = page_need(request)
    limit(request, "matches", me)
    f = await form(request)
    d = request.app.state.hall.seat(me, f.get("level"), f.get("rounds"))
    return go(f"/m/{d['match']}")


@router.post("/m/new")
@guarded
async def match_new(request: Request):
    me = page_need(request)
    limit(request, "matches", me)
    f = await form(request)
    d = request.app.state.hall.create_match(me, f.get("open") == "1", f.get("rounds"), f.get("level"))
    return go(f"/m/{d['match']}")


@router.post("/m/{mid}/join")
@guarded
async def match_join(request: Request, mid: str):
    me = page_need(request)
    request.app.state.hall.join_match(me, mid)
    return go(f"/m/{mid}")


@router.get("/m/{mid}", response_class=HTMLResponse)
async def match_page(request: Request, mid: str):
    hall = request.app.state.hall
    me = page_viewer(request)
    m = hall.match_state(me, mid)
    b = None
    cur = m.get("current")
    if cur and m["you"]["role"] == "builder":
        b = hall.build_state(me, cur["build"])
    return render(request, "match.html", here="live", m=m, b=b, role=m["you"]["role"], grid=bool(cur and cur["level"] <= 3))


@router.post("/m/{mid}/say")
@guarded
async def match_say(request: Request, mid: str):
    me = page_need(request)
    f = await form(request)
    hall = request.app.state.hall
    try:
        hall.say(me, mid, f.get("text", ""))
    except GameError as e:
        if e.status == 422:
            m = hall.match_state(me, mid)
            cur = m.get("current")
            b = hall.build_state(me, cur["build"]) if cur and m["you"]["role"] == "builder" else None
            return render(request, "match.html", code=422, here="live", m=m, b=b, error=e.message, role=m["you"]["role"],
                          grid=bool(cur and cur["level"] <= 3))
        raise
    return go(f"/m/{mid}")


@router.post("/m/{mid}/submit")
@guarded
async def match_submit(request: Request, mid: str):
    me = page_need(request)
    f = await form(request)
    d = request.app.state.hall.submit(me, mid, f.get("note"))
    return go(f"/round/{d['round_id']}")


@router.get("/round/{rid}", response_class=HTMLResponse)
async def round_page(request: Request, rid: str):
    hall = request.app.state.hall
    r = hall.round_view(page_viewer(request), rid)
    lines = [f"{i + 1}. {describe(s)}" for i, s in enumerate(r["result"]["build_shapes"])] if r.get("result") else []
    me = page_viewer(request)
    onward = None
    if me and me["callsign"] in (r["describer"], r["builder"]):
        m = hall.match_state(me, r["match"])
        if m["status"] == "playing" and m.get("current"):
            onward = {"n": m["current"]["n"], "role": m["you"]["role"], "url": m["url"], "rounds": m["rounds"]}
        elif m["status"] == "finished":
            onward = {"done": True, "url": m["url"]}
    return render(request, "round.html", r=r, build_lines=lines, onward=onward)


@router.get("/wall", response_class=HTMLResponse)
async def wall_page(request: Request, level: int | None = None, mode: str | None = None, page: int = 1):
    per = 24
    page = max(1, page)
    mode = mode if mode in ("letters", "live") else None
    items = request.app.state.hall.recent(per * page + 1, level=level, mode=mode)
    more = len(items) > per * page
    items = items[per * (page - 1): per * page]

    def q(**kw):
        cur = {"level": level, "mode": mode, "page": None}
        cur.update(kw)
        if "page" not in kw:
            cur["page"] = None
        return urllib.parse.urlencode({k: v for k, v in cur.items() if v not in (None, "", 1) or (k == "level" and v)})

    return render(request, "wall.html", here="wall", items=items, level=level, mode=mode, page=page, more=more, q=q)


# ---------------------------------------------------------------- for agents

def manual_text(request: Request) -> str:
    return templates.get_template("llms.txt").render(
        base=base_url(request), levels=list(C.LEVELS.values()), note_words=C.NOTE_WORDS, max_shapes=C.MAX_BUILD_SHAPES,
        always=("one, two, three, first, second, third, once, twice, double, triple, and the fraction words half, halves, "
                "third(s), quarter(s), fourth(s), fifth(s), sixth(s), seventh(s), eighth(s), ninth(s), tenth(s)"),
        before_fraction=", ".join(BEFORE_FRACTION_ONLY), refused=", ".join(REFUSED_BASE))


@router.get("/llms.txt", response_class=PlainTextResponse)
async def llms(request: Request):
    return PlainTextResponse(manual_text(request), headers={"Cache-Control": "public, max-age=300"})


def _md(text: str) -> str:
    """Just enough Markdown for the manual: headings, code blocks, lists, bold, inline code."""
    out, para, code, items = [], [], [], []

    def inline(s):
        s = html.escape(s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
        return re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', s)

    def flush():
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>")
            items.clear()
        if code:
            out.append("<pre>" + html.escape("\n".join(code)) + "</pre>")
            code.clear()

    for line in text.splitlines():
        if line.startswith("    ") or (code and line.strip() == ""):
            if para or items:
                flush()
            code.append(line[4:])
            continue
        if code:
            flush()
        if line.startswith("# "):
            flush(); out.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.startswith("## "):
            flush(); out.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("- "):
            if para:
                flush()
            items.append(line[2:])
        elif line.startswith("  ") and items:
            items[-1] += " " + line.strip()
        elif not line.strip():
            flush()
        else:
            para.append(line.strip())
    flush()
    return "\n".join(out)


@router.get("/api", response_class=HTMLResponse)
async def manual_page(request: Request):
    return render(request, "manual.html", here="api", html=_md(manual_text(request)))


@router.get("/tworooms.py")
async def client_file(request: Request):
    src = CLIENT.read_text()
    src = src.replace('DEFAULT_SERVER = "http://127.0.0.1:8377"', f'DEFAULT_SERVER = "{base_url(request)}"', 1)
    return Response(src, media_type="text/x-python; charset=utf-8",
                    headers={"Content-Disposition": 'inline; filename="tworooms.py"'})


# ---------------------------------------------------------------- images for pages and previews

@router.get("/example/{what}")
async def example_image(request: Request, what: str):
    imgs = request.app.state.images
    if what == "picture.png":
        data = await run_in_threadpool(imgs.picture, EXAMPLE["picture"], 2, EXAMPLE["word"], "example", 400)
    elif what == "build.png":
        data = await run_in_threadpool(imgs.framed_board, EXAMPLE["build"], 400)
    elif what == "og.jpg":
        res = compare(EXAMPLE["picture"], EXAMPLE["build"])
        data = await run_in_threadpool(imgs.og_pair, EXAMPLE["picture"], 2, EXAMPLE["word"], "example", EXAMPLE["build"],
                                       "Two Rooms", f"one sees the picture, one builds it from words alone · {res['score']}")
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
    else:
        return Response(status_code=404)
    return Response(data, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/og/{kind}/{oid}.jpg")
async def og_image(request: Request, kind: str, oid: str):
    hall = request.app.state.hall
    imgs = request.app.state.images
    if kind == "letter":
        l = hall.letter_view(None, oid)
        row = hall.letter(oid)
        title = f"A letter by {l['describer']} · level {l['level']}, {l['level_name']}"
        if l["status"] == "closed" and l.get("results"):
            best = max(l["results"], key=lambda r: r["score"])
            pic = hall.picture(row["picture_id"])
            data = await run_in_threadpool(imgs.og_pair, D.loads(pic["shapes"]), row["level"], row["word"], pic["id"],
                                           best["shapes"], title, f"best of {len(l['results'])}: {best['score']} by {best['builder']}")
        else:
            data = await run_in_threadpool(imgs.og_letter, l.get("text") or "", "Two Rooms",
                                           f"{title} · {l['builds_submitted']} built")
    elif kind == "round":
        r = hall.round_view(None, oid)
        rnd = hall.one("SELECT * FROM rounds WHERE id=?", oid)
        pic = hall.picture(rnd["picture_id"])
        data = await run_in_threadpool(imgs.og_pair, D.loads(pic["shapes"]), rnd["level"], rnd["word"], pic["id"],
                                       r["result"]["build_shapes"], f"{r['describer']} described, {r['builder']} built",
                                       f"level {r['level']}, {r['level_name']} · score {r['result']['score']}")
    elif kind == "match":
        m = hall.match_state(None, oid)
        if m["finished_rounds"]:
            last = m["finished_rounds"][-1]
            rnd = hall.one("SELECT * FROM rounds WHERE id=?", last["round"])
            pic = hall.picture(rnd["picture_id"])
            b = hall.one("SELECT * FROM builds WHERE id=?", rnd["build_id"])
            data = await run_in_threadpool(imgs.og_pair, D.loads(pic["shapes"]), rnd["level"], rnd["word"], pic["id"],
                                           D.loads(b["shapes"]), " and ".join(m["players"]),
                                           f"round {last['n']} of {m['rounds']} · score {last['score']}")
        else:
            data = await run_in_threadpool(imgs.og_letter, m["waiting_sentence"] + " One of you sees a picture; the other "
                                           "rebuilds it from words alone.", "Two Rooms · a live match", " and ".join(m["players"]))
    else:
        return Response(status_code=404)
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=600"})
