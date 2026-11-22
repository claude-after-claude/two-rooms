"""Rasterise shapes on the 80 x 80 scoring grid and compare two boards.

All geometry is done in exact integers: coordinates are multiples of 1/8 unit, cell centres are odd multiples
of 1/16, so everything is scaled by 16 and compared without floating point.
"""
import numpy as np

from .config import CELLS, COLOR_INDEX, SLIDE_CELLS

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


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    painted = (a != 0) | (b != 0)
    n = int(painted.sum())
    if n == 0:
        return 100.0
    return 100.0 * int(((a == b) & (a != 0)).sum()) / n


def best_slide(a: np.ndarray, b: np.ndarray, reach: int = SLIDE_CELLS) -> tuple[float, int, int]:
    """The best overlap of painted cells over every shift of the whole build b by (dx, dy) cells, |dx|, |dy| <= reach.
    Cells slid off the board are lost. Ties go to the smallest slide. Returns (overlap %, dx, dy)."""
    pa = a != 0
    n_a = int(pa.sum())
    pb = b != 0
    best = (-1.0, 0, 0)
    for dy in range(-reach, reach + 1):
        # rows of a that b's rows land on after moving up by dy
        ay0, ay1 = max(0, dy), CELLS + min(0, dy)
        by0, by1 = max(0, -dy), CELLS - max(0, dy)
        a_rows, b_rows = a[ay0:ay1], b[by0:by1]
        pa_rows, pb_rows = pa[ay0:ay1], pb[by0:by1]
        for dx in range(-reach, reach + 1):
            ax0, ax1 = max(0, dx), CELLS + min(0, dx)
            bx0, bx1 = max(0, -dx), CELLS - max(0, dx)
            bs, pbs, pas = b_rows[:, bx0:bx1], pb_rows[:, bx0:bx1], pa_rows[:, ax0:ax1]
            inter = int(((a_rows[:, ax0:ax1] == bs) & pas).sum())
            union = n_a + int(pbs.sum()) - int((pas & pbs).sum())
            v = 100.0 * inter / union if union else 100.0
            if v > best[0] + 1e-9 or (abs(v - best[0]) <= 1e-9 and abs(dx) + abs(dy) < abs(best[1]) + abs(best[2])):
                best = (v, dx, dy)
    return best


def readings(picture: list[dict], build: list[dict]) -> dict:
    """The two readings shown to players, and the cell match kept for the details.

    in place:    of the cells painted on either board, the share painted the same colour, as built.
    slid to fit: the same, after sliding the whole build to wherever it matches best (up to 3 units each way)."""
    a, b = rasterise(picture), rasterise(build)
    slid, dx, dy = best_slide(a, b)
    same = a == b
    return {
        "in_place": round(_iou(a, b), 1),
        "slid_to_fit": round(slid, 1),
        "slide": {"right": dx * 0.125, "up": dy * 0.125},
        "cells_match": round(float(100.0 * same.sum() / same.size), 1),
        "cells_differ": int((~same).sum()),
    }


def compare(picture: list[dict], build: list[dict]) -> dict:
    """Cell match and in-place overlap only (cheap); kept for tests and the hall's example."""
    a, b = rasterise(picture), rasterise(build)
    same = a == b
    return {
        "cells_match": round(float(100.0 * same.sum() / same.size), 1),
        "in_place": round(_iou(a, b), 1),
        "cells_right": int(same.sum()),
        "cells_total": int(same.size),
    }


def diff_mask(picture: list[dict], build: list[dict]) -> np.ndarray:
    return rasterise(picture) != rasterise(build)
