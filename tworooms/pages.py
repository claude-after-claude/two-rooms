"""Server-rendered pages (filled in below)."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


def error_page(request: Request, status: int, message: str):
    return HTMLResponse(f"<!doctype html><title>Two Rooms</title><p>{message}</p>", status_code=status)
