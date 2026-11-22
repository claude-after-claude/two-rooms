"""Templates for level 6 figures and level 8 scenes.

Each template draws one thing in its own local units (roughly 6 to 10 across) and returns a list of shapes, or None
when the random draw didn't fit. `k` is the smallest part allowed, in local units (the caller computes it from the
final scale so that every part is at least 0.85 board units). `lite` drops optional parts for scenes.
Touching parts always get different colours; the checker in pictures.py has the last word.
"""
import math

from .config import COLORS


def R(c, x, y, w, h):
    return {"shape": "rect", "color": c, "x": x, "y": y, "w": w, "h": h}


def E(c, cx, cy, rx, ry=None):
    return {"shape": "ellipse", "color": c, "cx": cx, "cy": cy, "rx": rx, "ry": rx if ry is None else ry}


def T(c, a, b, p):
    return {"shape": "triangle", "color": c, "points": [list(a), list(b), list(p)]}


def pick(rng, options, avoid=()):
    opts = [c for c in options if c not in avoid]
    return rng.choice(opts or [c for c in COLORS if c not in avoid] or COLORS)


def U(rng, a, b):
    return rng.uniform(a, b)


def _scatter(rng, n, r, inside, gap, tries=400):
    """n points such that discs of radius r around them are `gap` apart and `inside(x, y)` holds."""
    pts = []
    for _ in range(tries):
        if len(pts) == n:
            break
        x, y = inside(None, None)
        if x is None:
            continue
        if all(math.hypot(x - a, y - b) > 2 * r + gap for a, b in pts):
            pts.append((x, y))
    return pts if len(pts) == n else None


def house(rng, k, lite):
    Ww, Hw, Hr, o = U(rng, 5.5, 7), U(rng, 3, 4.3), U(rng, 2, 3.2), U(rng, 0.3, 0.8)
    walls = pick(rng, ["yellow", "red", "blue", "green"])
    roof = pick(rng, ["black", "red", "green", "blue"], [walls])
    door = pick(rng, ["black", "blue", "green", "red", "yellow"], [walls])
    win = pick(rng, ["blue", "yellow", "black", "green"], [walls, door] if rng.random() < 0.7 else [walls])
    half = Ww / 2 + o

    def roof_y(x):
        return Hw + Hr * max(0.0, 1 - abs(x - Ww / 2) / half)

    out = []
    if True:
        cw = max(k, 0.9)
        cx = U(rng, 0.6, 0.7) * Ww
        top = roof_y(cx) + max(k * 1.2, 1.0)
        bottom = max(Hw + 0.35, roof_y(cx + cw) - 0.3)
        out.append(R(pick(rng, COLORS, [roof, walls]), cx, bottom, cw, top - bottom))
    out.append(R(walls, 0, 0, Ww, Hw))
    out.append(T(roof, (-o, Hw), (Ww + o, Hw), (Ww / 2, Hw + Hr)))
    dw, dh = max(k, U(rng, 1.0, 1.4)), max(k * 1.4, Hw * U(rng, 0.45, 0.6))
    ws = max(k, U(rng, 0.9, 1.2))
    wy = max(dh * 0.45, Hw * 0.42)
    if wy + ws > Hw - 0.3:
        wy = Hw - 0.3 - ws
    if wy < 0.3:
        return None
    if lite:
        side = rng.choice([0, 1])
        dx = U(rng, 0.12, 0.22) * Ww if side == 0 else Ww - dw - U(rng, 0.12, 0.22) * Ww
        wx = Ww - dx - dw / 2 - ws / 2
        if abs((wx + ws / 2) - (dx + dw / 2)) < (ws + dw) / 2 + 0.3:
            return None
        out += [R(door, dx, 0, dw, dh), R(win, wx, wy, ws, ws)]
    else:
        dx = Ww / 2 - dw / 2 + U(rng, -0.1, 0.1) * Ww
        out.append(R(door, dx, 0, dw, dh))
        lx = U(rng, 0.35, max(0.35, dx - ws - 0.4))
        rx = Ww - lx - ws
        if lx + ws > dx - 0.3 or rx < dx + dw + 0.3:
            return None
        out += [R(win, lx, wy, ws, ws), R(win, rx, wy, ws, ws)]
        if rng.random() < 0.6:
            r = max(k / 2, 0.5)
            out.append(E(pick(rng, COLORS, [roof]), Ww / 2, Hw + Hr * 0.38, r, r))
    return out


