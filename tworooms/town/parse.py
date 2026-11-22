"""Reading a town reply as a build: forgiving about layout, case and chatter, strict about the numbers.

A shape is a shape word and a colour, in either order, then its numbers; the numbers may be separated by spaces,
commas, x=/w= labels and so on. Shapes may sit one per line, be separated by commas, semicolons, slashes or plus
signs, or simply follow one another. A colour with four numbers and no shape word is a rectangle, as in the games
dealt by post in November ("black 4.5, 5, 4.75, 4.75"). Words after "note:" are the builder's note; the word
"final" anywhere before it makes the reply the submission.
"""
import re
from dataclasses import dataclass, field

KINDS = {"rect": "rect", "rects": "rect", "rectangle": "rect", "rectangles": "rect", "block": "rect", "box": "rect",
         "ellipse": "ellipse", "ellipses": "ellipse", "oval": "ellipse", "circle": "ellipse", "disc": "ellipse",
         "disk": "ellipse", "triangle": "triangle", "tri": "triangle", "triangles": "triangle"}
COLOURS = {"red", "blue", "yellow", "green", "black"}
# words that may sit inside a shape without ending it ("red rect at x=2 y=1, 3 wide and 2 tall")
FILLER = {"at", "from", "to", "by", "and", "x", "y", "w", "h", "cx", "cy", "rx", "ry", "left", "bottom", "width",
          "height", "wide", "tall", "high", "across", "up", "centre", "center", "radius", "radii", "corner", "corners",
          "lower", "size", "point", "points", "with", "of", "a", "the", "on", "is", "colour", "color", "xy", "wh"}
FORMAT = "rect COLOUR X Y W H · ellipse COLOUR CX CY RX RY · triangle COLOUR X1 Y1 X2 Y2 X3 Y3"
_WANT = {"rect": "four numbers (x y w h)", "ellipse": "four numbers (cx cy rx ry), or three for a circle",
         "triangle": "six numbers (three corners)"}
_TOKEN = re.compile(r"(?P<num>-?\d+(?:\.\d+)?(?:/\d+)?|-?\.\d+)|(?P<word>[^\W\d_]+)|(?P<brk>[\n;+/|]|\s[-–—•*]\s)")


@dataclass
class Reply:
    shapes: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    final: bool = False
    note: str | None = None

    @property
    def build(self) -> bool:
        """At least one whole shape and nothing half-written: this reply is a board."""
        return bool(self.shapes) and not self.errors


def _num(s: str) -> float:
    if "/" in s:
        a, b = s.split("/")
        if not float(b):
            raise ValueError(s)
        return float(a) / float(b)
    return float(s)


def _pieces(t: str) -> list[dict]:
    """Group the tokens into shape attempts: a shape word and/or a colour, and at least two numbers."""
    pieces, cur = [], None

    def close():
        nonlocal cur
        if cur and len(cur["nums"]) >= 2:
            pieces.append(cur)
        cur = None

    for tok in _TOKEN.finditer(t):
        if tok.group("brk"):
            close()
        elif tok.group("num"):
            if cur is not None:
                cur["nums"].append(tok.group("num"))
                cur["text"].append(tok.group("num"))
        else:
            w = tok.group("word").lower()
            if w in KINDS or w in COLOURS:
                slot = "kind" if w in KINDS else "colour"
                if cur is None or cur["nums"] or cur[slot]:
                    close()
                    cur = {"kind": None, "colour": None, "nums": [], "text": []}
                cur[slot] = KINDS.get(w, w)
                cur["text"].append(tok.group("word"))
            elif w not in FILLER and cur is not None:
                close()          # prose after the numbers ends a shape; prose before them ("the red one was") drops it
    close()
    return pieces


def parse_reply(text: str) -> Reply:
    r = Reply()
    m = re.search(r"\bnote\s*:", text, re.I)
    body = text[:m.start()] if m else text
    if m:
        r.note = text[m.end():].strip() or None
    body = re.sub(r"https?://\S+", " ", body)     # addresses carry digits
    body = re.sub(r"@[\w.-]+", " ", body)           # so do some handles
    r.final = bool(re.search(r"\bfinal\b", body, re.I))
    for p in _pieces(body):
        shown = " ".join(p["text"])
        try:
            v = [_num(x) for x in p["nums"]]
        except ValueError:
            r.errors.append(f'"{shown}": one of its numbers is not a number')
            continue
        kind = p["kind"] or ("rect" if len(v) == 4 else None)
        if kind is None:
            r.errors.append(f'"{shown}": say which shape it is (rect, ellipse or triangle)')
        elif not p["colour"]:
            r.errors.append(f'"{shown}": it needs a colour (red, blue, yellow, green or black)')
        elif kind == "rect" and len(v) == 4:
            r.shapes.append({"shape": "rect", "color": p["colour"], "x": v[0], "y": v[1], "w": v[2], "h": v[3]})
        elif kind == "ellipse" and len(v) in (3, 4):
            r.shapes.append({"shape": "ellipse", "color": p["colour"], "cx": v[0], "cy": v[1], "rx": v[2], "ry": v[-1]})
        elif kind == "triangle" and len(v) == 6:
            r.shapes.append({"shape": "triangle", "color": p["colour"], "points": [v[0:2], v[2:4], v[4:6]]})
        else:
            r.errors.append(f'"{shown}": a {kind} takes {_WANT[kind]}, and this has {len(v)}')
    return r
