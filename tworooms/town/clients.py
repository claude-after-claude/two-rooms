"""The two sides the daemon talks to: Delve Town (read publicly; write as the hall's own account, or only print in a
dry run) and the hall (its own JSON API, as any player would, with the admin key to register town players and close
letters). The writer has no way to like, follow or repost: the daemon only posts."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx

API = "https://api.delve.town"
HOST = "https://pds.delve.town"
POST = "town.delve.feed.post"
UA = {"User-Agent": "two-rooms-hall-town/0.2"}


class TownError(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def web_url(uri: str, handle: str) -> str:
    """The delve.town page of a post."""
    return f"https://delve.town/profile/{handle}/post/{uri.rsplit('/', 1)[1]}"


def link_facets(text: str) -> list[dict]:
    """Addresses in a post are only clickable with a facet over their bytes."""
    out = []
    for m in re.finditer(r"https?://[^\s)\]]+", text):
        url = m.group(0).rstrip(".,;")
        start = len(text[: m.start()].encode())
        out.append({"index": {"byteStart": start, "byteEnd": start + len(url.encode())},
                    "features": [{"$type": "town.delve.richtext.facet#link", "uri": url}]})
    return out


def mention_facets(text: str, mentions: dict[str, str]) -> list[dict]:
    """A mention only notifies its account when the "@handle" carries a facet with the account's DID."""
    out = []
    for handle, did in mentions.items():
        at = text.find("@" + handle)
        if at >= 0:
            start = len(text[:at].encode())
            out.append({"index": {"byteStart": start, "byteEnd": start + len(("@" + handle).encode())},
                        "features": [{"$type": "town.delve.richtext.facet#mention", "did": did}]})
    return out


class TownReader:
    """Public reads; no account needed."""

    def __init__(self, api: str = API):
        self.api = api
        self.http = httpx.Client(timeout=30, headers=UA)

    def get(self, method: str, **params):
        try:
            r = self.http.get(f"{self.api}/xrpc/{method}", params=params)
        except httpx.HTTPError as e:
            raise TownError(f"{method}: {e}") from e
        if r.status_code != 200:
            raise TownError(f"{method}: HTTP {r.status_code} {r.text[:300]}")
        return r.json()

    def thread(self, uri: str) -> dict:
        return self.get("town.delve.feed.getPostThread", uri=uri, depth=60, parentHeight=0)["thread"]

    def profile(self, actor: str) -> dict:
        return self.get("town.delve.actor.getProfile", actor=actor)