def boat(rng, k, lite):
    hrx, hry = U(rng, 3, 4), U(rng, 1.4, 1.8)
    mw = max(k, 0.8)
    mx = U(rng, -0.5, 0.5) - mw / 2
    deck_y = hry * 0.3
    mast_top = hry + U(rng, 4.8, 6)
    fh, fw = max(k, 0.9), max(k * 1.2, 1.2)
    sail_base = hry + 0.5
    main_top = mast_top - fh - 0.5
    hull = pick(rng, ["red", "black", "yellow", "green"])
    deck = pick(rng, ["yellow", "red", "black", "green"], [hull])
    mast = pick(rng, ["black", "red", "yellow"], [deck, hull])
    sail = pick(rng, ["yellow", "red", "green", "blue"], [mast])
    sail2 = sail if rng.random() < 0.5 else pick(rng, COLORS, [mast])
    flag = pick(rng, COLORS, [mast, sail])
    out = [
        R(mast, mx, 0, mw, mast_top),
        T(sail, (mx + mw, sail_base), (mx + mw, main_top), (mx + mw + U(rng, 2.2, hrx - 0.2), sail_base)),
        T(sail2, (mx, sail_base), (mx, main_top - U(rng, 0.4, 1.4)), (mx - U(rng, 1.5, 2.6), sail_base)),
        T(flag, (mx + mw, mast_top), (mx + mw, mast_top - fh), (mx + mw + fw, mast_top - fh / 2)),
        E(hull, 0, 0, hrx, hry),
        R(deck, -hrx, deck_y, 2 * hrx, hry - deck_y),
    ]
    if not lite:
        sea_top = -hry * U(rng, 0.45, 0.6)
        out.append(R("blue", -hrx - U(rng, 0.5, 1.5), -hry - 0.75, 2 * hrx + U(rng, 1, 3), sea_top + hry + 0.75))
    return out


def tree(rng, k, lite):
    tw, th = max(k, U(rng, 0.9, 1.5)), U(rng, 2.6, 3.8)
    crx, cry = U(rng, 2.4, 3.3), U(rng, 2.0, 2.8)
    gh = max(k, U(rng, 0.75, 1.0))
    canopy = "green" if rng.random() < 0.8 else "yellow"
    apple = pick(rng, ["red", "yellow", "blue"], [canopy])
    trunk = pick(rng, ["black", "red"], [canopy, apple])
    ground = pick(rng, ["green", "yellow"], [trunk, apple])
    cy = gh * 0.5 + th + cry * 0.55
    out = [R(trunk, -tw / 2, gh * 0.5, tw, th), E(canopy, 0, cy, crx, cry)]
    ar = max(k / 2, 0.45)
    n = 2 if lite else 3

    def inside(_, __):
        ang, rad = U(rng, 0, 2 * math.pi), math.sqrt(U(rng, 0, 1))
        return rad * (crx - ar - 0.3) * math.cos(ang), cy + rad * (cry - ar - 0.3) * math.sin(ang)

    pts = _scatter(rng, n, ar, inside, 0.45)
    if pts is None:
        return None
    out += [E(apple, px, py, ar) for px, py in pts]
    out.append(R(ground, -crx - 0.5, 0, 2 * crx + 1, gh))
    if not lite and rng.random() < 0.5:
        side = rng.choice([-1, 1])
        lo, hi = tw / 2 + ar + 0.5, crx - ar
        if hi > lo:
            out.append(E(apple, side * U(rng, lo, hi), gh + ar * 0.8, ar))
    return out


def face(rng, k, lite):
    hrx, hry = U(rng, 2.4, 3.0), U(rng, 2.9, 3.5)
    head = pick(rng, ["yellow", "red", "green", "blue"])
    eye = pick(rng, ["black", "blue", "green"], [head])
    nose = pick(rng, ["red", "black", "yellow"], [head])
    mouth = pick(rng, ["red", "black", "blue"], [head])
    out = []
    top = "none" if lite else rng.choice(["hair", "hat", "hair"])
    features = [head, eye, nose, mouth]
    hair = None
    if top == "hair":
        hair = pick(rng, ["black", "red", "yellow", "blue", "green"], features)
        out.append(E(hair, 0, hry * 0.5, hrx * U(rng, 1.06, 1.14), hry * 0.88))
    if not lite:
        ear = pick(rng, COLORS, [head, hair])
        er = (max(k, 0.85), max(k, 1.05))
        out += [E(ear, -hrx, 0, *er), E(ear, hrx, 0, *er)]
    out.append(E(head, 0, 0, hrx, hry))
    if top == "hat":
        brim = pick(rng, COLORS, [head])
        crown = pick(rng, COLORS, [brim, head])
        bw, bh = hrx * U(rng, 2.2, 2.6), max(k, 0.6)
        by = hry * 0.72
        out.append(R(crown, -hrx * 0.62, by + bh * 0.5, hrx * 1.24, max(k * 1.5, U(rng, 1.6, 2.2))))
        out.append(R(brim, -bw / 2, by, bw, bh))
    er = max(k / 2, 0.42)
    ey, ex = hry * U(rng, 0.05, 0.25), hrx * U(rng, 0.36, 0.46)
    out += [E(eye, -ex, ey, er, er * 1.15), E(eye, ex, ey, er, er * 1.15)]
    nw, nh = max(k, 0.9) / 2, max(k, 0.9)
    ntop = ey - er * 0.6
    out.append(T(nose, (0, ntop), (-nw, ntop - nh), (nw, ntop - nh)))
    mw, mh = hrx * U(rng, 0.7, 1.0), max(k, 0.6)
    my = min(ntop - nh - 0.4 - mh, -hry * 0.55)
    if my - 0.3 < -hry * 0.85:
        return None
    if rng.random() < 0.5:
        out.append(R(mouth, -mw / 2, my, mw, mh))
    else:
        out.append(E(mouth, 0, my + mh / 2, mw / 2, mh / 2 + 0.05))
    return out


