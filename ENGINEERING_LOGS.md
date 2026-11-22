# Engineering log

Decisions where SPEC.md was silent, and things that surprised me. Newest at the bottom.

## 22 Nov 2026, first build (opus-5-5, for fable52)

**Layout.** Beyond the modules the spec names, `config.py` holds the level table and every tunable number,
`figures.py` holds the 21 level-6 templates (pictures.py was getting long), `game.py` holds all rules and
visibility (api.py and pages.py are thin over it), `images.py` caches rendered images on disk by a key of their
inputs (under `<db dir>/cache`).

**Geometry is exact.** Scoring works in sixteenths of a unit with integers: shape coordinates are multiples of
1/8, cell centres odd multiples of 1/16, so a centre never ties with a rect edge and nothing depends on floating
point. Builder input is rounded to 1/8 and the reply says so in `notes` rather than refusing.

**Constraint checker definitions.** "At least 0.75 units of visible extent in each direction" = the longest
visible run of cells is at least 6 in some row and in some column. "May not touch" = full (not visible) masks of
two same-coloured shapes stay 2 cells (0.25 units) apart; one cell looked like touching once painted. Level 1
blocks are at least one unit apart. Levels 1-4 never repeat a colour; level 5 repeats exactly one (6 shapes, 5
colours). Level 3 requires each rectangle to overlap another; level 7 requires each shape to overlap two others.
The level-7 generator places shapes one by one, each overlapping something already there, checks visibility
after every placement, then colours the touch graph greedily; this is ~50 ms a picture instead of seconds.

**Figures.** Each template draws in its own units and takes `k`, the smallest part allowed in those units; the
caller measures the figure, picks the final scale and redraws with `k = 1/scale` so every part comes out at least
one board unit. Without this, scene-sized figures failed the 0.75 rule most of the time. The touch rule forces
two-tone figures (a cat's head and body differ in colour; a key's teeth differ from its shaft); that reads as
cartoon and I kept it. Cup and lamp failed the at-a-glance test on the first contact sheet (top hat, Christmas
tree); the cup got steam and lost the straw, the lamp only uses a drum shade. Scenes exclude boat, fish, face,
cup, key, clock, lamp and ice cream (they need water or a table, or are just a big head). A scene is built
figure by figure, each checked against the ground and sky before the next, then a sun is placed where nothing is.

**Painted picture.** 800 px, 40 px frame, wobble ±0.03 units along the outline (spec allows 0.05) with
wavelengths 1-6 units: shorter waves looked like torn paper. A point that truly lies on the board's edge is
pushed past it so edge-hugging shapes stay flush; doing this for every point *near* the edge flattened ellipses
that touch the edge (seen in play, fixed). Per-pixel grain made PNGs 760 KB; low-frequency paper and brush noise
gives ~250 KB. Ticks on levels 1-2: nine marks per side, at every unit boundary (dividing each side into ten).
`tests/test_render.py` samples the painted PNG at every cell centre and requires every mismatch with the scoring
raster to be on an edge of the raster.

**Round word.** From a list of ~300 plain nouns in db.py (no colours, shapes or number words). Different from
the previous round of the same match and from the describer's other drafts; repeats across the whole site happen
and don't matter. It is painted on the describer's frame and printed on the builder's board image title.

**Letters.** A picture goes to a new describer with probability 1/2 when an existing one at that level has fewer
than 3 describers and this player hasn't seen it (unsent drafts older than two days don't hold a slot). Taking a
letter reserves one of its 5 slots; a build idle for 24 h expires and frees it. Closing by the describer cancels
builds in progress; at seven days a letter takes no new builders and closes once nobody is building. A draft is
discarded with the same `close` endpoint. Builders who have submitted see the picture and every other build while
the letter is still open; so does the describer.

**The builder's note** is capped at 60 words but not checked for numbers: it is read after the round, and "you
said a third but it was nearer two fifths" is the useful kind of note. Easy to change in `Hall.submit`.

**Live.** Whoever takes the seat describes round 1: they are the one present. Pictures in live rounds are always
fresh. The builder's board is never shown to the describer during a round (the wall between the rooms). In a
live match the match id stands for the current build (`/api/builds/<match id>/...`), so the client and agents
never need to know build ids. Long-poll: `GET /api/matches/<id>?wait=N` with no `since` waits for anything newer
than now; with `since` it returns at once if there is already news. One asyncio.Event per match, replaced each
time it fires; all handlers are async and touch SQLite only on the event loop thread, so a read-modify-write never
interleaves; images render in the thread pool.

**waiting_on.** Live: describer when no message yet or the builder spoke last; builder when the describer spoke
last; builder when the board has shapes and nothing has moved for 24 h. Letter builds: the builder. The match
page's sentence is addressed to you when it's your move ("Your move: answer kestrel").

**IDs** are seven pronounceable lowercase letters ("tamorik"): no digits, so an id can be said in a chat that
refuses numbers. Callsigns of the two players are exempt from the digit check in chat (fable52 has digits).

**Pages.** Added `/live` (open seats, your matches, the invite and seat forms) and `/start` (callsign or
existing key); the hall links to both. Result boards and difference images on pages are drawn in the painted
picture's frame geometry (`?framed=1`) so the three images line up; the API's default board image keeps axis
labels for agents. Cookie: `tr_key`, httponly, SameSite=Lax (cross-site form posts don't carry it).

**Client.** The server's `next` sentences speak HTTP; the client rewrites them into its own commands
(`cli_next`). The served `/tworooms.py` has the server's own address as its default. `match --wait` remembers
the last event per match in `~/.tworooms.json`, so each call shows only what is new.

**Rate limits** are in memory (lost on restart, fine): 10 callsigns/hour per IP, 40 pictures/hour per key,
20 matches/hour per key, 600 requests/minute per key. Set `TWOROOMS_TRUST_PROXY=1` behind a proxy so the IP is
read from X-Forwarded-For.

**Things noticed while playing (for fable52, not changed):**
- "Four blocks" and "six shapes" are refused. I wrote both without thinking, twice, while seeding test data.
- Fractions make every grid position sayable exactly: "half a tenth" (a twentieth), "a quarter of a tenth" (a
  fortieth), "halfway between four fifths and nine tenths" (17/20). A careful describer scored 100 at levels 3
  and 5 in my games. What makes levels 6-8 hard is the word budget, not the number rule.
