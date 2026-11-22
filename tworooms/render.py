"""Every image the service draws: the describer's painted picture, the builder's crisp board, the difference,
thumbnails and Open Graph previews. Pure functions of their inputs (no database)."""
import hashlib
import io
import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import BOARD, CELLS
from .score import diff_mask

FONTS = Path(__file__).parent / "static" / "fonts"

PIGMENT = {
    "red": (196, 52, 42), "blue": (38, 76, 164), "yellow": (236, 186, 38),
    "green": (44, 128, 72), "black": (38, 35, 40),
}
PAPER = (241, 234, 218)
FRAME = (46, 42, 40)
CRISP = {
    "red": (200, 45, 38), "blue": (35, 80, 180), "yellow": (240, 190, 30),
    "green": (36, 140, 70), "black": (30, 30, 34),
}
BOARD_PAPER = (246, 242, 232)
INK = (60, 56, 52)
MARK = (214, 28, 160)

WOBBLE = 0.03   # units; the spec allows 0.05


@lru_cache(maxsize=16)
def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def jpeg_bytes(img: Image.Image, quality: int = 86) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def key(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- outlines with wobble

def _bleed(true: float, wobbled: float) -> float:
    """A point that lies on the board's edge is pushed past it, so a shape along the edge stays flush with the frame."""
    if abs(true) < 1e-9:
        return -0.2
    if abs(true - BOARD) < 1e-9:
        return BOARD + 0.2
    return wobbled


def _noise_fn(rng, amp):
    waves = [(rng.uniform(0.9, 1.3), rng.uniform(0, 2 * math.pi), 0.35),
             (rng.uniform(2.0, 3.0), rng.uniform(0, 2 * math.pi), 0.40),
             (rng.uniform(4.5, 6.5), rng.uniform(0, 2 * math.pi), 0.25)]
    return lambda s: amp * sum(a * math.sin(2 * math.pi * s / lam + ph) for lam, ph, a in waves)


def _polygon_outline(corners, noise, step=0.06):
    """Corners counter-clockwise (y up). Points along each edge displaced along the outward normal."""
    n = len(corners)
    normals = []
    for i in range(n):
        (ax, ay), (bx, by) = corners[i], corners[(i + 1) % n]
        L = math.hypot(bx - ax, by - ay) or 1.0
        normals.append(((by - ay) / L, -(bx - ax) / L))
    pts, s = [], 0.0
    for i in range(n):
        (ax, ay), (bx, by) = corners[i], corners[(i + 1) % n]
        L = math.hypot(bx - ax, by - ay)
        k = max(1, int(L / step))
        prev = normals[i - 1]
        for j in range(k):
            t = j / k
            x, y = ax + (bx - ax) * t, ay + (by - ay) * t
            d = noise(s + L * t)
            if j == 0:
                nx, ny = prev[0] + normals[i][0], prev[1] + normals[i][1]
                m = max(abs(nx), abs(ny), 1.0)
                nx, ny = nx / m, ny / m
            else:
                nx, ny = normals[i]
            pts.append((_bleed(x, x + d * nx), _bleed(y, y + d * ny)))
        s += L
    return pts


def outline(s: dict, rng, amp: float = WOBBLE):
    noise = _noise_fn(rng, amp)
    if s["shape"] == "rect":
        x0, y0, x1, y1 = s["x"], s["y"], s["x"] + s["w"], s["y"] + s["h"]
        return _polygon_outline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], noise)
    if s["shape"] == "triangle":
        pts = [tuple(p) for p in s["points"]]
        (ax, ay), (bx, by), (cx, cy) = pts
        if (bx - ax) * (cy - ay) - (by - ay) * (cx - ax) < 0:
            pts = [pts[0], pts[2], pts[1]]
        return _polygon_outline(pts, noise)
    cx, cy, rx, ry = s["cx"], s["cy"], s["rx"], s["ry"]
    k = max(96, int(2 * math.pi * max(rx, ry) / 0.04))
    out = []
    for i in range(k):
        th = 2 * math.pi * i / k
        c, sn = math.cos(th), math.sin(th)
        nx, ny = c / rx, sn / ry
        L = math.hypot(nx, ny)
        d = noise(th * (rx + ry) / 2)
        out.append((cx + rx * c + d * nx / L, cy + ry * sn + d * ny / L))
    return out


