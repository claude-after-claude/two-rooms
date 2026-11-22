"""Checking and normalising shapes that players send."""
from .config import BOARD, COLORS, STEP

FIELDS = {
    "rect": ("x", "y", "w", "h"),
    "ellipse": ("cx", "cy", "rx", "ry"),
}

EXAMPLES = (
    '{"shape": "rect", "color": "red", "x": 2, "y": 1, "w": 3, "h": 2}, '
    '{"shape": "ellipse", "color": "blue", "cx": 5, "cy": 5, "rx": 2, "ry": 1.5} or '
    '{"shape": "triangle", "color": "green", "points": [[1, 1], [4, 1], [1, 5]]}'
)


class ShapeError(ValueError):
    pass


def num(v: float):
    """2.0 -> 2 so that JSON reads naturally."""
    return int(v) if float(v).is_integer() else float(v)


def _snap(v, name: str, notes: list[str]) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise ShapeError(f"{name} must be a number, got {v!r}.")
    if v != v or v in (float("inf"), float("-inf")):
        raise ShapeError(f"{name} must be a finite number.")
    snapped = round(v / STEP) * STEP
    if abs(snapped - v) > 1e-9:
        notes.append(f"{name} {v:g} → {snapped:g}")
    return snapped


def _say_rounded(notes: list[str]) -> list[str]:
    return [f"Rounded to steps of 1/8: {', '.join(notes)}."] if notes else []


def normalise(raw: dict) -> tuple[dict, list[str]]:
    """Return (shape, notes). Raises ShapeError with a sentence a player can act on."""
    if not isinstance(raw, dict):
        raise ShapeError(f"A shape is a JSON object such as {EXAMPLES}.")
    kind = raw.get("shape", raw.get("type", raw.get("kind")))
    if kind is None:
        raise ShapeError(f'The shape needs a "shape" field: "rect", "ellipse" or "triangle". For example {EXAMPLES}.')
    kind = str(kind).lower().strip()
    kind = {"rectangle": "rect", "circle": "ellipse", "oval": "ellipse", "tri": "triangle"}.get(kind, kind)
    if kind not in ("rect", "ellipse", "triangle"):
        raise ShapeError(f'Unknown shape "{kind}". Use "rect", "ellipse" or "triangle".')
    color = raw.get("color", raw.get("colour"))
    if color is None:
        raise ShapeError(f'The {kind} needs a "color": one of {", ".join(COLORS)}.')
    color = str(color).lower().strip()
    if color not in COLORS:
        raise ShapeError(f'Unknown colour "{color}". The colours are {", ".join(COLORS)}.')
    notes: list[str] = []
    out = {"shape": kind, "color": color}
    if kind == "triangle":
        pts = raw.get("points")
        if not (isinstance(pts, list) and len(pts) == 3 and all(isinstance(p, (list, tuple)) and len(p) == 2 for p in pts)):
            raise ShapeError('A triangle needs "points": three [x, y] pairs, e.g. [[1, 1], [4, 1], [1, 5]].')
        pts = [[_snap(p[0], f"point {k + 1} x", notes), _snap(p[1], f"point {k + 1} y", notes)] for k, p in enumerate(pts)]
        (ax, ay), (bx, by), (cx, cy) = pts
        if abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax)) < 1e-9:
            raise ShapeError("Those three points lie on one line, so the triangle has no area.")
        for k, (x, y) in enumerate(pts):
            _inside(x, y, f"point {k + 1}")
        out["points"] = [[num(x), num(y)] for x, y in pts]
        return out, _say_rounded(notes)
    names = FIELDS[kind]
    vals = {}
    for n in names:
        if n not in raw:
            want = ", ".join(f'"{f}"' for f in names)
            raise ShapeError(f"A {kind} needs {want}. Missing \"{n}\". For example {EXAMPLES}.")
        vals[n] = _snap(raw[n], n, notes)
    if kind == "rect":
        if vals["w"] <= 0 or vals["h"] <= 0:
            raise ShapeError("A rect's w and h must be more than 0 (w is its width, h its height).")
        _inside(vals["x"], vals["y"], "its bottom-left corner (x, y)")
        _inside(vals["x"] + vals["w"], vals["y"] + vals["h"], "its top-right corner (x + w, y + h)")
    else:
        if vals["rx"] <= 0 or vals["ry"] <= 0:
            raise ShapeError("An ellipse's rx and ry (half-width and half-height) must be more than 0.")
        for side, (x, y) in {
            "left": (vals["cx"] - vals["rx"], vals["cy"]), "right": (vals["cx"] + vals["rx"], vals["cy"]),
            "bottom": (vals["cx"], vals["cy"] - vals["ry"]), "top": (vals["cx"], vals["cy"] + vals["ry"]),
        }.items():
            _inside(x, y, f"its {side} edge")
    out.update({n: num(v) for n, v in vals.items()})
    return out, _say_rounded(notes)


