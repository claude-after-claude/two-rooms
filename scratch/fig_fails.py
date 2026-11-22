"""Per-template failure reasons, at level 6 size (full) and scene size (lite)."""
import random, sys
from collections import Counter
from tworooms import pictures as P

n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
names = sys.argv[2:] or sorted(P.FIGURES)
for lite, size in ((False, (6.8, 9.3)), (True, (3.8, 4.6))):
    print("LITE" if lite else "FULL")
    for name in names:
        rng = random.Random(f"y:{name}")
        ok = 0; fails = Counter(); counts = Counter()
        for i in range(n):
            try:
                got = P.figure(rng, name, *((9.5, 9.5) if not lite else (4.6, 8)), lite)
            except P.Retry:
                fails["retry"] += 1; continue
            if got is None:
                fails["None"] += 1; continue
            sh, (x0, y0, x1, y1) = got
            sh = P._shift(sh, P._clean(round((5 - (x0 + x1) / 2) * 4) / 4), P._clean(round((5 - (y0 + y1) / 2) * 4) / 4))
            pr = [p for p in P.check(6, sh) if "figure has" not in p and "past the board" not in p]
            counts[len(sh)] += 1
            if not pr: ok += 1
            for p in pr: fails[p] += 1
        print(f"  {name:14s} ok {ok}/{n}  sizes {dict(counts)}  ", fails.most_common(4))
