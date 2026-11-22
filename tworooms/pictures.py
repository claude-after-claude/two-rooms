"""Picture generators, one per level, deterministic from (level, seed), and the constraint checker they all obey."""
import math
import random

import numpy as np

from .config import BOARD, COLORS, LEVELS
from .score import owners
from . import figures
from .figures import E, R, T, pick, U
from .shapes import bbox

GAP_CELLS = 2          # shapes of one colour stay at least 0.25 units apart
MIN_RUN_CELLS = 6      # 0.75 units of visible extent in each direction
CELL = 0.125


# ---------------------------------------------------------------- shape helpers

def _clean(v: float):
    v = round(v, 6)
    return int(v) if float(v).is_integer() else v


def snap_shape(s: dict, grid: float) -> dict:
    q = lambda v: _clean(round(v / grid) * grid)
    if s["shape"] == "rect":
        x0, y0, x1, y1 = q(s["x"]), q(s["y"]), q(s["x"] + s["w"]), q(s["y"] + s["h"])
        return R(s["color"], x0, y0, _clean(max(grid, x1 - x0)), _clean(max(grid, y1 - y0)))
    if s["shape"] == "ellipse":
        return E(s["color"], q(s["cx"]), q(s["cy"]), max(grid, q(s["rx"])), max(grid, q(s["ry"])))
    return T(s["color"], *[(q(x), q(y)) for x, y in s["points"]])


# ---------------------------------------------------------------- the checker

def _max_run(mask: np.ndarray) -> int:
    """Longest run of True along rows."""
    padded = np.zeros((mask.shape[0], mask.shape[1] + 2), dtype=np.int8)
    padded[:, 1:-1] = mask
    d = np.diff(padded, axis=1)
    starts, ends = np.nonzero(d == 1), np.nonzero(d == -1)
    if len(starts[1]) == 0:
        return 0
    return int((ends[1] - starts[1]).max())


def _dilate(mask: np.ndarray, r: int) -> np.ndarray:
    out = mask.copy()
    for _ in range(r):
        grown = out.copy()
        grown[1:, :] |= out[:-1, :]
        grown[:-1, :] |= out[1:, :]
        grown[:, 1:] |= out[:, :-1]
        grown[:, :-1] |= out[:, 1:]
        grown[1:, 1:] |= out[:-1, :-1]
        grown[1:, :-1] |= out[:-1, 1:]
        grown[:-1, 1:] |= out[1:, :-1]
        grown[:-1, :-1] |= out[1:, 1:]
        out = grown
    return out


def _boxes_near(a: dict, b: dict, gap: float) -> bool:
    ax0, ay0, ax1, ay1 = bbox(a)
    bx0, by0, bx1, by1 = bbox(b)
    return not (ax1 + gap < bx0 or bx1 + gap < ax0 or ay1 + gap < by0 or by1 + gap < ay0)


def visibility_problems(shapes: list[dict], min_visible: float = 0.25, top=None, masks=None) -> list[str]:
    if top is None:
        top, masks = owners(shapes)
    out = []
    for i, m in enumerate(masks):
        area = int(m.sum())
        vis = top == i
        nvis = int(vis.sum())
        if area == 0:
            out.append(f"shape {i} has no area")
            continue
        if nvis < min_visible * area:
            out.append(f"shape {i} is only {100 * nvis / area:.0f}% visible")
            continue
        if _max_run(vis) < MIN_RUN_CELLS or _max_run(vis.T) < MIN_RUN_CELLS:
            out.append(f"shape {i} shows less than 0.75 units in some direction")
    return out


def colour_problems(shapes: list[dict], masks) -> list[str]:
    out = []
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            if shapes[i]["color"] != shapes[j]["color"]:
                continue
            if not _boxes_near(shapes[i], shapes[j], 0.5):
                continue
            if (_dilate(masks[i], GAP_CELLS) & masks[j]).any():
                out.append(f"shapes {i} and {j} are both {shapes[i]['color']} and touch")
    return out


