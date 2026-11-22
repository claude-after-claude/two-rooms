"""Screenshots of the pages changed after the first play.

    uv run python scratch/shots2.py
Reads the real games on 8377 without writing to them; makes a builder with two checks on the seeded 8378.
"""
import random

import httpx
from playwright.sync_api import sync_playwright

REAL, DEV = "http://127.0.0.1:8377", "http://127.0.0.1:8378"
tag = random.randrange(10 ** 5)
key = httpx.post(DEV + "/api/players", json={"callsign": f"chk{tag}"}).json()["key"]
H = {"Authorization": f"Bearer {key}"}
letters = httpx.get(DEV + "/api/letters", headers=H).json()["letters"]
lid = letters[0]["letter"]
bid = httpx.post(DEV + f"/api/letters/{lid}/builds", headers=H).json()["build"]
httpx.put(DEV + f"/api/builds/{bid}/shapes", headers=H, json=[{"shape": "rect", "color": "blue", "x": 2, "y": 2, "w": 3, "h": 3}])
httpx.post(DEV + f"/api/builds/{bid}/check", headers=H)
httpx.put(DEV + f"/api/builds/{bid}/shapes", headers=H, json=[{"shape": "rect", "color": "blue", "x": 2, "y": 2, "w": 3, "h": 3},
                                                              {"shape": "ellipse", "color": "red", "cx": 7, "cy": 7, "rx": 1.5, "ry": 1}])
httpx.post(DEV + f"/api/builds/{bid}/check", headers=H)

pages = [
    ("real-hall", REAL + "/", None),
    ("real-lamp", REAL + "/letter/vomatum", None),
    ("real-blocks", REAL + "/letter/kibujov", None),
    ("real-wall", REAL + "/wall", None),
    ("dev-build-checks", DEV + f"/build/{bid}", key),
]
with sync_playwright() as pw:
    br = pw.chromium.launch()
    for w in (390, 1280):
        for name, url, k in pages:
            ctx = br.new_context(viewport={"width": w, "height": 900})
            if k:
                ctx.add_cookies([{"name": "tr_key", "value": k, "url": DEV}])
            page = ctx.new_page()
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.goto(url, wait_until="networkidle")
            if name == "real-lamp":
                page.locator("details summary").first.click()
                page.wait_for_timeout(500)
            page.screenshot(path=f"scratch/shots/{name}-{w}.png", full_page=True)
            sw = page.evaluate("document.documentElement.scrollWidth")
            print(name, w, "scroll" if sw > w else "", errs or "")
            ctx.close()
    # submit with the canvas page and land on the letter page
    ctx = br.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_cookies([{"name": "tr_key", "value": key, "url": DEV}])
    page = ctx.new_page()
    page.goto(DEV + f"/build/{bid}")
    with page.expect_navigation():
        page.click("#submitbtn")
    page.wait_for_timeout(800)
    page.screenshot(path="scratch/shots/dev-after-submit-1280.png", full_page=True)
    print("after submit:", page.url)
    br.close()