def _inside(x: float, y: float, what: str):
    if not (0 <= x <= BOARD and 0 <= y <= BOARD):
        raise ShapeError(
            f"That shape would stick out of the board: {what} is at ({x:g}, {y:g}), but x and y run from 0 to "
            f"{BOARD:g} (x from the left edge, y from the bottom edge). Nothing in a picture goes past the board."
        )


def describe(s: dict) -> str:
    """One line, as the command-line client takes it back: 'rect red 2 1 3 2'."""
    if s["shape"] == "triangle":
        coords = " ".join(f"{num(v):g}" for p in s["points"] for v in p)
    else:
        coords = " ".join(f"{num(s[f]):g}" for f in FIELDS[s["shape"]])
    return f"{s['shape']} {s['color']} {coords}"


def bbox(s: dict) -> tuple[float, float, float, float]:
    """x0, y0, x1, y1"""
    if s["shape"] == "rect":
        return s["x"], s["y"], s["x"] + s["w"], s["y"] + s["h"]
    if s["shape"] == "ellipse":
        return s["cx"] - s["rx"], s["cy"] - s["ry"], s["cx"] + s["rx"], s["cy"] + s["ry"]
    xs = [p[0] for p in s["points"]]
    ys = [p[1] for p in s["points"]]
    return min(xs), min(ys), max(xs), max(ys)


def parse_text(text: str) -> list[dict]:
    """'rect red 2 1 3 2, ellipse blue 5 5 2 1.5, triangle green 1 1 4 1 1 5' -> raw shapes (not yet normalised).
    Shapes are separated by commas or semicolons; an ellipse with three numbers is a circle."""
    out = []
    parts = [p.split() for p in text.replace(";", ",").split(",")]
    parts = [p for p in parts if p]
    for i, p in enumerate(parts):
        where = f"Shape {i + 1} ({' '.join(p)}): " if len(parts) > 1 else ""
        kind = p[0].lower()
        if len(p) < 2:
            raise ShapeError(where + "a colour comes after the shape: red, blue, yellow, green or black.")
        color, nums = p[1], p[2:]
        try:
            v = [float(x) for x in nums]
        except ValueError:
            raise ShapeError(where + f"the numbers after the colour must be numbers, got {' '.join(nums)}.")
        if kind in ("rect", "rectangle"):
            if len(v) != 4:
                raise ShapeError(where + "rect COLOUR X Y W H (lower left corner, width, height).")
            out.append({"shape": "rect", "color": color, "x": v[0], "y": v[1], "w": v[2], "h": v[3]})
        elif kind in ("ellipse", "circle", "oval"):
            if len(v) == 3:
                v.append(v[2])
            if len(v) != 4:
                raise ShapeError(where + "ellipse COLOUR CX CY RX RY (centre, half-width, half-height).")
            out.append({"shape": "ellipse", "color": color, "cx": v[0], "cy": v[1], "rx": v[2], "ry": v[3]})
        elif kind in ("triangle", "tri"):
            if len(v) != 6:
                raise ShapeError(where + "triangle COLOUR X1 Y1 X2 Y2 X3 Y3.")
            out.append({"shape": "triangle", "color": color, "points": [v[0:2], v[2:4], v[4:6]]})
        else:
            raise ShapeError(where + f'unknown shape "{kind}": use rect, ellipse or triangle.')
    return out
