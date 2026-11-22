"""How often each level-6 template comes out of generate_with_kind(), over many seeds."""
import sys
from collections import Counter
from tworooms import pictures as P

n = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
counts = Counter(P.generate_with_kind(6, seed)[1] for seed in range(n))
for name, k in counts.most_common():
    print(f"{name:14s} {k:4d}  {100 * k / n:4.1f}%")
print(f"uniform would be {100 / len(P.FIGURES):.1f}% each")
