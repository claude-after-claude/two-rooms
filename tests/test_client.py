"""The command-line client, run against a test server, the way an agent would use it."""
import importlib.util
import re
import threading
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).parent.parent


def load_client():
    spec = importlib.util.spec_from_file_location("tworooms_client", ROOT / "client" / "tworooms.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Player:
    def __init__(self, base, home: Path, capsys):
        self.mod = load_client()
        self.mod.CONFIG = home / "tworooms.json"
        self.base, self.out_dir, self.capsys = base, home / "images", capsys

    def __call__(self, *argv, ok=True) -> str:
        self.capsys.readouterr()
        code = self.mod.main(["--server", self.base, "--out", str(self.out_dir), *argv])
        out = self.capsys.readouterr()
        text = out.out + out.err
        assert (code == 0) == ok, f"{argv} -> {code}\n{text}"
        return text


def test_client_plays_letters_and_live(server, tmp_path, capsys):
    base, app = server
    alice = Player(base, tmp_path / "a", capsys)
    bob = Player(base, tmp_path / "b", capsys)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()

    assert "You are alice" in alice("callsign", "alice", "--kind", "agent")
    assert "You are bob" in bob("callsign", "bob")
    refused = alice("callsign", "carol", ok=False)
    assert "already holds alice's key" in refused and "TWOROOMS_CONFIG" in refused
    assert "You are alice" in alice("me"), "a refused callsign must leave the key in place"
    assert "next:" in alice("hall")

    out = alice("describe", "--level", "1")
    letter = re.search(r"Letter (\w+):", out).group(1)
    picture = Path(re.search(r"saved at\n\s+(\S+)", out).group(1))
    assert picture.exists() and picture.read_bytes()[:4] == b"\x89PNG"
    assert "budget: 25 words" in out
    assert "past nine" in alice("send", letter, "the red one is twelve wide", ok=False)
    checked = alice("send", letter, "Five quarters of the board.", "--check")
    assert "Would be refused" in checked and "counting in fractions" in checked
    assert "would be accepted" in alice("send", letter, "Two blocks, both red.", "--check").lower()
    assert app.state.hall.letter(letter)["status"] == "draft", "--check must not send"
    words = tmp_path / "a" / "words.txt"
    words.write_text("Two blocks. Red, low on the left, a third of the board wide. Blue square, high right.")
    assert "is open" in alice("send", letter, "--file", str(words))

    assert letter in bob("letters")
    out = bob("take", letter)
    build = re.search(r"Build (\w+) of letter", out).group(1)
    assert "a third of the board wide" in out
    out = bob("place", build, "rect", "red", "1", "1", "3.3", "2")
    assert "Placed 1. rect red 1 1 3.25 2" in out and out.count("Rounded to steps of 1/8") == 1
    assert len(out.strip().splitlines()) == 2, "place prints one line, and one for the rounding"
    bob("place", build, "ellipse", "blue", "7", "8", "1")
    assert "Removed ellipse blue 7 8 1 1" in bob("undo", build)
    out = bob("place", build, "triangle", "green", "6", "6", "9", "6", "6", "9,", "rect", "black", "0", "0", "1", "1")
    assert "Placed 2. triangle green" in out and "Placed 3. rect black 0 0 1 1" in out and "3 on the board" in out
    out = bob("shapes", build, "--set", "rect red 1 1 3.25 2, triangle green 6 6 9 6 6 9")
    assert "now holds 2 shapes" in out
    out = bob("board", build)
    assert Path(re.search(r"saved at\n\s+(\S+)", out).group(1)).exists()
    assert "error" in bob("place", build, "rect", "pink", "1", "1", "1", "1", ok=False)
    out = bob("check", build)
    assert "Check 1 of 2" in out and "In place:" in out and "Slid to fit:" in out and "1 check left" in out
    out = bob("submit", build, "--note", "the blue square was a guess")
    assert re.search(r"In place: +[a-z ]+ · \d+%", out) and re.search(r"Slid to fit: +[a-z ]+ · \d+%", out)
    assert "Most of the difference is in" in out and "You are the first to build this letter" in out
    assert "The picture's true shapes" in out
    assert "the blue square was a guess" in alice("letter", letter)

    # live, with the long-poll
    out = alice("invite", "--rounds", "1")
    match = re.search(r"Match (\w+) created", out).group(1)
    assert "joined" not in alice("match", match)
    out = bob("join", match)
    assert "You are the describer" in out and "this round's word is" in out
    word = re.search(r"this round's word is (\w+)", out).group(1)
    assert word in bob("look", match)
    nxt = bob("say", match, "Twelve of them.", ok=False)
    assert "past nine" in nxt
    assert "POST /api" not in bob("match", match) and f"tworooms.py say {match}" in bob("match", match)
    caught_up = alice("match", match, "--wait", "5")
    assert "new · joined: bob" in caught_up and "round 1 started" in caught_up, "news since alice last looked comes at once"
    got = {}

    def wait():
        t = time.time()
        got["out"] = alice("match", match, "--wait", "20")
        got["t"] = time.time() - t

    th = threading.Thread(target=wait)
    th.start()
    time.sleep(0.5)
    bob("say", match, "One red block filling the lower half of the board.")
    th.join()
    assert got["t"] < 10 and "*bob (describer" in got["out"] and "You are the builder" in got["out"]
    assert word in alice("look", match)
    alice("place", match, "rect", "red", "0", "0", "10", "5")
    out = alice("submit", match)
    assert "In place:" in out and "That was the last round" in out
    assert "finished" in bob("match", match)
    assert "callsign" in Player(base, tmp_path, capsys)("me", ok=False)


def test_served_client_points_at_its_server(server):
    base, app = server
    src = httpx.get(base + "/tworooms.py").text
    assert f'DEFAULT_SERVER = "{base}"' in src
    compile(src, "tworooms.py", "exec")
    manual = httpx.get(base + "/llms.txt").text
    for w in ("twelve", "dozen", "eleventh", "four, five, six, seven, eight, nine", "Authorization: Bearer"):
        assert w in manual
