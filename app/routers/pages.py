"""Dashboard and static page routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse
from starlette.responses import Response

from app.auth import easylearn_url, lti_launched, needs_oauth_authorization
from app.config import STATIC_DIR, TEMPLATES_DIR

router = APIRouter(tags=["pages"])


@router.get("/favicon.ico", include_in_schema=False)
def get_favicon() -> FileResponse:
    svg_path = STATIC_DIR / "logo.svg"
    if svg_path.is_file():
        return FileResponse(svg_path, media_type="image/svg+xml")
    return FileResponse(STATIC_DIR / "favicon.ico")


@router.get("/")
def get_dashboard(request: Request) -> Response:
    """Serve the quiz dashboard; redirect to OAuth when multi-instructor mode is enabled."""
    if not lti_launched(request):
        return FileResponse(TEMPLATES_DIR / "launch_required.html")
    if needs_oauth_authorization(request):
        return RedirectResponse(url=easylearn_url("/oauth/login"))
    return FileResponse(TEMPLATES_DIR / "dashboard.html")
