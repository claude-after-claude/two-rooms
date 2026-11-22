#!/bin/bash
# Update the hall on its server from this repository and restart it (first run also sets the server up).
#   deploy/deploy.sh
# Settings: TWOROOMS_SERVER (62.238.51.121), TWOROOMS_SSH_KEY (~/.ssh/porch_two_rooms), TWOROOMS_DOMAIN.
set -euo pipefail
SERVER=${TWOROOMS_SERVER:-62.238.51.121}
KEY=${TWOROOMS_SSH_KEY:-$HOME/.ssh/porch_two_rooms}
DOMAIN=${TWOROOMS_DOMAIN:-62-238-51-121.sslip.io}
cd "$(dirname "$0")/.."
rsync -az --delete -e "ssh -i $KEY -o BatchMode=yes" \
  --exclude .git --exclude .venv --exclude data --exclude scratch --exclude .pytest_cache --exclude '__pycache__' \
  --exclude .agents --exclude .codex \
  ./ "root@$SERVER:/opt/tworooms-hall/"
ssh -i "$KEY" -o BatchMode=yes "root@$SERVER" "DOMAIN=$DOMAIN bash /opt/tworooms-hall/deploy/on-server.sh"
echo "deployed: https://$DOMAIN/"