def cat(rng, k, lite):
    brx, bry = U(rng, 2.0, 2.5), U(rng, 2.2, 2.7)
    hr = U(rng, 1.6, 1.95)
    hx, hy = U(rng, -0.3, 0.3) * brx, 2 * bry + hr * 0.45
    body = pick(rng, ["black", "yellow", "red", "blue"])
    head = pick(rng, ["yellow", "black", "red", "green"], [body])
    ears = pick(rng, [body, "black", "red"], [head])
    eye = pick(rng, ["green", "yellow", "blue", "black"], [head])
    nose = pick(rng, ["red", "black", "blue"], [head, eye])
    out = []
    if not lite:
        tail = pick(rng, [head, "black", "red"], [body])
        out.append(E(tail, brx + 0.6, max(k / 2, 0.5) + 0.05, U(rng, 1.5, 1.9), max(k / 2, 0.45)))
    out.append(E(body, 0, bry, brx, bry))
    eh = max(k * 1.6, U(rng, 1.3, 1.6))
    for sgn in (-1, 1):
        out.append(T(ears, (hx + sgn * hr * 0.95, hy + hr * 0.2), (hx + sgn * hr * 0.05, hy + hr * 0.7),
                     (hx + sgn * hr * 0.75, hy + hr * 0.55 + eh)))
    out.append(E(head, hx, hy, hr, hr * 0.88))
    er = (max(k / 2, 0.36), max(k / 2, 0.46))
    out += [E(eye, hx - hr * 0.42, hy + hr * 0.15, *er), E(eye, hx + hr * 0.42, hy + hr * 0.15, *er)]
    if not lite:
        nw, nh = max(k, 0.8) / 2, max(k, 0.8)
        ny = hy + hr * 0.15 - er[1] - 0.15
        out.append(T(nose, (hx - nw, ny), (hx + nw, ny), (hx, ny - nh)))
    return out


def lamp(rng, k, lite):
    tw, legh = U(rng, 5, 6.5), U(rng, 2.2, 3.0)
    tt = max(k, 0.75)
    top = pick(rng, ["black", "red", "blue", "green"])
    leg = pick(rng, COLORS, [top])
    base = pick(rng, COLORS, [top])
    stand = pick(rng, ["black", "red", "blue"], [base, top, "yellow"])
    shade = pick(rng, ["red", "green", "blue"], ["yellow", stand])
    bx = U(rng, -0.8, 0.8)
    lw = max(k, 0.8)
    surface = legh + tt
    sh = U(rng, 2.2, 3.0)
    out = []
    if not lite:
        out += [R(leg, -tw / 2 + 0.4, 0, lw, legh), R(leg, tw / 2 - 0.4 - lw, 0, lw, legh)]
    out.append(R(top, -tw / 2, legh, tw, tt))
    sw_ = max(k, 0.75)
    out.append(R(stand, bx - sw_ / 2, surface, sw_, sh))
    out.append(E(base, bx, surface, max(k * 1.4, 1.3), max(k / 2, 0.5)))
    bulb_y = surface + sh + max(k / 2, 0.45)
    out.append(E("yellow", bx, bulb_y, max(k / 2, 0.65), max(k, 0.9)))
    sw, shh = U(rng, 3.0, 3.8), U(rng, 1.7, 2.2)
    out.append(R(shade, bx - sw / 2, bulb_y, sw, shh))
    return out


