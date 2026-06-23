"""Dashboard and static page routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse
from starlette.responses import Response

from app import config
from app.config import STATIC_DIR, TEMPLATES_DIR

router = APIRouter(tags=["pages"])


@router.get("/favicon.ico", include_in_schema=False)
def get_favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.ico")


@router.get("/")
def get_dashboard(request: Request) -> Response:
    """Serve the quiz dashboard; redirect to OAuth when multi-instructor mode is enabled."""
    if config.CANVAS_CLIENT_ID and config.CANVAS_CLIENT_SECRET:
        if not request.session.get("canvas_user_token"):
            return RedirectResponse(url="/oauth/login")
    return FileResponse(TEMPLATES_DIR / "dashboard.html")
