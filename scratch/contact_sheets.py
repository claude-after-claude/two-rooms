"""Render contact sheets: 20 painted pictures per level, and every level 6 template a few times."""
import argparse, time
from pathlib import Path
from tworooms import pictures as P, render as Rn

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="scratch/sheets")
ap.add_argument("--levels", default="1,2,3,4,5,6,7,8")
ap.add_argument("--n", type=int, default=20)
ap.add_argument("--templates", action="store_true")
ap.add_argument("--start", type=int, default=0)
args = ap.parse_args()
out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
for level in map(int, args.levels.split(",")):
    t = time.time(); imgs = []
    for seed in range(args.start, args.start + args.n):
        sh = P.generate(level, seed)
        imgs.append(Rn.painted(sh, level, "heron", f"{level}:{seed}"))
    dt = time.time() - t
    Rn.sheet(imgs, 5, 300, [f"L{level} seed {s}" for s in range(args.start, args.start + args.n)]).save(out / f"level{level}.jpg", quality=88)
    print(f"level {level}: {dt / args.n * 1000:.0f} ms per picture (generate + paint)")
if args.templates:
    names = sorted(P.FIGURES)
    imgs, labels = [], []
    for name in names:
        for seed in range(4):
            imgs.append(Rn.plain(P.generate_figure(name, seed), 300)); labels.append(f"{name} {seed}")
    Rn.sheet(imgs, 8, 220, labels).save(out / "templates.jpg", quality=88)
