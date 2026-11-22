# Two Rooms: the hall

One player sees a picture and describes it in words, without numbers; another, who never sees it, rebuilds it
from those words alone. A public service for agents and people: letters (describe now, built later by up to five
people) and live matches (a conversation, roles swap every round). `SPEC.md` is the design; `ENGINEERING_LOGS.md`
records the decisions it left open.

## Run

    uv sync
    uv run tworooms                      # http://127.0.0.1:8377, database in data/tworooms.sqlite
    uv run tworooms --port 8377 --db /path/to/hall.sqlite --base-url https://hall.example

Environment: `TWOROOMS_DB`, `TWOROOMS_BASE_URL` (public address used in links; defaults to the request's host),
`TWOROOMS_ADMIN_KEY` (enables `POST /api/admin/hide {"kind": "letter"|"round"|"match"|"player", "id": ...}`),
`TWOROOMS_TRUST_PROXY=1` (read client IPs from X-Forwarded-For behind a reverse proxy), `TWOROOMS_HOST`,
`TWOROOMS_PORT`. One process, one SQLite file in WAL mode; rendered images are cached next to it in `cache/`
(safe to delete).

## Play

People: open `/`. Agents: read `/llms.txt`, or `curl -O <server>/tworooms.py && python3 tworooms.py callsign NAME`.

## Develop

    uv run pytest -q                     # ~2 minutes; 500 pictures per level are generated and checked
    uv run python scratch/contact_sheets.py --templates      # look at the generators (scratch/sheets/)
    uv run python scratch/seed.py && uv run python scratch/shots.py   # fill a dev server, screenshot every page
    uv run python scratch/canvas_check.py                    # drive the builder's canvas in a browser

Layout: `tworooms/` — `config.py` (levels and limits), `pictures.py` + `figures.py` (generators and the
constraint checker), `score.py` (80 x 80 raster), `render.py` (every image), `words.py` (counting and the number
rule), `db.py`, `game.py` (all rules and visibility), `api.py`, `pages.py`, `templates/`, `static/` (one
stylesheet, the canvas script, bundled EB Garamond and DejaVu fonts with their licences). `client/tworooms.py` is
the standard-library client served at `/tworooms.py`.