def check(level: int, shapes: list[dict]) -> list[str]:
    """Every constraint a picture at this level must meet; an empty list means it is good."""
    lv = LEVELS[level]
    problems = []
    for i, s in enumerate(shapes):
        x0, y0, x1, y1 = bbox(s)
        if x0 < 0 or y0 < 0 or x1 > BOARD or y1 > BOARD:
            problems.append(f"shape {i} extends past the board")
        vals = (
            [v for p in s["points"] for v in p] if s["shape"] == "triangle"
            else [s[k] for k in (("x", "y", "w", "h") if s["shape"] == "rect" else ("cx", "cy", "rx", "ry"))]
        )
        if any(abs(v / lv.grid - round(v / lv.grid)) > 1e-9 for v in vals):
            problems.append(f"shape {i} is off the level's grid")
        if s["color"] not in COLORS:
            problems.append(f"shape {i} has an unknown colour")
    if problems:
        return problems
    top, masks = owners(shapes)
    problems += visibility_problems(shapes, 0.35 if level == 3 else 0.25, top, masks)
    problems += colour_problems(shapes, masks)
    kinds = [s["shape"] for s in shapes]
    n = len(shapes)
    overlaps = [[i != j and bool((masks[i] & masks[j]).any()) for j in range(n)] for i in range(n)]
    if level == 1:
        if kinds != ["rect", "rect"]:
            problems.append("level 1 is two rectangles")
        elif _boxes_near(shapes[0], shapes[1], 0.99):
            problems.append("the two blocks must be at least one unit apart")
    elif level == 2:
        if kinds != ["rect"] * 4:
            problems.append("level 2 is four rectangles")
        if any(any(r) for r in overlaps):
            problems.append("level 2 rectangles may not overlap")
    elif level == 3:
        if kinds != ["rect"] * 4:
            problems.append("level 3 is four rectangles")
        if not all(any(r) for r in overlaps):
            problems.append("every level 3 rectangle overlaps another")
    elif level == 4:
        if n != 5 or set(kinds) != {"rect", "ellipse"}:
            problems.append("level 4 is five rectangles and ellipses")
    elif level == 5:
        if n != 6 or set(kinds) != {"rect", "ellipse", "triangle"}:
            problems.append("level 5 is six shapes of all three kinds")
    elif level == 6:
        if not 6 <= n <= 9:
            problems.append("a figure has 6 to 9 shapes")
    elif level == 7:
        if n != 9 or set(kinds) != {"rect", "ellipse", "triangle"}:
            problems.append("level 7 is nine shapes of all kinds")
        if not all(sum(r) >= 2 for r in overlaps):
            problems.append("every level 7 shape overlaps at least two others")
    elif level == 8:
        if not 10 <= n <= 14:
            problems.append("a scene has 10 to 14 shapes")
    if level <= 4 and len({s["color"] for s in shapes}) != n:
        problems.append("colours repeat below level 5")
    return problems


# ---------------------------------------------------------------- random abstract shapes

class Retry(Exception):
    """This attempt can't be completed; the generator draws again."""


def _on(rng, lo, hi, grid):
    """A multiple of grid in [lo, hi]."""
    a, b = math.ceil(lo / grid - 1e-9), math.floor(hi / grid + 1e-9)
    if a > b:
        raise Retry
    return _clean(rng.randint(a, b) * grid)


def rand_rect(rng, c, grid, smin, smax, region=(0, 0, BOARD, BOARD)):
    w, h = _on(rng, smin, smax, grid), _on(rng, smin, smax, grid)
    rx0, ry0, rx1, ry1 = region
    x = _on(rng, max(0, rx0 - w / 2), min(BOARD - w, rx1 - w / 2), grid)
    y = _on(rng, max(0, ry0 - h / 2), min(BOARD - h, ry1 - h / 2), grid)
    return R(c, x, y, w, h)


def rand_ellipse(rng, c, grid, rmin, rmax, region=(0, 0, BOARD, BOARD)):
    rx, ry = _on(rng, rmin, rmax, grid), _on(rng, rmin, rmax, grid)
    rx0, ry0, rx1, ry1 = region
    cx = _on(rng, max(rx, rx0), min(BOARD - rx, rx1), grid)
    cy = _on(rng, max(ry, ry0), min(BOARD - ry, ry1), grid)
    return E(c, cx, cy, rx, ry)


