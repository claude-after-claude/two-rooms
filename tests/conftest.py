import socket
import threading
import time
from contextlib import contextmanager

import httpx
import pytest
import uvicorn

from tworooms.app import create_app


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@contextmanager
def serve(tmp_path, **kw):
    kw.setdefault("rate_limits", False)
    app = create_app(db_path=tmp_path / "t.sqlite", admin_key="admin-secret", cache_dir=tmp_path / "cache", **kw)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}", app
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture
def server(tmp_path):
    with serve(tmp_path) as s:
        yield s


class Client:
    """A test player: wraps httpx with the key and checks status codes."""

    def __init__(self, base: str, key: str | None = None, callsign: str | None = None):
        self.base, self.key, self.callsign = base, key, callsign
        self.http = httpx.Client(base_url=base, timeout=70)

    @classmethod
    def new(cls, base, callsign):
        r = httpx.post(base + "/api/players", json={"callsign": callsign})
        assert r.status_code == 201, r.text
        return cls(base, r.json()["key"], callsign)

    def _h(self):
        return {"Authorization": f"Bearer {self.key}"} if self.key else {}

    def req(self, method, path, expect=200, **kw):
        r = self.http.request(method, path, headers=self._h(), **kw)
        if expect is not None:
            exp = expect if isinstance(expect, (tuple, list)) else (expect,)
            assert r.status_code in exp, f"{method} {path} -> {r.status_code}: {r.text[:500]}"
        if r.headers.get("content-type", "").startswith("application/json"):
            return r.json()
        return r

    def get(self, path, expect=200, **kw):
        return self.req("GET", path, expect, **kw)

    def post(self, path, json=None, expect=(200, 201), **kw):
        return self.req("POST", path, expect, json=json, **kw)

    def put(self, path, json=None, expect=200, **kw):
        return self.req("PUT", path, expect, json=json, **kw)

    def status(self, path) -> int:
        return self.http.get(path, headers=self._h()).status_code
