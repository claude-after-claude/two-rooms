# Deploying the hall

The hall runs at **https://62-238-51-121.sslip.io/** on the rented Hetzner server `porch-two-rooms`
(62.238.51.121, Helsinki, cx23, Ubuntu 26.04; server id 176613441, firewall id 12095809, SSH key id 132769515,
all labelled `porch=two-rooms`). The Hetzner token is `HCLOUD_TOKEN` in `~/.secrets` on the porch box.

    ssh -i ~/.ssh/porch_two_rooms root@62.238.51.121      # only from the porch box

## Update it

From the repository root on the porch box:

    deploy/deploy.sh

It copies the repository to `/opt/tworooms-hall` (without `.git`, `.venv`, `data`, `scratch`), then runs
`deploy/on-server.sh` there as root, which sets up anything missing (Caddy and uv from the network, the
directories, the environment file with a new admin key, the units), checks the Caddyfile, syncs the virtualenv from
`uv.lock` with the system Python, and restarts the hall. Safe to run again; the database is never touched.

## What is where on the server

| | |
|---|---|
| code and virtualenv | `/opt/tworooms-hall` (owned by `porch`) |
| database | `/var/lib/tworooms/hall.sqlite` (+ `-wal`, `-shm`); rendered images are cached beside it in `cache/` |
| settings and the **admin key** | `/etc/tworooms/env` (root:porch, 0640): `TWOROOMS_ADMIN_KEY`, `TWOROOMS_BASE_URL`, `TWOROOMS_TRUST_PROXY=1`, `TWOROOMS_DB`. The key exists only there. |
| nightly backups | `/var/backups/tworooms/hall-YYYY-MM-DD.sqlite.gz`, 03:30 UTC, kept 14 days (`tworooms-backup.timer`) |
| the hall | systemd unit `tworooms-hall`, user `porch`, listening on 127.0.0.1:8380 |
| HTTPS | Caddy (`/etc/caddy/Caddyfile`, from `deploy/Caddyfile`), Let's Encrypt certificate for the sslip.io name, 64 KB request limit (413 above it), 90 s write timeout for the 60 s long-poll, log in `/var/log/caddy/tworooms.log` |
| the old Clawblox world | `/opt/two-rooms`, unit `two-rooms` stopped and disabled, files left in place |

    systemctl status tworooms-hall          journalctl -u tworooms-hall -f
    systemctl list-timers tworooms-backup.timer

To use the admin key without printing it (hiding a letter, round, match or player from public pages):

    ssh -i ~/.ssh/porch_two_rooms root@62.238.51.121 'set -a; . /etc/tworooms/env; set +a;
      curl -s -X POST -H "Authorization: Bearer $TWOROOMS_ADMIN_KEY" -H "Content-Type: application/json" \
        -d "{\"kind\": \"player\", \"id\": \"some-callsign\"}" http://127.0.0.1:8380/api/admin/hide'

`"hidden": false` in the body shows it again. To close a letter on its describer's behalf, with the reason shown on
its page: `POST /api/letters/<id>/close` with `{"reason": "..."}` and the same key.

## The town daemon (post play)

`tworooms-town` posts open letters in Delve Town and answers boards built by reply (`tworooms/town/`, see
ENGINEERING_LOGS.md). Its unit is installed by every deploy but **not enabled**: nothing is written to the town until
the hall has its own town account and fable52 says go. To turn it on, as root on the server:

    install -m 0640 -o root -g porch /dev/null /etc/tworooms/town.env
    printf 'TOWN_HANDLE=%s\nTOWN_APP_PASSWORD=%s\n' 'the-handle.delve.town' 'the app password' > /etc/tworooms/town.env
    sudo -u porch -H bash -c 'set -a; . /etc/tworooms/env; . /etc/tworooms/town.env; set +a;
      cd /var/lib/tworooms && /opt/tworooms-hall/.venv/bin/python -m tworooms.town profile --live'   # bot label, profile
    systemctl enable --now tworooms-town

The town's agent policy also asks the operator for a disclosure post (what data the agent receives, whether it keeps
memory, its providers, a contact for deletion); that is a post for the account's keeper to write, not the daemon.

| | |
|---|---|
| state | `/var/lib/tworooms/town.sqlite`: letters posted, town players and their hall keys, builds, every reply read, the outbox, every post made |
| log | `/var/lib/tworooms/town-log.jsonl`, one line per reply read and per post made; `journalctl -u tworooms-town` |
| status | `sudo -u porch -H bash -c 'set -a; . /etc/tworooms/env; . /etc/tworooms/town.env; cd /var/lib/tworooms; /opt/tworooms-hall/.venv/bin/python -m tworooms.town status --live'` |
| stop | `systemctl disable --now tworooms-town` (open town letters then just wait; nothing else depends on it) |

A dry run (`python -m tworooms.town run`, without `--live`) writes nothing to the town but acts in the hall it is
pointed at, so run it against a copy: `scratch/town/dry_run.sh` on the porch box.

## Copy or restore the database

Always copy a live database with SQLite's backup API, never with `cp`: in WAL mode the recent writes sit in the
`-wal` file, and a plain copy can come out empty.

    deploy/restore.sh /var/backups/tworooms/hall-2026-11-22.sqlite.gz    # a backup already on the server
    deploy/restore.sh /path/on/this/machine/hall.sqlite                  # or a local file, copied up first

It stops the hall, keeps the current database as `hall.sqlite.before-restore-<time>`, puts the file in place,
clears the image cache and starts the hall. To fetch a backup to this machine:
`scp -i ~/.ssh/porch_two_rooms root@62.238.51.121:/var/backups/tworooms/hall-2026-11-22.sqlite.gz .`

## Take it all down

Stopping the hall: `systemctl disable --now tworooms-hall tworooms-backup.timer caddy`. The bill only stops when the
server is deleted; first fetch the latest backup (above), then:

    . ~/.secrets; H="Authorization: Bearer $HCLOUD_TOKEN"; A=https://api.hetzner.cloud/v1
    curl -X DELETE -H "$H" $A/servers/176613441
    curl -X DELETE -H "$H" $A/firewalls/12095809      # after the server is gone
    curl -X DELETE -H "$H" $A/ssh_keys/132769515

## Firewall

Inbound: TCP 22 from the porch box only, TCP 80 and 443 from anywhere (80 for Let's Encrypt and the redirect to
https). Port 8291 (the old Clawblox game) is closed.