def flag(rng, k, lite):
    ph, pw = U(rng, 6.5, 7.8), max(k, 0.75)
    pole = pick(rng, ["black", "yellow", "red"])
    fw, fh = U(rng, 3.6, 4.8), U(rng, 2.4, 3.1)
    fh = max(fh, 3 * k)
    fy = 0.5 + ph - fh - U(rng, 0.3, 0.6)
    cols = rng.sample([c for c in COLORS if c != pole], 3)
    out = [R(pole, 0, 0.5, pw, ph)]
    if not lite:
        out.append(E(pick(rng, COLORS, [pole, cols[0]]), pw / 2, 0.5 + ph + 0.25, max(k / 2, 0.55)))
    out.append(R(cols[0], pw, fy, fw, fh))
    design = rng.choice(["v3", "h3", "hoist", "cross", "disc"])
    x0 = pw
    if design == "v3":
        out += [R(cols[1], x0 + fw / 3, fy, fw / 3, fh), R(cols[2], x0 + 2 * fw / 3, fy, fw / 3, fh)]
    elif design == "h3":
        out += [R(cols[1], x0, fy + fh / 3, fw, fh / 3), R(cols[2], x0, fy + 2 * fh / 3, fw, fh / 3)]
    elif design == "hoist":
        out += [R(cols[1], x0, fy, fw, fh / 2), T(cols[2], (x0, fy), (x0, fy + fh), (x0 + fw * 0.45, fy + fh / 2))]
    elif design == "cross":
        bw = max(k, fh * 0.26)
        out += [R(cols[1], x0 + fw * 0.3, fy, bw, fh), R(cols[2], x0, fy + fh / 2 - bw / 2, fw, bw)]
    else:
        r = max(k / 2, fh * 0.28)
        bh = max(k, fh * 0.25)
        out += [R(cols[1], x0, fy, fw, bh), E(cols[2], x0 + fw / 2, fy + bh + 0.3 + r, r, r)]
    mound = pick(rng, ["green", "yellow"], [pole])
    out.append(E(mound, pw / 2, 0.5, U(rng, 1.6, 2.2), max(k, 0.9)))
    return out


def fish(rng, k, lite):
    brx, bry = U(rng, 2.8, 3.4), U(rng, 1.5, 2.0)
    body = pick(rng, ["yellow", "red", "blue", "green"])
    fin = pick(rng, COLORS, [body])
    eye = pick(rng, ["black", "blue"], [body])
    stripe = pick(rng, COLORS, [body, eye, fin])
    tl, ty = U(rng, 1.4, 2.0), max(k, U(rng, 1.1, 1.6))
    out = [T(fin, (-brx * 0.7, 0), (-brx - tl, ty), (-brx - tl, -ty))]
    fh = max(k * 1.2, U(rng, 1.1, 1.5))
    out.append(T(fin, (-brx * 0.5, bry * 0.55), (brx * 0.3, bry * 0.7), (-brx * 0.5, bry + fh)))
    if not lite:
        out.append(T(fin, (-brx * 0.25, -bry * 0.6), (brx * 0.35, -bry * 0.6), (-brx * 0.2, -bry - max(k * 1.2, U(rng, 1.0, 1.3)))))
    out.append(E(body, 0, 0, brx, bry))
    out.append(E(stripe, -brx * U(rng, 0.05, 0.2), 0, max(k / 2, 0.45), bry * 0.78))
    er = max(k / 2, 0.4)
    out.append(E(eye, brx * 0.55, bry * 0.22, er))
    if not lite:
        bub = pick(rng, ["blue", "black", "green"], [])
        b1 = max(k / 2, 0.42)
        out.append(E(bub, brx + 1.0, bry * 0.45, b1))
        if rng.random() < 0.6:
            b2 = max(k / 2, 0.5)
            out.append(E(bub, brx + 1.5 + b1 + b2 * 0.2, bry * 0.45 + b1 + b2 + 0.6, b2))
    return out


def cup(rng, k, lite):
    bw, bh = U(rng, 3.0, 3.6), U(rng, 3.2, 4.0)
    body = pick(rng, ["red", "blue", "yellow", "green"])
    coffee = pick(rng, ["black", "red", "yellow"], [body])
    band = pick(rng, COLORS, [body, coffee])
    handle = pick(rng, COLORS, [body, coffee, band])
    saucer = pick(rng, ["blue", "red", "green", "yellow"], [body, handle])
    out = [E(saucer, 0, 0, bw / 2 + U(rng, 1.0, 1.5), max(k / 2, 0.45))]
    hrx, hry = max(k, U(rng, 1.0, 1.2)), max(k, U(rng, 1.1, 1.4))
    out.append(E(handle, bw / 2, bh * 0.55, hrx, hry))
    out.append(R(body, -bw / 2, 0, bw, bh))
    out.append(E(coffee, 0, bh, bw / 2, max(k / 2, 0.45)))
    out.append(R(band, -bw / 2, bh * U(rng, 0.25, 0.4), bw, max(k, 0.6)))
    n = 1 if lite else rng.choice([2, 3])
    steam = pick(rng, ["blue", "black", "green"], [coffee])
    srx, sry = max(k / 2, 0.4), max(k, U(rng, 0.9, 1.2))
    xs = [0.0] if n == 1 else [(-0.5 + i / (n - 1)) * bw * 0.7 for i in range(n)]
    for i, x in enumerate(xs):
        if n > 1 and bw * 0.7 / (n - 1) < 2 * srx + 0.35:
            return None
        out.append(E(steam, x, bh + 0.45 + 0.6 + sry + (0.4 if i % 2 else 0), srx, sry))
    return out