def rand_triangle(rng, c, grid, smin, smax, region=(0, 0, BOARD, BOARD)):
    w, h = _on(rng, smin, smax, grid), _on(rng, smin, smax, grid)
    rx0, ry0, rx1, ry1 = region
    x0 = _on(rng, max(0, rx0 - w / 2), min(BOARD - w, rx1 - w / 2), grid)
    y0 = _on(rng, max(0, ry0 - h / 2), min(BOARD - h, ry1 - h / 2), grid)
    x1, y1 = x0 + w, y0 + h
    style = rng.choice(["right", "iso", "free"])
    if style == "right":
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        k = rng.randrange(4)
        pts = [corners[k], corners[(k + 1) % 4], corners[(k + 3) % 4]]
    elif style == "iso":
        side = rng.randrange(4)
        mx, my = _on(rng, x0 + w / 2, x0 + w / 2, grid / 2), _on(rng, y0 + h / 2, y0 + h / 2, grid / 2)
        mx, my = round(mx / grid) * grid, round(my / grid) * grid
        pts = [
            [(x0, y0), (x1, y0), (mx, y1)], [(x0, y1), (x1, y1), (mx, y0)],
            [(x0, y0), (x0, y1), (x1, my)], [(x1, y0), (x1, y1), (x0, my)],
        ][side]
    else:
        pts = [(_on(rng, x0, x1, grid), y0), (x1, _on(rng, y0, y1, grid)), (_on(rng, x0, x1, grid), y1)]
        if rng.random() < 0.5:
            pts = [(x0, _on(rng, y0, y1, grid)), (_on(rng, x0, x1, grid), y0), (_on(rng, x0, x1, grid), y1)]
    pts = [(_clean(x), _clean(y)) for x, y in pts]
    (ax, ay), (bx, by), (cx_, cy_) = pts
    area = abs((bx - ax) * (cy_ - ay) - (by - ay) * (cx_ - ax)) / 2
    if area < 0.3 * w * h:
        return None
    return T(c, *pts)


def _rand_shape(rng, kind, c, grid, size, region=(0, 0, BOARD, BOARD)):
    lo, hi = size
    if kind == "rect":
        return rand_rect(rng, c, grid, lo, hi, region)
    if kind == "ellipse":
        return rand_ellipse(rng, c, grid, max(grid, lo / 2), hi / 2, region)
    return rand_triangle(rng, c, grid, lo, hi, region)


def _overlaps(a: dict, b: dict) -> bool:
    from .score import shape_mask
    return _boxes_near(a, b, -0.01) and bool((shape_mask(a) & shape_mask(b)).any())


# ---------------------------------------------------------------- levels 1 to 5, 7

def gen1(rng):
    cols = rng.sample(COLORS, 2)
    shapes = []
    for c in cols:
        for _ in range(50):
            w, h = rng.randint(1, 5), rng.randint(1, 5)
            if w * h < 2:
                continue
            r = R(c, rng.randint(0, 10 - w), rng.randint(0, 10 - h), w, h)
            if all(not _boxes_near(r, o, 0.99) for o in shapes):
                shapes.append(r)
                break
        else:
            return None
    return shapes


def gen2(rng):
    cols = rng.sample(COLORS, 4)
    shapes = []
    for c in cols:
        for _ in range(80):
            w, h = rng.randint(1, 5), rng.randint(1, 5)
            if w * h < 2:
                continue
            r = R(c, rng.randint(0, 10 - w), rng.randint(0, 10 - h), w, h)
            if all(not _boxes_near(r, o, -0.01) for o in shapes):
                shapes.append(r)
                break
        else:
            return None
    return shapes


def gen3(rng):
    cols = rng.sample(COLORS, 4)
    shapes = [rand_rect(rng, cols[0], 0.5, 2, 5.5, (1.5, 1.5, 8.5, 8.5))]
    for c in cols[1:]:
        for _ in range(80):
            anchor = rng.choice(shapes)
            ax0, ay0, ax1, ay1 = bbox(anchor)
            r = rand_rect(rng, c, 0.5, 1.5, 5.5, (ax0, ay0, ax1, ay1))
            if _overlaps(r, anchor) and not visibility_problems(shapes + [r], 0.35):
                shapes.append(r)
                break
        else:
            return None
    return shapes


def _incremental(rng, kinds, colours, grid, size, region, min_visible=0.25, must_touch=False):
    shapes = []
    for kind, c in zip(kinds, colours):
        for _ in range(80):
            s = _rand_shape(rng, kind, c, grid, size, region)
            if s is None:
                continue
            if must_touch and shapes and not any(_overlaps(s, o) for o in shapes):
                continue
            if not visibility_problems(shapes + [s], min_visible):
                shapes.append(s)
                break
        else:
            return None
    return shapes


