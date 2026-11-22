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
    assert r["cells_match"] == 100.0 and r["in_place"] == 100.0


def test_empty_build():
    r = compare([RECT], [])
    assert r["cells_match"] == round(100 * (6400 - 384) / 6400, 1)
    assert r["in_place"] == 0.0


def test_shift_by_one_cell():
    shifted = {**RECT, "x": 2.125}
    r = compare([RECT], [shifted])
    assert r["cells_right"] == 6400 - 2 * 16
    assert r["cells_match"] == round(100 * (6400 - 32) / 6400, 1)
    assert r["in_place"] == round(100 * (384 - 16) / (384 + 16), 1)


def test_wrong_colour_counts_as_wrong():
    r = compare([RECT], [{**RECT, "color": "blue"}])
    assert r["cells_right"] == 6400 - 384 and r["in_place"] == 0.0


from tworooms.score import readings  # noqa: E402


def test_readings_identical_and_empty():
    r = readings([RECT], [RECT])
    assert r["in_place"] == 100.0 and r["slid_to_fit"] == 100.0 and r["slide"] == {"right": 0, "up": 0}
    r = readings([RECT], [])
    assert r["in_place"] == 0.0 and r["slid_to_fit"] == 0.0 and r["cells_match"] > 90


def test_slid_to_fit_finds_the_right_thing_in_the_wrong_place():
    picture = [RECT, {"shape": "ellipse", "color": "blue", "cx": 7, "cy": 7, "rx": 1.5, "ry": 1}]
    moved = [{**RECT, "x": 3.5, "y": 2.25}, {**picture[1], "cx": 8.5, "cy": 8.25}]   # all 1.5 right, 1.25 up
    r = readings(picture, moved)
    assert r["in_place"] < 30 and r["slid_to_fit"] == 100.0
    assert r["slide"] == {"right": -1.5, "up": -1.25}


def test_slide_is_limited_to_three_units():
    far = [{**RECT, "x": 6.5}]                     # 4.5 units to the right
    assert readings([RECT], far)["slid_to_fit"] < 100


def test_slid_to_fit_never_below_in_place():
    import random
    from tworooms import pictures as P
    rng = random.Random(1)
    for seed in range(6):
        pic = P.generate(4, seed)
        build = [dict(s, color=rng.choice(["red", "blue", "green"])) for s in pic[:3]]
        r = readings(pic, build)
        assert r["slid_to_fit"] >= r["in_place"]


def test_wrong_thing_stays_low_when_slid():
    r = readings([RECT], [{"shape": "ellipse", "color": "red", "cx": 7, "cy": 7, "rx": 0.5, "ry": 2}])
    assert r["slid_to_fit"] < 40


def test_slide_at_zero_equals_in_place():
    from tworooms import pictures as P
    for seed in range(10):
        pic = P.generate(7, seed)
        build = P.generate(7, seed + 100)
        r = readings(pic, build)
        assert r["slid_to_fit"] >= r["in_place"]
        if r["slide"] == {"right": 0, "up": 0}:
            assert r["slid_to_fit"] == r["in_place"]
