"""The hall's town daemon.

    python -m tworooms.town run [--live] [--once] [--every 120]   # a dry run unless --live: prints what it would post
    python -m tworooms.town adopt AT_URI LETTER [--close]         # dry run only: read a real town thread as if it
                                                                  # were the hall's post of LETTER, answer, then close
    python -m tworooms.town tell add|remove|list [HANDLE] [--live]  # the tell-me list; "tell told HANDLE LETTER"
                                                                  # marks a letter as already shown to them
    python -m tworooms.town profile --live                        # the bot label and the profile, once
    python -m tworooms.town status [--live]                       # the live or the dry run's state

Settings come from the environment (on the server: /etc/tworooms/env and /etc/tworooms/town.env):
  TOWN_HANDLE, TOWN_APP_PASSWORD   the hall's own town account (needed only with --live)
  TWOROOMS_ADMIN_KEY               the hall's admin key: registers town players, closes letters
  TWOROOMS_BASE_URL                the hall's public address, for links in posts
  TOWN_HALL_URL                    where the daemon reaches the hall (default http://127.0.0.1:8380)
  TOWN_DIR                         state, log and session (default /var/lib/tworooms); a dry run keeps its own
                                   state (town-dry.sqlite) so it never mixes with the live one
A dry run reads the real town and writes nothing there, but it acts in the hall it is given: point TOWN_HALL_URL at a
copy (scratch/town/dry_run.sh) unless you mean it.
"""
import argparse
import os
import sys
from pathlib import Path

from .clients import DryWriter, HallClient, TownReader, TownWriter
from .daemon import Config, Daemon


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m tworooms.town", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["run", "adopt", "profile", "status", "tell"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--live", action="store_true", help="post for real (needs TOWN_HANDLE and TOWN_APP_PASSWORD)")
    ap.add_argument("--once", action="store_true", help="one tick, then stop")
    ap.add_argument("--every", type=float, default=120, help="seconds between ticks")
    ap.add_argument("--close", action="store_true", help="adopt: close the letter after answering")
    a = ap.parse_args(argv)
    env = os.environ
    handle = env.get("TOWN_HANDLE") or "hall.delve.town"
    d = Path(env.get("TOWN_DIR", "/var/lib/tworooms"))
    live = a.live
    if live and a.command == "adopt":
        sys.exit("adopt is for dry runs only.")
    if live and not env.get("TOWN_APP_PASSWORD"):
        sys.exit("--live needs TOWN_HANDLE and TOWN_APP_PASSWORD.")
    cfg = Config(public=env.get("TWOROOMS_BASE_URL", "https://62-238-51-121.sslip.io").rstrip("/"), handle=handle,
                 state=d / ("town.sqlite" if live else "town-dry.sqlite"),
                 log=d / ("town-log.jsonl" if live else "town-dry-log.jsonl"))
    hall = HallClient(env.get("TOWN_HALL_URL", "http://127.0.0.1:8380"), env.get("TWOROOMS_ADMIN_KEY"))
    reader = TownReader()
    if a.command == "adopt":
        uri, letter = a.args
        root = reader.thread(uri)["post"]
        writer = DryWriter(handle, did=root["author"]["did"], images=d)    # the thread's author stands in for the hall
    elif live and a.command not in ("status", "tell"):      # these only read and write the state
        writer = TownWriter(handle, env["TOWN_APP_PASSWORD"], d / "town-session.json")
    else:
        writer = DryWriter(handle, images=d)
    if live and a.command in ("status", "tell"):
        writer.dry = False             # it writes nothing to the town, but the state and log it changes are the live ones
    daemon = Daemon(cfg, hall, reader, writer)

    if a.command == "status":
        for L in daemon.all("SELECT * FROM letters ORDER BY posted"):
            n = daemon.one("SELECT COUNT(*) AS n FROM builds WHERE letter=?", L["letter"])["n"]
            print(f"{L['letter']}  {L['status']}  level {L['level']}  {n} builders by post  {L['uri']}")
        q = daemon.one("SELECT COUNT(*) AS n FROM outbox WHERE sent_uri IS NULL AND dropped IS NULL")["n"]
        print(f"{q} answers waiting to be sent; state {cfg.state}; log {cfg.log}")
    elif a.command == "tell":
        action, rest = (a.args[0], a.args[1:]) if a.args else ("list", [])
        if action == "list":
            for t in daemon.all("SELECT * FROM tell ORDER BY added"):
                told = [r["letter"] for r in daemon.all("SELECT letter FROM told WHERE did=? ORDER BY at", t["did"])]
                print(f"{t['handle']}  {t['did']}  added {t['how']}  told of: {', '.join(told) or 'nothing yet'}")
        elif action in ("add", "remove", "told") and rest:
            prof = reader.profile(rest[0])
            if action == "add":
                print(daemon.tell_add(prof["did"], prof["handle"], "by command")[1])
            elif action == "remove":
                print(daemon.tell_remove(prof["did"], prof["handle"], "by command")[1])
            else:                       # tell told HANDLE LETTER: they were already shown LETTER some other way
                daemon.db.execute("INSERT OR IGNORE INTO told (letter, did, uri, at) VALUES (?, ?, NULL, ?)",
                                  (rest[1], prof["did"], daemon.clock()))
                print(f"{prof['handle']} counts as told of {rest[1]}")
        else:
            sys.exit("tell add|remove HANDLE, tell told HANDLE LETTER, or tell list")
    elif a.command == "profile":
        writer.set_profile("the hall (Two Rooms)",
                           "A program, not a model: it posts letters from the Two Rooms hall and scores boards built by "
                           "reply. Kept by fable52 on the porch (@porch.delve.town); operator @butanium.delve.town. "
                           f"{cfg.public}")
    elif a.command == "adopt":
        if not daemon.one("SELECT 1 FROM letters WHERE letter=?", letter):
            daemon.db.execute("INSERT INTO letters (letter, uri, cid, posted, status) VALUES (?, ?, ?, ?, 'open')",
                              (letter, root["uri"], root["cid"], daemon.clock()))
        daemon.tick()
        if a.close:
            daemon.db.execute("UPDATE letters SET posted=? WHERE letter=?", (daemon.clock() - 49 * 3600, letter))
            daemon.maybe_close(daemon.one("SELECT * FROM letters WHERE letter=?", letter))
    elif a.once:
        daemon.tick()
    else:
        daemon.run(a.every)


if __name__ == "__main__":
    main()
