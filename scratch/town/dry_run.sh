#!/bin/bash
# A dry run of the town daemon against the real town (read only) and a copy of the live hall.
#   scratch/town/dry_run.sh                                 # one tick: which letter it would post, as it would post it
#   scratch/town/dry_run.sh AT_URI LETTER                   # read a real thread as the hall's post of LETTER, answer, close
# Everything lands in /var/tmp/tworooms-dry (the copied hall, the daemon's state and log, what it would post).
set -euo pipefail
cd "$(dirname "$0")/../.."
D=/var/tmp/tworooms-dry; PORT=8392; KEY=dry-admin
rm -rf "$D"; mkdir -p "$D/town"
ssh -i ~/.ssh/porch_two_rooms -o BatchMode=yes root@62.238.51.121 'python3 -c "
import sqlite3; s = sqlite3.connect(\"file:/var/lib/tworooms/hall.sqlite?mode=ro\", uri=True)
d = sqlite3.connect(\"/tmp/hall-dry.sqlite\"); s.backup(d); d.close()" && gzip -c /tmp/hall-dry.sqlite && rm /tmp/hall-dry.sqlite' \
  | gunzip > "$D/hall.sqlite"
TWOROOMS_ADMIN_KEY=$KEY uv run tworooms --port $PORT --db "$D/hall.sqlite" > "$D/hall.log" 2>&1 &
HALL=$!; trap 'kill $HALL' EXIT
for _ in $(seq 1 60); do curl -fs -o /dev/null http://127.0.0.1:$PORT/llms.txt && break; sleep 0.5; done
export TOWN_HALL_URL=http://127.0.0.1:$PORT TWOROOMS_ADMIN_KEY=$KEY TOWN_DIR="$D/town" \
       TWOROOMS_BASE_URL=https://62-238-51-121.sslip.io
if [ $# -eq 2 ]; then
  uv run python -m tworooms.town adopt "$1" "$2" --close | tee "$D/would-post.txt"
else
  uv run python -m tworooms.town run --once | tee "$D/would-post.txt"
fi