def gen4(rng):
    n_ell = rng.choice([2, 3])
    kinds = ["ellipse"] * n_ell + ["rect"] * (5 - n_ell)
    rng.shuffle(kinds)
    return _incremental(rng, kinds, rng.sample(COLORS, 5), 0.5, (1.5, 4.5), (0, 0, BOARD, BOARD))


def gen5(rng):
    kinds = ["rect", "rect", "ellipse", "ellipse", "triangle", "triangle"]
    rng.shuffle(kinds)
    colours = rng.sample(COLORS, 5)
    colours.append(rng.choice(colours))
    rng.shuffle(colours)
    return _incremental(rng, kinds, colours, 0.5, (1.5, 4.5), (0, 0, BOARD, BOARD))


def _assign_colours(rng, shapes):
    """Greedy colouring so that shapes that touch never share a colour."""
    _, masks = owners(shapes)
    n = len(shapes)
    near = [[False] * n for _ in range(n)]
    for i in range(n):
        di = _dilate(masks[i], GAP_CELLS)
        for j in range(n):
            if i != j and (di & masks[j]).any():
                near[i][j] = near[j][i] = True
    order = list(range(n))
    rng.shuffle(order)
    out = [None] * n
    for i in order:
        options = [c for c in COLORS if all(out[j] != c for j in range(n) if near[i][j])]
        if not options:
            return None
        used = {c for c in out if c}
        fresh = [c for c in options if c not in used]
        out[i] = rng.choice(fresh or options)
    for s, c in zip(shapes, out):
        s["color"] = c
    return shapes


def gen7(rng):
    kinds = ["rect"] * 3 + ["ellipse"] * 3 + ["triangle"] * 3
    rng.shuffle(kinds)
    shapes = _incremental(rng, kinds, ["black"] * 9, 0.25, (1.5, 4.75), (2.25, 2.25, 7.75, 7.75), must_touch=True)
    if shapes is None:
        return None
    return _assign_colours(rng, shapes)


# ---------------------------------------------------------------- figures (levels 6 and 8)

FIGURES = figures.TEMPLATES
SCENE_FIGURES = figures.SCENE_TEMPLATES


def _local_bbox(shapes):
    bs = [bbox(s) for s in shapes]
    return min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)


def _transform(shapes, s, mirror, box):
    """Scale by s, put the bounding box's corner at the origin, optionally mirror left-right, snap to quarters."""
    x0, y0, x1, _ = box
    fx = (lambda x: s * (x1 - x)) if mirror else (lambda x: s * (x - x0))
    fy = lambda y: s * (y - y0)
    q = lambda v: _clean(round(v * 4) / 4)
    out = []
    for sh in shapes:
        if sh["shape"] == "rect":
            xa, xb = sorted((q(fx(sh["x"])), q(fx(sh["x"] + sh["w"]))))
            ya, yb = q(fy(sh["y"])), q(fy(sh["y"] + sh["h"]))
            out.append(R(sh["color"], xa, ya, _clean(max(0.25, xb - xa)), _clean(max(0.25, yb - ya))))
        elif sh["shape"] == "ellipse":
            out.append(E(sh["color"], q(fx(sh["cx"])), q(fy(sh["cy"])), max(0.25, q(s * sh["rx"])), max(0.25, q(s * sh["ry"]))))
        else:
            out.append(T(sh["color"], *[(q(fx(x)), q(fy(y))) for x, y in sh["points"]]))
    return out


def figure(rng, name, box_w, box_h, lite, fill=(0.72, 1.0)):
    """Draw a template scaled to fit a box_w x box_h box (times a random fill factor), at the origin.
    Returns (shapes, bbox) or None."""
    tpl = FIGURES[name]
    state = rng.getstate()
    trial = tpl(rng, 0.8, lite)
    if trial is None:
        return None
    x0, y0, x1, y1 = _local_bbox(trial)
    f = U(rng, *fill)
    s = f * min(box_w / (x1 - x0), box_h / (y1 - y0))
    rng.setstate(state)
    shapes = tpl(rng, 1.0 / s, lite)
    if shapes is None:
        return None
    box = _local_bbox(shapes)
    s = f * min(box_w / (box[2] - box[0]), box_h / (box[3] - box[1]))
    mirror = rng.random() < 0.5
    placed = _transform(shapes, s, mirror, box)
    return placed, _local_bbox(placed)