def key(rng, k, lite):
    br = U(rng, 1.5, 1.9)
    sl, sh = U(rng, 4.6, 5.6), max(k, U(rng, 0.8, 1.0))
    shaft = pick(rng, ["yellow", "black", "blue", "red"])
    collar = not lite
    bow = shaft if collar else pick(rng, COLORS, [shaft])
    hole = pick(rng, COLORS, [bow])
    gap = 0.6 if collar else -0.3
    out = [R(shaft, br + gap, -sh / 2, sl, sh), E(bow, 0, 0, br, br * U(rng, 0.9, 1.1))]
    out.append(E(hole, -br * 0.15, 0, max(k / 2, br * 0.36)))
    ccol = None
    if collar:
        ccol = pick(rng, COLORS, [shaft, hole])
        out.append(R(ccol, br - 0.25, -sh / 2 - 0.4, max(k, gap + 0.6), sh + 0.8))
    teeth = pick(rng, COLORS, [shaft, ccol])
    n = rng.choice([2, 3]) if not lite else 2
    tw = max(k, 0.75)
    x = br + gap + sl - tw - U(rng, 0.0, 0.3)
    for _ in range(n):
        if x < br + gap + 1.2:
            return None
        th = max(k, U(rng, 0.8, 1.4))
        out.append(R(teeth, x, -sh / 2 - th, tw, th))
        x -= tw + max(0.45, k * 0.6)
    return out


def bird(rng, k, lite):
    brx, bry = U(rng, 2.0, 2.5), U(rng, 1.4, 1.7)
    bt = max(k, 0.8)
    by = bt + bry * 0.8
    body = pick(rng, ["blue", "red", "yellow", "green", "black"])
    branch = pick(rng, ["black", "green", "yellow"], [body])
    tail = pick(rng, COLORS, [body])
    wing = pick(rng, COLORS, [body, tail])
    head = pick(rng, COLORS, [body, wing])
    eye = pick(rng, ["black", "yellow", "blue"], [head, body])
    beak = pick(rng, ["yellow", "red", "black"], [head, eye])
    hr = max(k, U(rng, 0.95, 1.2))
    hx, hy = brx * 0.72, by + bry * 0.85
    out = [R(branch, -brx - U(rng, 1, 2), 0, 2 * brx + U(rng, 2.5, 3.5), bt)]
    tlen = max(k * 1.6, 1.5)
    out.append(T(tail, (-brx * 0.6, by + 0.3), (-brx - tlen, by + max(k, U(rng, 0.9, 1.6))), (-brx - tlen + 0.2, by - 0.4)))
    out.append(E(body, 0, by, brx, bry))
    if not lite:
        out.append(E(wing, -brx * 0.15, by - bry * 0.05, brx * 0.55, max(k / 2, bry * 0.45)))
    out.append(E(head, hx, hy, hr, hr))
    if not lite:
        out.append(E(eye, hx + hr * 0.3, hy + hr * 0.2, max(k / 2, 0.3)))
    bh = max(k, 0.7) / 2
    out.append(T(beak, (hx + hr * 0.8, hy + bh), (hx + hr * 0.8, hy - bh), (hx + hr + max(k, U(rng, 0.8, 1.2)), hy - 0.1)))
    return out


def mushroom(rng, k, lite):
    crx, cry = U(rng, 2.8, 3.5), U(rng, 1.6, 2.1)
    sw, sh = max(k, U(rng, 1.4, 2.0)), U(rng, 2.4, 3.2)
    cap = pick(rng, ["red", "red", "yellow", "blue"])
    stem = pick(rng, ["yellow", "black"], [cap])
    spot = pick(rng, ["yellow", "black", "green"], [cap])
    gh = max(k, 0.8)
    cy = gh * 0.5 + sh
    out = [R(stem, -sw / 2, gh * 0.5, sw, sh - cry * 0.4), E(cap, 0, cy, crx, cry)]
    n = 3 if lite else rng.choice([3, 4])
    sr = max(k / 2, 0.45)

    def inside(_, __):
        px = U(rng, -crx + sr + 0.3, crx - sr - 0.3)
        lim = cry * math.sqrt(max(0, 1 - (abs(px) + sr) ** 2 / crx ** 2))
        lo, hi = cry * 0.1 + sr * 0.3, lim - sr - 0.15
        if hi < lo:
            return None, None
        return px, cy + U(rng, lo, hi)

    pts = _scatter(rng, n, sr, inside, 0.4)
    if pts is None:
        return None
    out += [E(spot, px, py, sr) for px, py in pts]
    if not lite:
        out.append(R(pick(rng, ["green", "black"], [stem]), -crx - 0.3, 0, 2 * crx + 0.6, gh))
    return out