class TownWriter:
    """Writes as the hall's own account. Logs in once, refreshes after that, keeps the session on disk (the town allows
    30 logins per five minutes and 300 a day)."""

    dry = False

    def __init__(self, handle: str, password: str, session_file: Path, host: str = HOST):
        self.handle, self.password, self.file, self.host = handle, password, Path(session_file), host
        self.http = httpx.Client(timeout=60, headers=UA)
        self.s = None

    def _call(self, method, body=None, token=None, raw=None, ctype=None, params=None):
        h = {"Authorization": "Bearer " + token} if token else {}
        url = f"{self.host}/xrpc/{method}"
        try:
            if raw is not None:
                r = self.http.post(url, content=raw, headers={**h, "Content-Type": ctype})
            elif body is not None:
                r = self.http.post(url, json=body, headers=h)
            elif method.endswith("refreshSession"):
                r = self.http.post(url, headers=h)
            else:
                r = self.http.get(url, headers=h, params=params)
        except httpx.HTTPError as e:
            raise TownError(f"{method}: {e}") from e
        if r.status_code == 429:
            raise TownError(f"{method}: rate limited, retry after {r.headers.get('Retry-After', '?')} s")
        if r.status_code >= 400:
            raise TownError(f"{method}: HTTP {r.status_code} {r.text[:300]}")
        return r.json() if r.content else {}

    def session(self) -> dict:
        if self.s is None and self.file.exists():
            self.s = json.loads(self.file.read_text())
        if self.s:
            try:
                self._call("com.atproto.server.getSession", token=self.s["accessJwt"])
                return self.s
            except TownError:
                try:
                    self.s = self._call("com.atproto.server.refreshSession", token=self.s["refreshJwt"])
                    self._save()
                    return self.s
                except TownError:
                    pass
        self.s = self._call("com.atproto.server.createSession", {"identifier": self.handle, "password": self.password})
        self._save()
        return self.s

    def _save(self):
        self.file.write_text(json.dumps(self.s))
        self.file.chmod(0o600)

    @property
    def did(self) -> str:
        return self.session()["did"]

    def post(self, text: str, reply: dict | None = None, image: bytes | None = None, alt: str | None = None,
             mentions: dict[str, str] | None = None) -> dict:
        """`reply` is {"root": {uri, cid}, "parent": {uri, cid}}; `mentions` maps a handle written as "@handle" in the
        text to its DID."""
        s = self.session()
        rec = {"$type": POST, "text": text, "createdAt": now_iso()}
        facets = mention_facets(text, mentions or {}) + link_facets(text)
        if facets:
            rec["facets"] = facets
        if image is not None:
            ctype = "image/png" if image[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
            blob = self._call("com.atproto.repo.uploadBlob", token=s["accessJwt"], raw=image, ctype=ctype)["blob"]
            rec["embed"] = {"$type": "town.delve.embed.images", "images": [{"alt": alt or "", "image": blob}]}
        if reply:
            rec["reply"] = reply
        out = self._call("com.atproto.repo.createRecord", {"repo": s["did"], "collection": POST, "record": rec},
                         token=s["accessJwt"])
        return {"uri": out["uri"], "cid": out["cid"]}

    def notifications(self, limit: int = 50) -> list[dict]:
        """Newest first: mentions of the hall and replies to it, among likes and follows."""
        s = self.session()
        return self._call("town.delve.notification.listNotifications", token=s["accessJwt"],
                          params={"limit": limit}).get("notifications", [])

    def set_profile(self, display: str, description: str):
        """The bot label the town asks agents to carry, and the profile shown in the app; other fields kept."""
        s = self.session()
        for coll in ("app.bsky.actor.profile", "town.delve.actor.profile"):
            try:
                cur = self._call("com.atproto.repo.getRecord", token=s["accessJwt"],
                                 params={"repo": s["did"], "collection": coll, "rkey": "self"})["value"]
            except TownError:
                cur = {"$type": coll}
            if coll == "app.bsky.actor.profile":
                labels = cur.setdefault("labels", {"$type": "com.atproto.label.defs#selfLabels", "values": []})
                if not any(v.get("val") == "bot" for v in labels.get("values", [])):
                    labels.setdefault("values", []).append({"val": "bot"})
            else:
                cur.update(displayName=display, description=description)
                cur.setdefault("createdAt", now_iso())
            self._call("com.atproto.repo.putRecord", {"repo": s["did"], "collection": coll, "rkey": "self",
                                                      "record": cur}, token=s["accessJwt"])


class DryWriter:
    """Prints what would be posted and sends nothing. Posts get made-up addresses so threads can be followed."""

    dry = True

    def __init__(self, handle: str, did: str | None = None, out=print, images: Path | None = None):
        self.handle, self.out, self.n, self.images = handle, out, 0, images
        self.did = did or "did:dry-run:" + handle

    def post(self, text, reply=None, image=None, alt=None, mentions=None) -> dict:
        self.n += 1
        uri = f"at://{self.did}/{POST}/dry{self.n}"
        where = f"reply under {reply['parent']['uri']}" if reply else "new post"
        if mentions:
            where += ", mentioning " + ", ".join(f"{h} ({d})" for h, d in mentions.items())
        img = ""
        if image:
            saved = ""
            if self.images:
                path = self.images / f"dry{self.n}.png"
                path.write_bytes(image)
                saved = f", saved as {path}"
            img = f"\n[image: {len(image):,} bytes{saved}]\n[alt text]\n{alt}"
        self.out(f"\n===== WOULD POST ({where}) as {self.handle} =====\n{text}{img}\n===== end =====")
        return {"uri": uri, "cid": f"dry{self.n}"}

    def set_profile(self, display, description):
        self.out(f"\n===== WOULD SET the bot label and the profile: {display!r} / {description!r}")


class HallError(Exception):
    def __init__(self, status: int, message: str, body: dict | None = None):
        super().__init__(message)
        self.status, self.message, self.body = status, message, body or {}


class HallClient:
    """The hall's JSON API, used the way any player uses it; the admin key to register town players and close."""

    def __init__(self, base: str, admin_key: str | None = None):
        self.base = base.rstrip("/")
        self.admin_key = admin_key
        self.http = httpx.Client(timeout=60, headers=UA)

    def _req(self, method, path, key=None, json_body=None, expect_json=True):
        h = {"Authorization": f"Bearer {key}"} if key else {}
        try:
            r = self.http.request(method, self.base + path, headers=h, json=json_body)
        except httpx.HTTPError as e:
            raise HallError(0, f"the hall did not answer: {e}") from e
        if r.status_code >= 400:
            try:
                body = r.json()
                msg = body["error"]
            except Exception:
                body, msg = {}, r.text[:300]
            raise HallError(r.status_code, msg, body)
        return r.json() if expect_json else r.content

    def register(self, callsign, about=None) -> str:
        return self._req("POST", "/api/players", self.admin_key,
                         {"callsign": callsign, "about": about, "via": "town"})["key"]

    def player(self, callsign: str) -> dict:
        return self._req("GET", f"/api/players/{callsign}")

    def open_letters(self, level: int) -> list[dict]:
        return self._req("GET", f"/api/letters?level={level}")["letters"]

    def letter(self, lid: str) -> dict:
        """As the admin sees it: words, status, every submitted build."""
        return self._req("GET", f"/api/letters/{lid}", self.admin_key)

    def take(self, key, lid, via_url=None) -> dict:
        return self._req("POST", f"/api/letters/{lid}/builds", key, {"via_url": via_url})

    def put_shapes(self, key, bid, shapes) -> dict:
        return self._req("PUT", f"/api/builds/{bid}/shapes", key, shapes)

    def check(self, key, bid) -> dict:
        return self._req("POST", f"/api/builds/{bid}/check", key, {})

    def submit(self, key, bid, note=None) -> dict:
        return self._req("POST", f"/api/builds/{bid}/submit", key, {"note": note} if note else {})

    def close(self, lid, reason) -> dict:
        return self._req("POST", f"/api/letters/{lid}/close", self.admin_key, {"reason": reason})

    def boards_png(self, lid) -> bytes:
        return self._req("GET", f"/og/boards/{lid}.png", self.admin_key, expect_json=False)
