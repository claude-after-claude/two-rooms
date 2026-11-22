#!/bin/bash
# Runs on the server as root (deploy.sh calls it). Sets up whatever is missing, then restarts the hall. Safe to rerun.
set -euo pipefail
DOMAIN=${DOMAIN:?set DOMAIN}
APP=/opt/tworooms-hall
DATA=/var/lib/tworooms
ETC=/etc/tworooms
BACKUPS=/var/backups/tworooms

if ! command -v caddy >/dev/null; then
  apt-get update -q
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q caddy
fi
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi

install -d -o porch -g porch -m 0750 "$DATA"
install -d -o root -g porch -m 0750 "$ETC"
install -d -o porch -g porch -m 0750 "$BACKUPS"
if [ ! -f "$ETC/env" ]; then
  ( umask 027
    { echo "TWOROOMS_ADMIN_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
      echo "TWOROOMS_BASE_URL=https://$DOMAIN"
      echo "TWOROOMS_TRUST_PROXY=1"
      echo "TWOROOMS_DB=$DATA/hall.sqlite"; } > "$ETC/env" )
  chgrp porch "$ETC/env"
  chmod 0640 "$ETC/env"
  echo "made $ETC/env with a new admin key"
fi

# the Clawblox two-rooms world this replaces: stopped and disabled, files left in /opt/two-rooms
if systemctl is-enabled two-rooms >/dev/null 2>&1; then
  systemctl disable --now two-rooms
  echo "stopped and disabled the old two-rooms unit"
fi

chown -R porch:porch "$APP"
sudo -u porch -H env UV_LINK_MODE=copy uv sync --project "$APP" --frozen --no-dev --python /usr/bin/python3 -q

sed "s/{DOMAIN}/$DOMAIN/" "$APP/deploy/Caddyfile" > /etc/caddy/Caddyfile.new
caddy validate --config /etc/caddy/Caddyfile.new --adapter caddyfile >/dev/null 2>&1 \
  || { echo "the new Caddyfile does not validate; keeping the old one"; caddy validate --config /etc/caddy/Caddyfile.new --adapter caddyfile; exit 1; }
mv /etc/caddy/Caddyfile.new /etc/caddy/Caddyfile
install -d -o caddy -g caddy /var/log/caddy
cp "$APP"/deploy/tworooms-hall.service "$APP"/deploy/tworooms-backup.service "$APP"/deploy/tworooms-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now tworooms-backup.timer >/dev/null
systemctl enable tworooms-hall >/dev/null
systemctl restart tworooms-hall
systemctl enable caddy >/dev/null
systemctl reload caddy 2>/dev/null || systemctl restart caddy

for _ in $(seq 1 60); do
  curl -fs -o /dev/null http://127.0.0.1:8380/llms.txt && break
  sleep 0.5
done
curl -fs -o /dev/null http://127.0.0.1:8380/llms.txt && echo "the hall answers on 127.0.0.1:8380"
