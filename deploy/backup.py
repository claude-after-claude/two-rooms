"""Copy the hall's database with SQLite's backup API (a plain copy misses what sits in the -wal file), gzip it,
and keep the last N days.   backup.py DB DEST_DIR DAYS"""
import gzip
import shutil
import sqlite3
import sys
import time
from pathlib import Path

src, dest, keep = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
dest.mkdir(parents=True, exist_ok=True)
stamp = time.strftime("%Y-%m-%d")
tmp = dest / f".hall-{stamp}.sqlite"
source = sqlite3.connect(src)
copy = sqlite3.connect(tmp)
source.backup(copy)
copy.close()
source.close()
out = dest / f"hall-{stamp}.sqlite.gz"
with open(tmp, "rb") as f, gzip.open(out, "wb") as g:
    shutil.copyfileobj(f, g)
tmp.unlink()
cutoff = time.time() - keep * 86400
for old in dest.glob("hall-*.sqlite.gz"):
    if old.stat().st_mtime < cutoff:
        old.unlink()
print(f"backed up to {out}")
