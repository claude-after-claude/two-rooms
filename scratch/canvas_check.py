"""Drive the builder's canvas in a real browser and check what reaches the server.

    uv run python scratch/canvas_check.py [--width 1280]
Makes a fresh player and letter build on the dev server, draws with the mouse, then reads the build via the API.
"""
import argparse
import json

import httpx
from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("--server", default="http://127.0.0.1:8377")
ap.add_argument("--width", type=int, default=1280)
ap.add_argument("--shot", default="scratch/shots/canvas-after.png")
args = ap.parse_args()
S = args.server


def player(name):
    r = httpx.post(S + "/api/players", json={"callsign": name})
    if r.status_code == 409:
        raise SystemExit("rerun with a fresh db or change names")
    return r.json()["key"]


import random
tag = random.randrange(10 ** 6)
kd, kb = player(f"cd{tag}"), player(f"cb{tag}")
H = lambda k: {"Authorization": "Bearer " + k}
lid = httpx.post(S + "/api/letters", json={"level": 6}, headers=H(kd)).json()["letter"]
httpx.post(S + f"/api/letters/{lid}/send", json={"text": "a house"}, headers=H(kd))
bid = httpx.post(S + f"/api/letters/{lid}/builds", headers=H(kb)).json()["build"]


def state():
    return httpx.get(S + f"/api/builds/{bid}", headers=H(kb)).json()["shapes"]


results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": args.width, "height": 1000}, has_touch=args.width < 600)
    ctx.add_cookies([{"name": "tr_key", "value": kb, "url": S}])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(S + f"/build/{bid}")
    box = page.locator("#board").bounding_box()
    # viewBox is -0.55 -0.15 10.75 10.75: board x in [0,10] maps to pixels
    sx = box["width"] / 10.75

    def px(x, y):
        return box["x"] + (x + 0.55) * sx, box["y"] + (10 - y + 0.15) * sx

    def drag(a, b):
        page.mouse.move(*px(*a))
        page.mouse.down()
        page.mouse.move(*px((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), steps=4)
        page.mouse.move(*px(*b), steps=4)
        page.mouse.up()

    def settle():
        page.wait_for_timeout(700)

    drag((2, 1), (5, 3))
    settle()
    s = state()
    check("drag draws a red rect, snapped to the quarter grid", s == [{"shape": "rect", "color": "red", "x": 2, "y": 1, "w": 3, "h": 2}], s)
    page.click("[data-color=blue]")
    page.click("[data-tool=ellipse]")
    drag((6, 6), (9, 8))
    settle()
    s = state()
    check("ellipse from its box", len(s) == 2 and s[1] == {"shape": "ellipse", "color": "blue", "cx": 7.5, "cy": 7, "rx": 1.5, "ry": 1}, s)
    page.click("[data-color=green]")
    page.click("[data-tool=triangle]")
    for p in ((1, 6), (4, 6), (1, 9)):
        page.mouse.click(*px(*p))
    settle()
    s = state()
    check("three clicks make a triangle", len(s) == 3 and s[2]["shape"] == "triangle" and s[2]["points"] == [[1, 6], [4, 6], [1, 9]], s)
    page.click("[data-tool=select]")
    page.mouse.click(*px(3, 2))
    drag((3, 2), (4, 2.5))
    settle()
    s = state()
    check("move tool drags the rect", s[0]["x"] == 3 and s[0]["y"] == 1.5, s[0])
    drag((6, 3.5), (7, 4.5))   # the rect's top-right handle is at (6, 3.5)
    settle()
    s = state()
    check("handle resizes the rect", s[0] == {"shape": "rect", "color": "red", "x": 3, "y": 1.5, "w": 4, "h": 3}, s[0])
    inp = page.locator("#fields input").first
    inp.fill("2.125")
    inp.press("Tab")
    settle()
    s = state()
    check("typing a value sets it (to 1/8)", s[0]["x"] == 2.125, s[0])
    page.keyboard.press("Control+z")
    settle()
    s = state()
    check("undo takes the last change back", s[0]["x"] == 3, s[0])
    page.click("#down")
    settle()
    check("reorder is a no-op at the bottom", state()[0]["color"] == "red")
    page.locator("#layers li").nth(2).click()
    page.click("#down")
    settle()
    s = state()
    check("send the triangle backward", s[1]["shape"] == "triangle", [x["shape"] for x in s])
    page.click("#del")
    settle()
    s = state()
    check("delete removes it", len(s) == 2 and all(x["shape"] != "triangle" for x in s), s)
    page.fill("#note", "the roof was hard")
    page.click("#submitbtn")
    page.wait_for_load_state("load")
    page.wait_for_timeout(500)
    check("submit lands on the letter page with my result", f"/letter/{lid}" in page.url and "the roof was hard" in page.content(), page.url)
    page.screenshot(path=args.shot, full_page=True)
    check("no JavaScript errors", not errors, errors)
    browser.close()
print(json.dumps({"passed": sum(ok for _, ok in results), "of": len(results)}))