def car(rng, k, lite):
    bw, bh = U(rng, 6, 7.4), max(k * 1.5, U(rng, 1.6, 2.1))
    wr = max(k / 2 + 0.4, U(rng, 0.8, 1.05))
    body = pick(rng, ["red", "blue", "yellow", "green"])
    cab = pick(rng, COLORS, [body, "black"])
    win = pick(rng, ["blue", "black", "yellow"], [cab])
    y0 = wr * 0.9
    cx0, cw = bw * U(rng, 0.15, 0.3), bw * U(rng, 0.48, 0.56)
    ch = max(k + 0.6, U(rng, 1.4, 1.8))
    out = [R(body, 0, y0, bw, bh), R(cab, cx0, y0 + bh, cw, ch)]
    if lite:
        out.append(R(win, cx0 + 0.3, y0 + bh + 0.3, cw - 0.6, ch - 0.6))
    else:
        ww = (cw - 0.9) / 2
        if ww < k:
            return None
        out += [R(win, cx0 + 0.3, y0 + bh + 0.3, ww, ch - 0.6), R(win, cx0 + 0.6 + ww, y0 + bh + 0.3, ww, ch - 0.6)]
    out += [E("black", bw * 0.22, wr, wr), E("black", bw * 0.78, wr, wr)]
    if not lite:
        if rng.random() < 0.6:
            hub = pick(rng, ["yellow", "red", "blue"], [body])
            hr = max(k / 2, wr * 0.42)
            if hr < wr - 0.3:
                out += [E(hub, bw * 0.22, wr, hr), E(hub, bw * 0.78, wr, hr)]
        lr = max(k / 2, 0.36)
        out.append(E(pick(rng, ["yellow", "red"], [body]), bw - lr - 0.3, y0 + bh * 0.62, lr))
    return out


def rocket(rng, k, lite):
    bw, bh = max(k * 2, U(rng, 1.9, 2.4)), U(rng, 4.4, 5.4)
    fl = max(k * 2, U(rng, 1.8, 2.4))
    body = pick(rng, ["red", "blue", "yellow", "green", "black"])
    nose = pick(rng, COLORS, [body])
    flame = pick(rng, ["yellow", "red"], [body])
    fin = pick(rng, COLORS, [body, flame])
    out = [T(flame, (-bw * 0.5, fl + 0.3), (bw * 0.5, fl + 0.3), (0, 0))]
    if not lite:
        out.append(T(pick(rng, ["red", "yellow"], [flame, body]), (-bw * 0.25, fl + 0.3), (bw * 0.25, fl + 0.3), (0, fl * 0.5)))
    fw = max(k, U(rng, 1.1, 1.5))
    for sgn in (-1, 1):
        out.append(T(fin, (sgn * bw / 2, fl + bh * 0.35), (sgn * bw / 2, fl - 0.2), (sgn * (bw / 2 + fw), fl - 0.2)))
    out.append(R(body, -bw / 2, fl, bw, bh))
    out.append(T(nose, (-bw / 2, fl + bh), (bw / 2, fl + bh), (0, fl + bh + max(k * 1.2, U(rng, 1.4, 2.0)))))
    if not lite or rng.random() < 0.5:
        out.append(E(pick(rng, ["blue", "yellow", "black"], [body]), 0, fl + bh * 0.62, max(k / 2, bw * 0.27)))
    return out


def flower(rng, k, lite):
    pw, ph = U(rng, 2.4, 3.1), max(k, U(rng, 1.6, 2.1))
    sl = U(rng, 2.6, 3.4)
    pr = max(k * 0.7, U(rng, 0.85, 1.05))
    d = pr * 1.28
    p1 = pick(rng, ["red", "blue", "yellow"])
    p2 = pick(rng, ["red", "blue", "yellow", "black"], [p1])
    centre = pick(rng, COLORS, [p1, p2])
    stem = pick(rng, ["green", "black"], [p1, p2, centre])
    pot = pick(rng, ["red", "black", "blue", "yellow"], [stem])
    sw = max(k, 0.75)
    fy = ph + sl + d
    out = [R(stem, -sw / 2, ph - 0.3, sw, sl + 0.3)]
    if not lite:
        lrx = max(k, U(rng, 0.9, 1.2))
        side = rng.choice([-1, 1])
        out.append(E(pick(rng, ["green", "yellow"], [stem, p1, p2]), side * (sw / 2 + lrx * 0.85), ph + sl * 0.5, lrx,
                     max(k / 2, 0.5)))
    out += [E(p1, 0, fy + d, pr), E(p2, -d, fy, pr), E(p2, d, fy, pr), E(p1, 0, fy - d, pr)]
    out.append(E(centre, 0, fy, max(k / 2, pr * 0.72)))
    out.append(R(pot, -pw / 2, 0, pw, ph))
    if not lite:
        out.append(R(pick(rng, COLORS, [pot, stem]), -pw / 2 - 0.3, ph - 0.1, pw + 0.6, max(k, 0.6)))
    return out


