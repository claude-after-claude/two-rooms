"""Say in words where a build lost the most: the colour behind most of the differing cells, and that colour's
shapes from both lists side by side."""
from .config import COLORS, COLOR_INDEX
from .score import rasterise


def _n(v) -> str:
    return f"{float(v):g}"


def _at(x, y) -> str:
    return f"{'at the left edge' if x == 0 else 'at ' + _n(x) + ' across'}, {'on the bottom edge' if y == 0 else _n(y) + ' up'}"


def in_words(s: dict) -> str:
    if s["shape"] == "rect":
        w, h = s["w"], s["h"]
        kind = "square" if w == h else ("bar" if max(w, h) >= 3 * min(w, h) else "block")
        size = f"{_n(w)} on a side" if w == h else f"{_n(w)} wide and {_n(h)} tall"
        return f"a {kind} {size}, its lower left corner {_at(s['x'], s['y'])}"
    if s["shape"] == "ellipse":
        if s["rx"] == s["ry"]:
            return f"a circle {_n(2 * s['rx'])} across, centred at {_n(s['cx'])} across, {_n(s['cy'])} up"
        return (f"an oval {_n(2 * s['rx'])} wide and {_n(2 * s['ry'])} tall, centred at {_n(s['cx'])} across, "
                f"{_n(s['cy'])} up")
    pts = "; ".join(f"{_n(x)} across, {_n(y)} up" for x, y in s["points"])
    return f"a triangle with corners at {pts}"


def _centre(s):
    from .shapes import bbox
    x0, y0, x1, y1 = bbox(s)
    return (x0 + x1) / 2, (y0 + y1) / 2


def _pairs(mine, theirs):
    """Pair each of the builder's shapes of one colour with the picture's nearest one (same kind preferred)."""
    costs = []
    for i, m in enumerate(mine):
        for j, t in enumerate(theirs):
            (ax, ay), (bx, by) = _centre(m), _centre(t)
            costs.append((((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 + (3 if m["shape"] != t["shape"] else 0), i, j))
    used_m, used_t, out = set(), set(), []
    for _, i, j in sorted(costs):
        if i not in used_m and j not in used_t:
            used_m.add(i), used_t.add(j)
            out.append((mine[i], theirs[j]))
    out += [(m, None) for i, m in enumerate(mine) if i not in used_m]
    out += [(None, t) for j, t in enumerate(theirs) if j not in used_t]
    return out


def loss(picture: list[dict], build: list[dict]) -> dict | None:
    from .score import shape_mask
    a, b = rasterise(picture), rasterise(build)
    differ = a != b
    total = int(differ.sum())
    if total == 0:
        return None
    best, best_n = None, -1
    for c in COLORS:
        k = COLOR_INDEX[c]
        n = int((differ & ((a == k) | (b == k))).sum())
        if n > best_n:
            best, best_n = c, n
    mine = [s for s in build if s["color"] == best]
    theirs = [s for s in picture if s["color"] == best]

    def cost(pair):
        m, t = pair
        mask = None
        for s in pair:
            if s is not None:
                mask = shape_mask(s) if mask is None else (mask | shape_mask(s))
        return int((differ & mask).sum())

    m, t = max(_pairs(mine, theirs), key=cost)
    head = f"Most of the difference is in {best}: {best_n} of the {total} cells that differ involve it."
    one_each = len(mine) == 1 and len(theirs) == 1
    if m is not None and t is not None:
        lead = " Yours" if one_each else f" The {best} piece that missed most: yours"
        body = f"{lead} is {in_words(m)}; the picture's is {in_words(t)}."
    elif t is not None:
        body = f" The picture has {in_words(t)}, and you built nothing like it."
    else:
        body = f" You built {in_words(m)}, and the picture has nothing like it."
    if len(mine) != len(theirs) and m is not None and t is not None:
        body += f" The picture has {len(theirs)} {best} shape{'s' if len(theirs) != 1 else ''}; you built {len(mine)}."
    return {"colour": best, "cells": best_n, "cells_differ": total, "sentence": head + body,
            "yours": [in_words(s) for s in mine], "picture": [in_words(s) for s in theirs]}
