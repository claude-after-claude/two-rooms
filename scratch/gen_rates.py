"""How many attempts each generator needs, and how long it takes."""
import random, time, sys
from collections import Counter
from tworooms import pictures as P

n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
for level in range(1, 9):
    t = time.time(); fails = Counter(); attempts = []
    for seed in range(n):
        rng = random.Random(f"two-rooms:{level}:{seed}")
        for a in range(5000):
            sh = P.attempt(P.GENERATORS[level], rng)
            if sh is None:
                fails["None"] += 1; continue
            pr = P.check(level, sh)
            if not pr:
                attempts.append(a + 1); break
            for p in pr: fails[p.split(" is ")[0][:50] if "shape" not in p else p.split(" ", 2)[2][:40]] += 1
    dt = time.time() - t
    print(f"level {level}: {dt / n * 1000:.0f} ms/picture, mean attempts {sum(attempts)/len(attempts):.1f}, max {max(attempts)}")
    print("   ", fails.most_common(6))
names = sorted(P.FIGURES)
for name in names:
    t = time.time(); att = []; fails = Counter()
    for seed in range(n):
        rng = random.Random(f"x:{name}:{seed}")
        for a in range(5000):
            sh = P.attempt(P.gen6, rng, name)
            if sh is None: fails["None"] += 1; continue
            pr = P.check(6, sh)
            if not pr: att.append(a+1); break
            for p in pr: fails[p] += 1
    print(f"{name:14s} {(time.time()-t)/n*1000:6.0f} ms  attempts {sum(att)/len(att):5.1f}  ", fails.most_common(3))