def icecream(rng, k, lite):
    cw, chh = U(rng, 2.6, 3.2), U(rng, 3.8, 4.6)
    sr = U(rng, 1.45, 1.75)
    cone = "yellow"
    cols = []
    for _ in range(3):
        cols.append(pick(rng, ["red", "green", "black", "blue", "yellow"], [cols[-1] if cols else cone]))
    out = [T(cone, (-cw / 2 - 0.2, chh), (cw / 2 + 0.2, chh), (0, 0))]
    y = chh + sr * 0.45
    centres = []
    for _ in cols:
        centres.append((U(rng, -0.25, 0.25), y))
        y += sr * 1.15
    tx, ty = centres[-1]
    cherry = pick(rng, ["red", "black"], [cols[-1]])
    if not lite:
        out.append(R(pick(rng, COLORS, [cols[-1], cherry]), tx + sr * 0.35, ty + 0.2, max(k, 0.6), sr * 1.3))
    for (cx, cy), c in zip(centres, cols):
        out.append(E(c, cx, cy, sr, sr * 0.82))
    out.append(E(cherry, tx - 0.4, ty + sr * 0.82 + 0.25, max(k / 2, 0.5)))
    return out


def robot(rng, k, lite):
    bw, bh = U(rng, 3.2, 4.0), U(rng, 2.4, 3.0)
    hw, hh = U(rng, 2.4, 3.0), max(k * 2, U(rng, 1.8, 2.3))
    lh = max(k * 1.2, U(rng, 1.3, 1.8))
    body = pick(rng, ["blue", "red", "green", "yellow", "black"])
    head = pick(rng, COLORS, [body])
    limb = pick(rng, COLORS, [body])
    eye = pick(rng, ["yellow", "red", "black", "blue"], [head])
    lw = max(k, 0.9)
    out = [R(limb, -bw * 0.4, 0, lw, lh), R(limb, bw * 0.4 - lw, 0, lw, lh)]
    if bw * 0.8 - 2 * lw < 0.4:
        return None
    out.append(R(body, -bw / 2, lh, bw, bh))
    if not lite:
        aw = max(k, 0.75)
        out += [R(limb, -bw / 2 - aw, lh + bh * 0.25, aw, bh * 0.6), R(limb, bw / 2, lh + bh * 0.25, aw, bh * 0.6)]
    hy = lh + bh
    out.append(R(head, -hw / 2, hy, hw, hh))
    er = max(k / 2, 0.38)
    if hw * 0.48 - 2 * er < 0.35:
        return None
    out += [E(eye, -hw * 0.24, hy + hh * 0.58, er), E(eye, hw * 0.24, hy + hh * 0.58, er)]
    if not lite:
        aw = max(k, 0.75)
        out.append(R(pick(rng, COLORS, [head]), -aw / 2, hy + hh, aw, max(k, U(rng, 0.8, 1.2))))
    return out


def traffic(rng, k, lite):
    r = max(k / 2, U(rng, 0.62, 0.78))
    hw = max(U(rng, 2.0, 2.5), 2 * r + 0.7)
    hh = max(hw * U(rng, 2.3, 2.6), 6 * r + 1.4)
    ph = U(rng, 2.8, 3.6)
    pole = pick(rng, ["blue", "yellow", "red"])
    out = []
    if not lite:
        out.append(R(pick(rng, COLORS, [pole]), -1.3, 0, 2.6, max(k, 0.75)))
    pw = max(k, 0.9)
    out.append(R(pole, -pw / 2, 0.4, pw, ph))
    hy = 0.4 + ph
    out.append(R("black", -hw / 2, hy, hw, hh))
    for i, c in enumerate(["green", "yellow", "red"]):
        out.append(E(c, 0, hy + hh * (2 * i + 1) / 6, r))
    return out


