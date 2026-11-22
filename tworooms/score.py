"""Rasterise shapes on the 80 x 80 scoring grid and compare two boards.

All geometry is done in exact integers: coordinates are multiples of 1/8 unit, cell centres are odd multiples
of 1/16, so everything is scaled by 16 and compared without floating point.
"""
import numpy as np

from .config import CELLS, COLOR_INDEX, PASS_SCORE

_IDX = np.arange(CELLS, dtype=np.int64)
# cell (row j from the bottom, column i from the left) has its centre at ((2i+1)/16, (2j+1)/16) units
CX = np.broadcast_to(2 * _IDX[None, :] + 1, (CELLS, CELLS))
CY = np.broadcast_to(2 * _IDX[:, None] + 1, (CELLS, CELLS))


def _q(v: float) -> int:
    return int(round(v * 16))


def shape_mask(s: dict) -> np.ndarray:
    """Boolean (80, 80) array, [row from bottom, column from left], True where the cell centre is inside."""
    kind = s["shape"]
    if kind == "rect":
        x0, y0 = _q(s["x"]), _q(s["y"])
        x1, y1 = x0 + _q(s["w"]), y0 + _q(s["h"])
        return (CX >= x0) & (CX < x1) & (CY >= y0) & (CY < y1)
    if kind == "ellipse":
        cx, cy, rx, ry = _q(s["cx"]), _q(s["cy"]), _q(s["rx"]), _q(s["ry"])
        dx, dy = CX - cx, CY - cy
        return (dx * ry) ** 2 + (dy * rx) ** 2 <= (rx * ry) ** 2
    if kind == "triangle":
        (ax, ay), (bx, by), (cx, cy) = [(_q(p[0]), _q(p[1])) for p in s["points"]]
        if (bx - ax) * (cy - ay) - (by - ay) * (cx - ax) < 0:
            bx, by, cx, cy = cx, cy, bx, by

        def edge(px, py, qx, qy):
            return (qx - px) * (CY - py) - (qy - py) * (CX - px)

        return (edge(ax, ay, bx, by) >= 0) & (edge(bx, by, cx, cy) >= 0) & (edge(cx, cy, ax, ay) >= 0)
    raise ValueError(f"unknown shape {kind!r}")


def rasterise(shapes: list[dict]) -> np.ndarray:
    """int8 (80, 80): 0 for empty paper, else the colour index of the topmost shape."""
    grid = np.zeros((CELLS, CELLS), dtype=np.int8)
    for s in shapes:
        grid[shape_mask(s)] = COLOR_INDEX[s["color"]]
    return grid


def owners(shapes: list[dict]) -> tuple[np.ndarray, list[np.ndarray]]:
    """Index of the topmost shape per cell (-1 for empty), and each shape's full mask."""
    top = np.full((CELLS, CELLS), -1, dtype=np.int16)
    masks = []
    for i, s in enumerate(shapes):
        m = shape_mask(s)
        masks.append(m)
        top[m] = i
    return top, masks


def compare(picture: list[dict], build: list[dict]) -> dict:
    a, b = rasterise(picture), rasterise(build)
    same = a == b
    coloured = (a != 0) | (b != 0)
    both = same & (a != 0)
    n_coloured = int(coloured.sum())
    score = round(float(100.0 * same.sum() / same.size), 1)
    overlap = round(float(100.0 * both.sum() / n_coloured), 1) if n_coloured else 100.0
    return {
        "score": score,
        "overlap": overlap,
        "passed": bool(score >= PASS_SCORE),
        "cells_right": int(same.sum()),
        "cells_total": int(same.size),
    }


def diff_mask(picture: list[dict], build: list[dict]) -> np.ndarray:
    return rasterise(picture) != rasterise(build)