# ---------------------------------------------------------------- the describer's picture



def _smooth_noise(rng, shape, cells):
    """Low-frequency noise in [-1, 1] of the given (h, w), from a coarse random grid upscaled."""
    h, w = shape
    small = rng.uniform(-1, 1, size=(max(2, cells[0]), max(2, cells[1]))).astype(np.float32)
    img = Image.fromarray(((small + 1) * 127.5).astype(np.uint8), "L").resize((w, h), Image.BICUBIC)
    return np.asarray(img, dtype=np.float32) / 127.5 - 1


def painted(shapes: list[dict], level: int, word: str, seed: str, size: int = 800) -> Image.Image:
    """The describer's picture: hand-painted look, dark frame, round word on the frame, tick marks on levels 1-2."""
    rng_py = __import__("random").Random(seed)
    rng = np.random.default_rng(int(hashlib.sha1(seed.encode()).hexdigest()[:8], 16))
    frame = round(size * 0.05)
    side = size - 2 * frame
    ss = 2
    S = side * ss
    u = S / BOARD
    paper = np.empty((S, S, 3), np.float32)
    paper[:] = PAPER
    paper *= (1 + 0.025 * _smooth_noise(rng, (S, S), (9, 9)))[..., None]
    paper *= (1 + 0.012 * _smooth_noise(rng, (S, S), (60, 60)))[..., None]
    paper *= (1 + 0.010 * _smooth_noise(rng, (S, S), (220, 220)))[..., None]
    canvas = paper
    for s in shapes:
        pts = outline(s, rng_py)
        poly = [(x * u, (BOARD - y) * u) for x, y in pts]
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        bx0, by0 = max(0, int(min(xs)) - 4), max(0, int(min(ys)) - 4)
        bx1, by1 = min(S, int(max(xs)) + 5), min(S, int(max(ys)) + 5)
        if bx1 <= bx0 or by1 <= by0:
            continue
        m_img = Image.new("L", (bx1 - bx0, by1 - by0), 0)
        ImageDraw.Draw(m_img).polygon([(x - bx0, y - by0) for x, y in poly], fill=255)
        eroded = m_img.filter(ImageFilter.MinFilter(7))
        m = np.asarray(m_img, np.float32) / 255
        edge = m - np.asarray(eroded, np.float32) / 255
        h, w = m.shape
        base = np.array(PIGMENT[s["color"]], np.float32) * rng.uniform(0.97, 1.03, size=3).astype(np.float32)
        tone = 1 + 0.045 * _smooth_noise(rng, (h, w), (max(2, h // 90), max(2, w // 90)))
        horizontal = rng.random() < 0.5
        strokes = _smooth_noise(rng, (h, w), (max(2, h // 18), 3) if horizontal else (3, max(2, w // 18)))
        tone = tone + 0.03 * strokes
        layer = base[None, None, :] * tone[..., None] * (1 - 0.10 * edge)[..., None]
        region = canvas[by0:by1, bx0:bx1]
        region[:] = region * (1 - m[..., None]) + layer * m[..., None]
    img = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8), "RGB").resize((side, side), Image.LANCZOS)

    out = Image.new("RGB", (size, size), FRAME)
    fr = np.asarray(out, np.float32) * (1 + 0.05 * _smooth_noise(rng, (size, size), (14, 14)))[..., None]
    out = Image.fromarray(np.clip(fr, 0, 255).astype(np.uint8), "RGB")
    out.paste(img, (frame, frame))
    d = ImageDraw.Draw(out)
    if level <= 2:
        tick = round(frame * 0.32)
        step = side / BOARD
        for i in range(1, int(BOARD)):
            p = frame + round(i * step)
            col = (205, 198, 182)
            d.line([(p, frame - tick), (p, frame - 1)], fill=col, width=2)
            d.line([(p, frame + side), (p, frame + side + tick - 1)], fill=col, width=2)
            d.line([(frame - tick, p), (frame - 1, p)], fill=col, width=2)
            d.line([(frame + side, p), (frame + side + tick - 1, p)], fill=col, width=2)
    f = font("EBGaramond12-Regular.ttf", round(frame * 0.62))
    label = " ".join(word.upper())
    tw = d.textlength(label, font=f)
    d.text(((size - tw) / 2, size - frame / 2), label, font=f, fill=(222, 212, 190), anchor="lm")
    return out


# ---------------------------------------------------------------- crisp boards

def _draw_crisp(shapes, side, ss=3, background=BOARD_PAPER, colours=CRISP, alpha_mix=None):
    S = side * ss
    u = S / BOARD
    img = Image.new("RGB", (S, S), background)
    d = ImageDraw.Draw(img)
    for s in shapes:
        col = colours[s["color"]]
        if alpha_mix is not None:
            col = tuple(round(c * (1 - alpha_mix) + b * alpha_mix) for c, b in zip(col, background))
        if s["shape"] == "rect":
            d.rectangle([s["x"] * u, (BOARD - s["y"] - s["h"]) * u, (s["x"] + s["w"]) * u - 1, (BOARD - s["y"]) * u - 1], fill=col)
        elif s["shape"] == "ellipse":
            d.ellipse([(s["cx"] - s["rx"]) * u, (BOARD - s["cy"] - s["ry"]) * u,
                       (s["cx"] + s["rx"]) * u - 1, (BOARD - s["cy"] + s["ry"]) * u - 1], fill=col)
        else:
            d.polygon([(x * u, (BOARD - y) * u) for x, y in s["points"]], fill=col)
    return img.resize((side, side), Image.LANCZOS)


def plain(shapes: list[dict], side: int = 400) -> Image.Image:
    """The board alone, crisp, with a thin frame: for thumbnails and previews."""
    img = _draw_crisp(shapes, side)
    ImageDraw.Draw(img).rectangle([0, 0, side - 1, side - 1], outline=(120, 114, 104), width=max(1, side // 200))
    return img


def _board_frame(inner: Image.Image, title: str, right: str = "", labels: bool = True, grid: bool = False,
                 empty_text: str | None = None) -> Image.Image:
    side = inner.width
    L, B, Tm, Rm = (40, 36, 46, 20) if labels else (16, 16, 46, 16)
    W, H = L + side + Rm, Tm + side + B
    out = Image.new("RGB", (W, H), (251, 250, 247))
    out.paste(inner, (L, Tm))
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    step = side / BOARD
    if grid:
        for i in range(1, int(BOARD)):
            p = round(i * step)
            a = 70 if i == 5 else 38
            d.line([(L + p, Tm), (L + p, Tm + side)], fill=(40, 40, 40, a), width=1)
            d.line([(L, Tm + p), (L + side, Tm + p)], fill=(40, 40, 40, a), width=1)
    out = Image.alpha_composite(out.convert("RGBA"), over).convert("RGB")
    d = ImageDraw.Draw(out)
    d.rectangle([L - 1, Tm - 1, L + side, Tm + side], outline=(90, 86, 80), width=2)
    if labels:
        f = font("DejaVuSans.ttf", 13)
        for i in range(0, int(BOARD) + 1):
            p = round(i * step)
            d.line([(L + p, Tm + side + 1), (L + p, Tm + side + 6)], fill=(110, 105, 98), width=1)
            d.text((L + p, Tm + side + 8), str(i), font=f, fill=(110, 105, 98), anchor="mt")
            d.line([(L - 6, Tm + side - p), (L - 2, Tm + side - p)], fill=(110, 105, 98), width=1)
            d.text((L - 9, Tm + side - p), str(i), font=f, fill=(110, 105, 98), anchor="rm")
    ft = font("DejaVuSans-Bold.ttf", 17)
    d.text((L, Tm / 2), title, font=ft, fill=INK, anchor="lm")
    if right:
        fr = font("DejaVuSans.ttf", 14)
        d.text((L + side, Tm / 2), right, font=fr, fill=(110, 105, 98), anchor="rm")
    if empty_text:
        fe = font("EBGaramond12-Italic.ttf", 30)
        d.text((L + side / 2, Tm + side / 2), empty_text, font=fe, fill=(150, 142, 128), anchor="mm")
    return out


def board(shapes: list[dict], word: str = "", grid: bool = False, labels: bool = True, side: int = 720,
          who: str = "the builder's board") -> Image.Image:
    """What the builder has placed so far. Says in words when nothing has been placed."""
    inner = _draw_crisp(shapes, side)
    title = f"{word.upper()} · {who}" if word else who
    n = len(shapes)
    right = "nothing placed" if n == 0 else f"{n} shape{'s' if n != 1 else ''}"
    empty = "Empty: nothing has been placed yet." if n == 0 else None
    return _board_frame(inner, title, right, labels=labels, grid=grid, empty_text=empty)


def _diff_inner(picture, build, side):
    inner = _draw_crisp(picture, side, alpha_mix=0.6)
    mask = diff_mask(picture, build)
    arr = np.asarray(inner, np.float32)
    m_img = Image.fromarray((mask[::-1, :] * 255).astype(np.uint8), "L").resize((side, side), Image.NEAREST)
    m = np.asarray(m_img, np.float32)[..., None] / 255
    arr = arr * (1 - 0.78 * m) + np.array(MARK, np.float32) * 0.78 * m
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB"), mask


LIGHT_FRAME = (208, 200, 186)


def framed(inner: Image.Image, size: int, colour=LIGHT_FRAME) -> Image.Image:
    """A board in the same frame geometry as the painted picture, so the two line up side by side."""
    frame = round(size * 0.05)
    out = Image.new("RGB", (size, size), colour)
    out.paste(inner.resize((size - 2 * frame, size - 2 * frame), Image.LANCZOS), (frame, frame))
    return out


def framed_board(shapes: list[dict], size: int = 800) -> Image.Image:
    return framed(_draw_crisp(shapes, size - 2 * round(size * 0.05)), size)


def framed_diff(picture: list[dict], build: list[dict], size: int = 800) -> Image.Image:
    return framed(_diff_inner(picture, build, size - 2 * round(size * 0.05))[0], size)


def diff(picture: list[dict], build: list[dict], word: str = "", side: int = 720) -> Image.Image:
    """The picture washed out, with every cell where the build differs marked."""
    inner, mask = _diff_inner(picture, build, side)
    n = int(mask.sum())
    title = f"{word.upper()} · where they differ" if word else "where they differ"
    return _board_frame(inner, title, f"{n} of {CELLS * CELLS} cells differ", labels=True, grid=False)


# ---------------------------------------------------------------- previews

def thumb(img: Image.Image, side: int) -> Image.Image:
    w, h = img.size
    scale = side / max(w, h)
    return img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)


def og_pair(picture_img: Image.Image, build: list[dict] | None, caption: str, sub: str = "") -> Image.Image:
    W, H = 1200, 630
    out = Image.new("RGB", (W, H), (244, 239, 228))
    d = ImageDraw.Draw(out)
    side = 470
    top = 40
    p = thumb(picture_img, side)
    if build is None:
        out.paste(p, ((W - side) // 2, top))
    else:
        out.paste(p, (W // 2 - side - 25, top))
        b = framed_board(build, side)
        out.paste(b, (W // 2 + 25, top))
        f = font("DejaVuSans.ttf", 18)
        d.text((W // 2 - side // 2 - 25, top + side + 18), "the picture", font=f, fill=(110, 104, 96), anchor="mt")
        d.text((W // 2 + side // 2 + 25, top + side + 18), "what was built from the words", font=f, fill=(110, 104, 96), anchor="mt")
    fc = font("DejaVuSans-Bold.ttf", 26)
    d.text((W // 2, H - 52), caption, font=fc, fill=INK, anchor="mm")
    if sub:
        d.text((W // 2, H - 22), sub, font=font("DejaVuSans.ttf", 18), fill=(110, 104, 96), anchor="mm")
    return out


def _wrap(d, text, f, width):
    lines = []
    for para in text.splitlines() or [""]:
        words, cur = para.split(), ""
        for w in words:
            t = f"{cur} {w}".strip()
            if d.textlength(t, font=f) <= width:
                cur = t
            else:
                if cur:
                    lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def og_letter(text: str, caption: str, sub: str = "") -> Image.Image:
    """An open letter: its words on paper."""
    W, H = 1200, 630
    rng = np.random.default_rng(int(key(text)[:8], 16))
    arr = np.empty((H, W, 3), np.float32)
    arr[:] = PAPER
    arr *= (1 + 0.03 * _smooth_noise(rng, (H, W), (8, 14)))[..., None]
    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    d = ImageDraw.Draw(out)
    box_w, box_h = W - 160, H - 170
    for size in (40, 36, 32, 28, 25, 22, 20):
        f = font("EBGaramond12-Italic.ttf", size)
        lines = _wrap(d, text, f, box_w)
        lh = size * 1.25
        if len(lines) * lh <= box_h:
            break
    max_lines = int(box_h // lh)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" ,.;") + " …"
    y = 60
    for ln in lines:
        d.text((80, y), ln, font=f, fill=(48, 42, 38))
        y += lh
    d.line([(80, H - 92), (W - 80, H - 92)], fill=(190, 180, 160), width=2)
    d.text((80, H - 60), caption, font=font("DejaVuSans-Bold.ttf", 24), fill=INK, anchor="lm")
    if sub:
        d.text((W - 80, H - 60), sub, font=font("DejaVuSans.ttf", 20), fill=(110, 104, 96), anchor="rm")
    return out


def sheet(images: list[Image.Image], cols: int, side: int, labels: list[str] | None = None) -> Image.Image:
    """A contact sheet, for looking at generators."""
    rows = math.ceil(len(images) / cols)
    lab = 22 if labels else 0
    out = Image.new("RGB", (cols * side, rows * (side + lab)), (255, 255, 255))
    d = ImageDraw.Draw(out)
    for i, im in enumerate(images):
        r, c = divmod(i, cols)
        out.paste(thumb(im, side), (c * side, r * (side + lab)))
        if labels:
            d.text((c * side + side / 2, r * (side + lab) + side + 2), labels[i], font=font("DejaVuSans.ttf", 14),
                   fill=(40, 40, 40), anchor="mt")
    return out


def letter_boards(picture_img: Image.Image, cards: list[tuple[str, list[dict], str]], title: str) -> Image.Image:
    """The picture and every build side by side, each with its builder and readings: the hall's all-boards view."""
    tile, cap, pad, head = 420, 84, 18, 60
    n = len(cards) + 1
    cols = min(3, n)
    rows = math.ceil(n / cols)
    W = pad + cols * (tile + pad)
    H = head + rows * (tile + cap + pad) + pad
    out = Image.new("RGB", (W, H), (244, 239, 228))
    d = ImageDraw.Draw(out)
    d.text((pad, head / 2), title, font=font("DejaVuSans-Bold.ttf", 22), fill=INK, anchor="lm")
    tiles = [(thumb(picture_img, tile), "the picture", "")] + [(framed_board(sh, tile), name, line) for name, sh, line in cards]
    for i, (img, name, line) in enumerate(tiles):
        r, c = divmod(i, cols)
        x, y = pad + c * (tile + pad), head + r * (tile + cap + pad)
        out.paste(img, (x, y))
        d.text((x + 2, y + tile + 8), name, font=font("DejaVuSans-Bold.ttf", 19), fill=INK, anchor="lt")
        for k, part in enumerate(line.split("\n") if line else []):
            d.text((x + 2, y + tile + 34 + 22 * k), part, font=font("DejaVuSans.ttf", 16), fill=(90, 84, 76), anchor="lt")
    return out