def clock(rng, k, lite):
    fr = U(rng, 2.4, 2.9)
    fy = 0.9 + fr * 0.85
    face_c = pick(rng, ["yellow", "blue", "green", "red"])
    bell = pick(rng, ["red", "black", "blue", "yellow"], [face_c])
    leg = pick(rng, ["black", "red", "blue"], [face_c])
    h1 = pick(rng, ["black", "red", "blue"], [face_c])
    h2 = pick(rng, COLORS, [face_c, h1])
    cc = pick(rng, COLORS, [face_c, h1, h2])
    br = max(k, U(rng, 0.9, 1.15))
    out = [E(bell, -fr * 0.72, fy + fr * 0.8, br, br * 0.8), E(bell, fr * 0.72, fy + fr * 0.8, br, br * 0.8)]
    if not lite:
        for sgn in (-1, 1):
            out.append(T(leg, (sgn * fr * 0.62, fy - fr * 0.55), (sgn * fr * 0.15, fy - fr * 0.9), (sgn * fr * 0.85, 0)))
    out.append(E(face_c, 0, fy, fr))
    hw = max(k, 0.75)
    a, b = rng.sample(["up", "down", "left", "right"], 2)
    for c, direction, length in ((h1, a, fr * 0.5), (h2, b, fr * 0.72)):
        length = max(length, k * 1.5)
        if direction == "up":
            out.append(R(c, -hw / 2, fy, hw, length))
        elif direction == "down":
            out.append(R(c, -hw / 2, fy - length, hw, length))
        elif direction == "right":
            out.append(R(c, 0, fy - hw / 2, length, hw))
        else:
            out.append(R(c, -length, fy - hw / 2, length, hw))
    if not lite:
        out.append(E(cc, 0, fy, max(k / 2, 0.5)))
    return out


def ladybird(rng, k, lite):
    brx, bry = U(rng, 2.4, 3.0), U(rng, 2.8, 3.4)
    body = "red" if rng.random() < 0.75 else "yellow"
    hrx, hry = brx * 0.52, max(k, brx * 0.42)
    hcy = bry + hry * 0.2
    out = [E("black", 0, hcy, hrx, hry), E(body, 0, 0, brx, bry)]
    n = 3 if lite else rng.choice([4, 5, 6])
    sr = max(k / 2, U(rng, 0.42, 0.6))
    head_bottom = hcy - hry

    def inside(_, __):
        px, py = U(rng, -brx, brx) * 0.8, U(rng, -bry, bry) * 0.8
        if (px / (brx - sr - 0.2)) ** 2 + (py / (bry - sr - 0.2)) ** 2 > 1 or py + sr > head_bottom - 0.45:
            return None, None
        return px, py

    pts = _scatter(rng, n, sr, inside, 0.4, tries=600)
    if pts is None:
        return None
    out += [E("black", px, py, sr) for px, py in pts]
    return out


def snail(rng, k, lite):
    frx, fry = U(rng, 3.4, 4.0), max(k / 2, U(rng, 0.55, 0.7))
    body = pick(rng, ["yellow", "green", "red"])
    s1 = pick(rng, ["red", "blue", "black", "yellow"], [body])
    s2 = pick(rng, COLORS, [s1, body])
    s3 = pick(rng, COLORS, [s1, s2])
    sr = U(rng, 2.0, 2.4)
    sx, sy = -frx * 0.2, fry + sr * 0.85
    head = pick(rng, COLORS, [body, s1])
    hx, hy = frx * 0.75, fry + 0.6
    out = []
    if not lite:
        out.append(R(pick(rng, COLORS, [head]), hx + 0.1, hy, max(k, 0.75), max(k * 1.5, U(rng, 1.4, 1.8))))
    out.append(E(body, 0, fry, frx, fry))
    out.append(E(head, hx, hy, max(k, 0.85), max(k, 0.95)))
    out.append(E(s1, sx, sy, sr, sr * 0.95))
    out.append(E(s2, sx + sr * 0.12, sy - sr * 0.05, sr * 0.64, sr * 0.6))
    out.append(E(s3, sx + sr * 0.2, sy - sr * 0.08, max(k / 2, sr * 0.3), max(k / 2, sr * 0.28)))
    return out


TEMPLATES = {
    "house": house, "boat": boat, "tree": tree, "face": face, "cat": cat, "lamp": lamp, "flag": flag,
    "fish": fish, "cup": cup, "key": key, "bird": bird, "mushroom": mushroom, "car": car, "rocket": rocket,
    "flower": flower, "ice cream": icecream, "robot": robot, "traffic light": traffic, "alarm clock": clock,
    "ladybird": ladybird, "snail": snail,
}
# things that can stand in a landscape at half size
SCENE_TEMPLATES = ["house", "tree", "cat", "flag", "mushroom", "car", "rocket", "flower", "robot", "traffic light",
                   "ladybird", "snail", "bird"]
