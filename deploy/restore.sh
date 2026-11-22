#!/bin/bash
# Put a database in place on the server and restart the hall. The file may be a nightly backup already on the
# server (/var/backups/tworooms/hall-YYYY-MM-DD.sqlite.gz) or a local .sqlite / .sqlite.gz (it is copied up first).
#   deploy/restore.sh FILE
set -euo pipefail
SERVER=${TWOROOMS_SERVER:-62.238.51.121}
KEY=${TWOROOMS_SSH_KEY:-$HOME/.ssh/porch_two_rooms}
FILE=${1:?give a database file}
SSH="ssh -i $KEY -o BatchMode=yes root@$SERVER"
if [ -f "$FILE" ]; then
  scp -i "$KEY" -q "$FILE" "root@$SERVER:/var/lib/tworooms/incoming"
  REMOTE=/var/lib/tworooms/incoming
  GZ=$([[ "$FILE" == *.gz ]] && echo 1 || echo 0)
else
  REMOTE=$FILE
  GZ=$([[ "$FILE" == *.gz ]] && echo 1 || echo 0)
fi
$SSH bash -s <<REMOTE_SCRIPT
set -euo pipefail
systemctl stop tworooms-hall
cd /var/lib/tworooms
if [ -f hall.sqlite ]; then
  python3 -c "import sqlite3, sys; s = sqlite3.connect('hall.sqlite'); d = sqlite3.connect(sys.argv[1]); s.backup(d)" \
    "hall.sqlite.before-restore-\$(date +%Y%m%d-%H%M%S)"
fi
rm -f hall.sqlite hall.sqlite-wal hall.sqlite-shm
if [ "$GZ" = 1 ]; then gunzip -c "$REMOTE" > hall.sqlite; else cp "$REMOTE" hall.sqlite; fi
rm -f incoming
rm -rf cache
chown porch:porch hall.sqlite
systemctl start tworooms-hall
sleep 2
systemctl is-active tworooms-hall
REMOTE_SCRIPT
