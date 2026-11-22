"""Rendering with a cache: images are pure functions of their inputs, so they are kept on disk by a key."""
import threading
from collections import OrderedDict
from pathlib import Path

from . import render as R


class ImageCache:
    def __init__(self, directory: Path | None, memory_items: int = 256):
        self.dir = Path(directory) if directory else None
        if self.dir:
            self.dir.mkdir(parents=True, exist_ok=True)
        self.mem: OrderedDict[str, bytes] = OrderedDict()
        self.max = memory_items
        self.lock = threading.Lock()

    def get(self, key: str, make) -> bytes:
        with self.lock:
            if key in self.mem:
                self.mem.move_to_end(key)
                return self.mem[key]
        path = self.dir / f"{key}.img" if self.dir else None
        if path and path.exists():
            data = path.read_bytes()
        else:
            data = make()
            if path:
                tmp = path.with_suffix(".tmp")
                tmp.write_bytes(data)
                tmp.replace(path)
        with self.lock:
            self.mem[key] = data
            while len(self.mem) > self.max:
                self.mem.popitem(last=False)
        return data


def _sized(img, size):
    return R.thumb(img, size) if size and size < max(img.size) else img


class Images:
    """Every image the service serves, by what it shows."""

    def __init__(self, cache: ImageCache):
        self.cache = cache

    def painted_img(self, shapes, level, word, picture_id):
        return R.painted(shapes, level, word, f"{picture_id}:{word}")

    def picture(self, shapes, level, word, picture_id, size=None) -> bytes:
        k = R.key("picture", picture_id, word, size)
        return self.cache.get(k, lambda: R.png_bytes(_sized(self.painted_img(shapes, level, word, picture_id), size)))

    def board(self, shapes, word, grid, size=None, who="the builder's board") -> bytes:
        k = R.key("board", shapes, word, grid, size, who)
        return self.cache.get(k, lambda: R.png_bytes(_sized(R.board(shapes, word, grid=grid, who=who), size)))

    def plain(self, shapes, size=300) -> bytes:
        k = R.key("plain", shapes, size)
        return self.cache.get(k, lambda: R.png_bytes(R.plain(shapes, size)))

    def framed_board(self, shapes, size=None) -> bytes:
        k = R.key("framedboard", shapes, size)
        return self.cache.get(k, lambda: R.png_bytes(R.framed_board(shapes, size or 800)))

    def framed_diff(self, picture, build, size=None) -> bytes:
        k = R.key("frameddiff", picture, build, size)
        return self.cache.get(k, lambda: R.png_bytes(R.framed_diff(picture, build, size or 800)))

    def diff(self, picture, build, word, size=None) -> bytes:
        k = R.key("diff", picture, build, word, size)
        return self.cache.get(k, lambda: R.png_bytes(_sized(R.diff(picture, build, word), size)))

    def og_pair(self, shapes, level, word, picture_id, build, caption, sub) -> bytes:
        k = R.key("ogpair", picture_id, word, build, caption, sub)
        return self.cache.get(k, lambda: R.jpeg_bytes(R.og_pair(self.painted_img(shapes, level, word, picture_id), build,
                                                                caption, sub)))

    def og_letter(self, text, caption, sub) -> bytes:
        k = R.key("ogletter", text, caption, sub)
        return self.cache.get(k, lambda: R.jpeg_bytes(R.og_letter(text, caption, sub)))
