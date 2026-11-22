"""Two fresh people use the web pages only: callsigns, a letter, an open seat, a live round with live updates.

    uv run python scratch/web_flow.py [--width 390]
Screenshots of each step go to scratch/shots/flow-*.png.
"""
import argparse
import random
import time

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("--server", default="http://127.0.0.1:8377")
ap.add_argument("--width", type=int, default=390)
args = ap.parse_args()
S = args.server
tag = random.randrange(10 ** 5)
ok = []


def check(name, cond, detail=""):
    ok.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))


def shot(page, name):
    page.screenshot(path=f"scratch/shots/flow-{name}-{args.width}.png", full_page=True)


with sync_playwright() as pw:
    br = pw.chromium.launch()
    errs = []

    def person():
        ctx = br.new_context(viewport={"width": args.width, "height": 900})
        p = ctx.new_page()
        p.on("pageerror", lambda e: errs.append(str(e)))
        return p

    a = person()
    t0 = time.time()
    a.goto(S + "/")
    a.fill("input[name=callsign]", f"ana{tag}")
    a.click("button:has-text(\"Start playing\")")
    check("callsign from the hall shows the key once", "There is no way to recover a lost key" in a.content())
    a.click("text=Continue")
    a.click("text=Describe a picture")
    a.check("input[name=level][value='2']")
    a.click("button:has-text(\"Get a picture\")")
    check("a picture with its word", "this letter's word is" in a.content() and a.locator("img[alt='the picture to describe']").count() == 1)
    a.fill("#text", "Blocks: a red one 3 units wide")
    check("the counter warns before sending", "will be refused" in a.locator("#counter").inner_text())
    a.click("button:has-text(\"Send the letter\")")
    check("refused, with the text kept", "digit" in a.content() and "3 units" in a.input_value("#text"))
    a.fill("#text", "Blocks: a red one along the bottom, a third of the board wide, touching the left edge.")
    a.click("button:has-text(\"Send the letter\")")
    check("sent: the letter page says it is open", "Your letter is open" in a.content())
    shot(a, "letter-sent")
    a.click("nav >> text=live")
    with a.expect_navigation(url="**/m/*"):
        a.click("form[action='/m/new'] button")
    mid = a.url.rstrip("/").split("/")[-1]
    check("an invitation, waiting", "Waiting for the invited player" in a.content() and f"/m/{mid}" in a.content())
    print(f"  (ana was playing within {time.time() - t0:.1f} s of arriving)")

    b = person()
    b.goto(S + f"/m/{mid}")
    check("the link explains what this is", "is waiting for someone to play with" in b.content())
    shot(b, "invited")
    b.fill("input[name=callsign]", f"ben{tag}")
    b.click("button:has-text(\"Start playing\")")
    b.click("text=Continue")
    with b.expect_navigation():
        b.click("button:has-text(\"Take the seat\")")
    check("ben describes first and sees the picture", "Your move: describe the picture" in b.content()
          and b.locator("img[alt='the picture to describe']").count() == 1)
    a.wait_for_selector("#board", timeout=35000)
    check("ana's page turned into the builder's room by itself", "you are the <b>builder</b>" in a.content())
    b.fill("#saytext", "A red block low on the left, a third of the board wide, a fifth tall.")
    b.click("#sayform button")
    a.wait_for_selector("#chat li", timeout=35000)
    check("ben's words reach ana without a reload", "a third of the board wide" in a.locator("#chat").inner_text())
    check("ana's page says it is her move", "Your move" in a.locator("#waiting").inner_text())
    a.locator("#board").scroll_into_view_if_needed()
    box = a.locator("#board").bounding_box()
    sx = box["width"] / 10.75
    px = lambda x, y: (box["x"] + (x + 0.55) * sx, box["y"] + (10 - y + 0.15) * sx)
    a.mouse.move(*px(0, 0))
    a.mouse.down()
    a.mouse.move(*px(3.33, 2), steps=5)
    a.mouse.up()
    a.wait_for_timeout(600)
    check("ana drew a block", "saved · 1 shape" in a.locator("#status").inner_text(), a.locator("#status").inner_text())
    shot(a, "builder")
    with a.expect_navigation(url="**/round/*"):
        a.click("#submitbtn")
    check("submit shows the round's result", "described" in a.content() and "cells differ" in a.content())
    shot(a, "round")
    b.wait_for_timeout(1500)
    b.reload()
    check("round 2 has started for ben, now the builder", "you are the <b>builder</b>" in b.content())
    check("no JavaScript errors", not errs, errs)
    br.close()
print(f"{sum(ok)} of {len(ok)} passed")
