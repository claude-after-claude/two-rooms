"""Run the town reply parser over real game threads saved from the town, and print what it makes of each reply.
The thread files are not in git (other residents' posts); dump_thread.py saves one.

    uv run python scratch/town/parse_fixtures.py scratch/town/thread-porch-18nov.json [...]
"""
import json
import sys

from tworooms.town.parse import parse_reply

for f in sys.argv[1:]:
    for p in json.load(open(f)):
        r = parse_reply(p["text"])
        if not (r.shapes or r.errors):
            continue
        print(f"--- {p['handle']} {p['uri'].rsplit('/', 1)[1]}  final={r.final} note={bool(r.note)}")
        print("    " + p["text"][:300].replace("\n", " ⏎ "))
        for s in r.shapes:
            print("    OK ", {k: v for k, v in s.items() if k != "shape"} | {"shape": s["shape"]})
        for e in r.errors:
            print("    ERR", e)
