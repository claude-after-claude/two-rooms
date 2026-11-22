"""Screenshot every page at phone and desktop widths, as different viewers.

    uv run python scratch/shots.py [--only NAME,...] [--widths 390,1280]
Reads ids from the dev db and keys from scratch/seed_out.json. Writes scratch/shots/<name>-<width>.png.
"""
import argparse
import json
import sqlite3
from pathlib import Path

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("--server", default="http://127.0.0.1:8377")
ap.add_argument("--db", default="/var/tmp/tworooms-dev/dev.sqlite")
ap.add_argument("--only", default="")
ap.add_argument("--widths", default="390,1280")
ap.add_argument("--out", default="scratch/shots")
args = ap.parse_args()
_raw = Path("scratch/seed_out.json").read_text()
seed = json.loads(_raw[_raw.index("\n{\n") + 1:] if not _raw.startswith("{") else _raw)
keys = seed["keys"]
db = sqlite3.connect(args.db)
one = lambda q, *a: db.execute(q, a).fetchone()[0]

closed = one("SELECT l.id FROM letters l WHERE status='closed' AND (SELECT COUNT(*) FROM builds b WHERE b.letter_id=l.id AND status='submitted')>=3 ORDER BY level DESC LIMIT 1")
open_ = one("SELECT id FROM letters WHERE status='open' ORDER BY level DESC LIMIT 1")
building = one("SELECT id FROM builds WHERE status='building' AND letter_id IS NOT NULL LIMIT 1")
builder = one("SELECT p.callsign FROM builds b JOIN players p ON p.id=b.builder_id WHERE b.id=?", building)
rnd = one("SELECT id FROM rounds WHERE status='finished' ORDER BY n DESC LIMIT 1")
playing = seed["live_playing"]
pdesc = one("SELECT p.callsign FROM rounds r JOIN players p ON p.id=r.describer_id WHERE r.match_id=? AND r.status='playing'", playing)
pbuild = one("SELECT p.callsign FROM rounds r JOIN players p ON p.id=r.builder_id WHERE r.match_id=? AND r.status='playing'", playing)
opener = one("SELECT describer_id FROM letters WHERE id=?", open_)
open_owner = one("SELECT callsign FROM players WHERE id=?", opener)

PAGES = [
    ("hall-anon", "/", None),
    ("hall-alice", "/", "alice"),
    ("start", "/start", None),
    ("describe", "/describe", "alice"),
    ("draft", f"/describe/{seed['draft']}", "alice"),
    ("build-list", "/build", "bob"),
    ("build-page", f"/build/{building}", builder),
    ("letter-closed", f"/letter/{closed}", None),
    ("letter-open-anon", f"/letter/{open_}", None),
    ("letter-open-owner", f"/letter/{open_}", open_owner),
    ("live", "/live", "alice"),
    ("match-finished", f"/m/{seed['live_finished']}", None),
    ("match-describer", f"/m/{playing}", pdesc),
    ("match-builder", f"/m/{playing}", pbuild),
    ("match-watcher", f"/m/{playing}", None),
    ("invite-guest", f"/m/{seed['invite']}", None),
    ("invite-owner", f"/m/{seed['invite']}", "eve"),
    ("round", f"/round/{rnd}", None),
    ("wall", "/wall", None),
    ("profile", "/p/alice", None),
    ("manual", "/api", None),
    ("notfound", "/letter/nosuchthing", None),
]
only = set(filter(None, args.only.split(",")))
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for w in map(int, args.widths.split(",")):
        for name, path, who in PAGES:
            if only and name not in only:
                continue
            ctx = browser.new_context(viewport={"width": w, "height": 900 if w > 600 else 844}, device_scale_factor=1)
            if who:
                ctx.add_cookies([{"name": "tr_key", "value": keys[who], "url": args.server}])
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.goto(args.server + path, wait_until="networkidle" if "match" not in name and "invite" not in name else "load")
            page.wait_for_timeout(600)
            page.screenshot(path=str(out / f"{name}-{w}.png"), full_page=True)
            sw = page.evaluate("document.documentElement.scrollWidth")
            print(f"{name}-{w}: {path} as {who or 'anonymous'}" + (f"  HORIZONTAL SCROLL {sw}" if sw > w else "")
                  + (f"  JS ERRORS {errors}" if errors else ""))
            ctx.close()
    browser.close()
