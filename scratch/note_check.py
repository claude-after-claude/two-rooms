"""The builder's note in a real browser: the live word count, and an over-long note kept on the page, not submitted.

    uv run python scratch/note_check.py [--server http://127.0.0.1:8377]
"""
import argparse
import random

import httpx
from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("--server", default="http://127.0.0.1:8377")
ap.add_argument("--shot", default="scratch/shots/note-over.png")
args = ap.parse_args()
S = args.server
tag = random.randrange(10 ** 6)
key = lambda name: httpx.post(S + "/api/players", json={"callsign": name}).json()["key"]
kd, kb = key(f"nd{tag}"), key(f"nb{tag}")
H = lambda k: {"Authorization": "Bearer " + k}
lid = httpx.post(S + "/api/letters", json={"level": 1}, headers=H(kd)).json()["letter"]
httpx.post(S + f"/api/letters/{lid}/send", json={"text": "two blocks"}, headers=H(kd))
bid = httpx.post(S + f"/api/letters/{lid}/builds", headers=H(kb)).json()["build"]
httpx.post(S + f"/api/builds/{bid}/place", json={"shape": "rect", "color": "red", "x": 1, "y": 1, "w": 2, "h": 2},
           headers=H(kb))
status = lambda: httpx.get(S + f"/api/builds/{bid}", headers=H(kb)).json()["status"]

with sync_playwright() as p:
    br = p.chromium.launch()
    ctx = br.new_context(viewport={"width": 420, "height": 900})
    ctx.add_cookies([{"name": "tr_key", "value": kb, "url": S}])
    page = ctx.new_page()
    page.goto(f"{S}/build/{bid}")
    count = page.locator("#notecount")
    print("empty:", count.inner_text())
    page.fill("#note", "a bit-right of centre/left")
    print("six words:", count.inner_text())
    page.fill("#note", " ".join(["word"] * 61))
    print("sixty-one:", count.inner_text(), "| over:", "over" in (count.get_attribute("class") or ""))
    page.click("#submitbtn")
    page.wait_for_timeout(800)
    print("after submit click: url", page.url.removeprefix(S), "| error shown:", page.locator("#noteerr").is_visible(),
          "| status", status())
    print("error:", page.locator("#noteerr").inner_text())
    page.screenshot(path=args.shot, full_page=True)
    page.fill("#note", " ".join(["word"] * 60))
    page.click("#submitbtn")
    page.wait_for_url(f"**/letter/{lid}**")
    print("sixty: landed on", page.url.removeprefix(S), "| status", status())
    br.close()
