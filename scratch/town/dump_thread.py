"""Save a town thread (every post, depth first) as JSON, for parse_fixtures.py.

    python3 scratch/town/dump_thread.py AT_URI OUT.json
"""
import json, sys, urllib.request, urllib.parse
API = "https://api.delve.town/xrpc/"
def get(m, **p):
    with urllib.request.urlopen(urllib.request.Request(API + m + "?" + urllib.parse.urlencode(p), headers={"User-Agent": "reader/0.1"}), timeout=30) as r:
        return json.load(r)
t = get("town.delve.feed.getPostThread", uri=sys.argv[1], depth=50, parentHeight=0)["thread"]
out = []
def walk(n, d=0):
    if "post" not in n: return
    p = n["post"]; out.append({"depth": d, "handle": p["author"]["handle"], "uri": p["uri"], "at": p["record"].get("createdAt"), "text": p["record"].get("text", ""), "facets": p["record"].get("facets")})
    for r in n.get("replies", []): walk(r, d + 1)
walk(t)
json.dump(out, open(sys.argv[2], "w"), indent=1, ensure_ascii=False)
print(len(out), "posts")
