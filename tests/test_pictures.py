import pytest

from tworooms import pictures as P
from tworooms.config import LEVELS

SEEDS = 500


@pytest.mark.parametrize("level", sorted(LEVELS))
def test_every_generator_obeys_its_constraints(level):
    seen = set()
    for seed in range(SEEDS):
        shapes = P.generate(level, seed)
        assert P.check(level, shapes) == [], (level, seed)
        seen.add(repr(shapes))
    assert len(seen) == SEEDS, "two seeds gave the same picture"


@pytest.mark.parametrize("level", sorted(LEVELS))
def test_generation_is_deterministic(level):
    for seed in (0, 7, 123456789):
        assert P.generate(level, seed) == P.generate(level, seed)


def test_at_least_sixteen_figure_templates_all_valid():
    assert len(P.FIGURES) >= 16
    for name in P.FIGURES:
        for seed in range(5):
            assert P.check(6, P.generate_figure(name, seed)) == [], (name, seed)


def test_checker_catches_violations():
    touching_reds = [P.R("red", 1, 1, 2, 2), P.R("red", 3, 1, 2, 2)]
    assert any("touch" in p for p in P.check(2, touching_reds + [P.R("blue", 6, 6, 2, 2), P.R("green", 1, 6, 2, 2)]))
    hidden = [P.R("red", 1, 1, 4, 4), P.R("blue", 0.5, 0.5, 5, 5), P.R("green", 6, 6, 2, 2), P.R("yellow", 6, 1, 2, 2)]
    assert any("visible" in p for p in P.check(3, hidden))
    off_board = [P.R("red", 9, 1, 2, 2), P.R("blue", 1, 5, 2, 2)]
    assert any("past the board" in p for p in P.check(1, off_board))
    off_grid = [P.R("red", 1.5, 1, 2, 2), P.R("blue", 6, 6, 2, 2)]
    assert any("grid" in p for p in P.check(1, off_grid))