def _shift(shapes, dx, dy):
    out = []
    for sh in shapes:
        if sh["shape"] == "rect":
            out.append(R(sh["color"], _clean(sh["x"] + dx), _clean(sh["y"] + dy), sh["w"], sh["h"]))
        elif sh["shape"] == "ellipse":
            out.append(E(sh["color"], _clean(sh["cx"] + dx), _clean(sh["cy"] + dy), sh["rx"], sh["ry"]))
        else:
            out.append(T(sh["color"], *[(_clean(x + dx), _clean(y + dy)) for x, y in sh["points"]]))
    return out


def gen6(rng, name=None):
    name = name or rng.choice(sorted(FIGURES))
    got = figure(rng, name, 9.5, 9.5, lite=False)
    if got is None:
        return None
    shapes, (x0, y0, x1, y1) = got
    dx = _on(rng, 0.25 - x0, BOARD - 0.25 - x1, 0.25)
    dy = _on(rng, 0.25 - y0, BOARD - 0.25 - y1, 0.25)
    return _shift(shapes, dx, dy)


def gen8(rng):
    gh = _on(rng, 1.25, 2.25, 0.25)
    ground = R(pick(rng, ["green", "green", "yellow"]), 0, 0, BOARD, gh)
    extras = rng.choice(["sky", "sun", "both"])
    sky = None
    if extras in ("sky", "both"):
        sky_h = _on(rng, 1.75, 2.75, 0.25)
        sky = R("blue", 0, BOARD - sky_h, BOARD, sky_h)
    backdrop = ([sky] if sky else []) + [ground]
    halves = [(0.25, 4.85), (5.15, 9.75)]
    rng.shuffle(halves)
    figs = []
    for name, (lo, hi) in zip(rng.sample(SCENE_FIGURES, 2), halves):
        base = gh - 0.5
        for _ in range(30):
            got = attempt(figure, rng, name, hi - lo, BOARD - 0.25 - base, True, (0.8, 1.0))
            if got is None:
                continue
            shapes, (x0, y0, x1, y1) = got
            dx = _on(rng, lo - x0, hi - x1, 0.25)
            dy = _clean(round((base - y0) * 4) / 4)
            placed = _shift(shapes, dx, dy)
            trial = backdrop + placed
            top, masks = owners(trial)
            if not visibility_problems(trial, 0.25, top, masks) and not colour_problems(trial, masks):
                figs.append(placed)
                break
        else:
            return None
    out = backdrop[:-1]
    n_fig = sum(len(f) for f in figs)
    if extras == "both" and len(out) + 2 + n_fig > 14:
        extras = "sky"
    if extras in ("sun", "both"):
        boxes = [_local_bbox(f) for f in figs]
        for _ in range(40):
            r = _on(rng, 0.75, 1.25, 0.25)
            sun = E(pick(rng, ["yellow", "red"], []), _on(rng, r + 0.25, BOARD - r - 0.25, 0.25),
                    _on(rng, max(6.5, gh + r + 0.5), BOARD - r - 0.25, 0.25), r)
            if all(not _boxes_near(sun, R("x", b[0], b[1], b[2] - b[0], b[3] - b[1]), 0.3) for b in boxes):
                out.append(sun)
                break
        else:
            if extras == "sun":
                return None
    out.append(ground)
    for f in figs:
        out += f
    if not 10 <= len(out) <= 14:
        return None
    return out


GENERATORS = {1: gen1, 2: gen2, 3: gen3, 4: gen4, 5: gen5, 6: gen6, 7: gen7, 8: gen8}


def generate(level: int, seed: int) -> list[dict]:
    rng = random.Random(f"two-rooms:{level}:{seed}")
    for _ in range(5000):
        shapes = attempt(GENERATORS[level], rng)
        if shapes is not None and not check(level, shapes):
            return shapes
    raise RuntimeError(f"no valid picture for level {level} seed {seed}")


def attempt(gen, rng, *args):
    try:
        return gen(rng, *args)
    except Retry:
        return None


def generate_figure(name: str, seed: int) -> list[dict]:
    """A level 6 picture of one named template (for contact sheets and tests)."""
    rng = random.Random(f"two-rooms:figure:{name}:{seed}")
    for _ in range(5000):
        shapes = attempt(gen6, rng, name)
        if shapes is not None and not check(6, shapes):
            return shapes
    raise RuntimeError(f"no valid {name} for seed {seed}")
