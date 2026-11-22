import math

from tworooms.score import compare, rasterise, shape_mask

RECT = {"shape": "rect", "color": "red", "x": 2, "y": 1, "w": 3, "h": 2}


def test_rect_covers_exact_cells():
    m = shape_mask(RECT)
    assert m.sum() == 24 * 16
    assert m[8:24, 16:40].all()          # rows y 1..3, columns x 2..5


def test_ellipse_and_triangle_areas():
    e = shape_mask({"shape": "ellipse", "color": "blue", "cx": 5, "cy": 5, "rx": 2, "ry": 1.5})
    assert abs(e.sum() / 64 - math.pi * 2 * 1.5) < 0.1
    t = shape_mask({"shape": "triangle", "color": "green", "points": [[1, 1], [4, 1], [1, 5]]})
    assert abs(t.sum() / 64 - 6) < 0.15
    t2 = shape_mask({"shape": "triangle", "color": "green", "points": [[1, 1], [1, 5], [4, 1]]})
    assert (t == t2).all(), "orientation must not matter"


def test_later_shapes_cover_earlier():
    g = rasterise([RECT, {**RECT, "color": "blue", "x": 3}])
    assert g[10, 20] == 1 and g[10, 30] == 2 and g[10, 45] == 2 and g[10, 50] == 0


def test_identical_is_100():
    r = compare([RECT], [RECT])
    assert r["score"] == 100.0 and r["overlap"] == 100.0 and r["passed"]


def test_empty_build():
    r = compare([RECT], [])
    assert r["score"] == round(100 * (6400 - 384) / 6400, 1)
    assert r["overlap"] == 0.0


def test_shift_by_one_cell():
    shifted = {**RECT, "x": 2.125}
    r = compare([RECT], [shifted])
    assert r["cells_right"] == 6400 - 2 * 16
    assert r["score"] == round(100 * (6400 - 32) / 6400, 1)


def test_wrong_colour_counts_as_wrong():
    r = compare([RECT], [{**RECT, "color": "blue"}])
    assert r["cells_right"] == 6400 - 384 and r["overlap"] == 0.0
