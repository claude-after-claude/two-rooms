"""The application: one process, one SQLite file. `uv run tworooms` serves it on port 8377."""
import argparse
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db as D
from .api import Notifier, RateLimiter, router as api_router
from .fetchplay import router as fetch_router
from .game import GameError, Hall
from .images import ImageCache, Images
from .pages import error_page, router as pages_router

HERE = Path(__file__).parent


def create_app(db_path=None, admin_key=None, base_url=None, cache_dir=None, trust_proxy=None,
               rate_limits: bool = True) -> FastAPI:
    db_path = Path(db_path or os.environ.get("TWOROOMS_DB", "data/tworooms.sqlite"))
    app = FastAPI(title="Two Rooms", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.notifier = Notifier()
    app.state.hall = Hall(D.connect(db_path), notify=app.state.notifier.notify,
                          admin_key=admin_key or os.environ.get("TWOROOMS_ADMIN_KEY") or None)
    app.state.images = Images(ImageCache(Path(cache_dir) if cache_dir else db_path.parent / "cache"))
    app.state.limiter = RateLimiter() if rate_limits else _NoLimits()
    app.state.base_url = (base_url or os.environ.get("TWOROOMS_BASE_URL") or "").rstrip("/") or None
    app.state.trust_proxy = trust_proxy if trust_proxy is not None else os.environ.get("TWOROOMS_TRUST_PROXY") == "1"
    app.include_router(api_router)
    app.include_router(fetch_router)
    app.include_router(pages_router)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    def is_api(request: Request) -> bool:
        return request.url.path.startswith("/api/") or request.url.path.endswith(".png")

    @app.exception_handler(GameError)
    async def game_error(request: Request, exc: GameError):
        if is_api(request):
            return JSONResponse({"error": exc.message, **exc.extra}, status_code=exc.status)
        return error_page(request, exc.status, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        parts = []
        for e in exc.errors():
            where = ".".join(str(x) for x in e.get("loc", []) if x not in ("query", "body", "path"))
            parts.append(f"{where}: {e.get('msg')}" if where else e.get("msg", "invalid"))
        msg = "The request was not understood: " + "; ".join(parts) + ". The manual is at /llms.txt."
        if is_api(request):
            return JSONResponse({"error": msg}, status_code=400)
        return error_page(request, 400, msg)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/play"):
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(f"There is nothing at this address. The addresses for playing by fetching are "
                                     f"listed at /play.\n", status_code=200 if exc.status_code == 405 else exc.status_code)
        if exc.status_code == 404:
            msg = "There is nothing at this address. The manual is at /llms.txt." if is_api(request) else \
                "There is nothing at this address."
        elif exc.status_code == 405:
            msg = f"{request.method} is not how this address is used. The manual (/llms.txt) lists every request."
        else:
            msg = str(exc.detail)
        if is_api(request):
            return JSONResponse({"error": msg}, status_code=exc.status_code)
        return error_page(request, exc.status_code, msg)

    return app


class _NoLimits:
    def check(self, *a, **k):
        pass


def main():
    ap = argparse.ArgumentParser(description="Serve Two Rooms: the hall.")
    ap.add_argument("--host", default=os.environ.get("TWOROOMS_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("TWOROOMS_PORT", "8377")))
    ap.add_argument("--db", default=os.environ.get("TWOROOMS_DB", "data/tworooms.sqlite"))
    ap.add_argument("--base-url", default=os.environ.get("TWOROOMS_BASE_URL"),
                    help="public address used in links, e.g. https://tworooms.example; defaults to the request's host")
    args = ap.parse_args()
    import uvicorn
    # no access log: /play addresses carry players' keys in the query string
    uvicorn.run(create_app(db_path=args.db, base_url=args.base_url), host=args.host, port=args.port, access_log=False,
                proxy_headers=True, forwarded_allow_ips="*" if os.environ.get("TWOROOMS_TRUST_PROXY") == "1" else None)


if __name__ == "__main__":
    main()
