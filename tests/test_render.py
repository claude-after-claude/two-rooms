import numpy as np
import pytest

from tworooms import pictures as P, render as R
from tworooms.config import CELLS, COLORS
from tworooms.score import rasterise

PALETTE = np.array([R.PAPER] + [R.PIGMENT[c] for c in COLORS], np.float32)


def classify(img, size=800):
    """Sample the painted picture at the centre of every scoring cell; return the nearest colour index."""
    frame = round(size * 0.05)
    side = size - 2 * frame
    arr = np.asarray(img, np.float32)
    out = np.zeros((CELLS, CELLS), np.int8)
    xs = (frame + (np.arange(CELLS) + 0.5) * side / CELLS).astype(int)
    for j in range(CELLS):
        y = int(frame + (CELLS - j - 0.5) * side / CELLS)
        px = arr[y, xs]
        out[j] = np.argmin(((px[:, None, :] - PALETTE[None]) ** 2).sum(-1), axis=1)
    return out


def on_edge(grid):
    """Cells whose 8-neighbourhood holds a different value."""
    g = np.pad(grid, 1, mode="edge")
    edge = np.zeros_like(grid, dtype=bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            edge |= g[1 + dy:1 + dy + CELLS, 1 + dx:1 + dx + CELLS] != grid
    return edge


@pytest.mark.parametrize("level", range(1, 9))
def test_painted_picture_agrees_with_scoring_raster(level):
    """The painted picture is drawn from the same true shapes the scorer rasterises: away from edges every cell
    shows the scorer's colour, and the wobble never moves an edge by a whole cell."""
    for seed in range(4):
        shapes = P.generate(level, seed)
        truth = rasterise(shapes)
        seen = classify(R.painted(shapes, level, "heron", f"t{level}:{seed}"))
        wrong = seen != truth
        assert not (wrong & ~on_edge(truth)).any(), f"level {level} seed {seed}: a cell away from any edge differs"
        assert wrong.sum() < 0.02 * CELLS * CELLS


def test_images_have_expected_sizes():
    shapes = P.generate(6, 1)
    assert R.painted(shapes, 6, "heron", "s").size == (800, 800)
    empty = R.board([], "heron", grid=True)
    assert empty.size[0] > 700
    assert R.diff(shapes, []).size == empty.size
    assert R.og_pair(R.painted(shapes, 6, "heron", "s"), shapes, "x").size == (1200, 630)
    assert R.og_letter("a red house " * 80, "x").size == (1200, 630)
