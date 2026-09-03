"""Dashboard and static page routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from starlette.responses import Response

from app.auth import easylearn_url, lti_launched, needs_oauth_authorization
from app.config import STATIC_DIR, TEMPLATES_DIR

router = APIRouter(tags=["pages"])


def asset_url(path: str) -> str:
    """Generate dynamic cache-busted static asset URL based on file modification timestamp."""
    file_path = STATIC_DIR / path
    if file_path.is_file():
        mtime = int(file_path.stat().st_mtime)
        return f"/static/{path}?v={mtime}"
    return f"/static/{path}"


@router.get("/favicon.ico", include_in_schema=False)
def get_favicon() -> FileResponse:
    svg_path = STATIC_DIR / "logo.svg"
    if svg_path.is_file():
        return FileResponse(svg_path, media_type="image/svg+xml")
    return FileResponse(STATIC_DIR / "favicon.ico")


@router.get("/")
def get_dashboard(request: Request) -> Response:
    """Serve the quiz dashboard with dynamic asset cache-busting."""
    if not lti_launched(request):
        return FileResponse(TEMPLATES_DIR / "launch_required.html")
    if needs_oauth_authorization(request):
        return RedirectResponse(url=easylearn_url("/oauth/login"))
    
    html = (TEMPLATES_DIR / "dashboard.html").read_text(encoding="utf-8")
    assets = [
        "css/dashboard.css",
        "js/util.js",
        "js/quiz-builder.js",
        "js/library.js",
        "js/feedback-reviewer.js",
        "js/quiz-modal.js",
        "js/main.js",
        "js/profile.js",
        "js/theme-sync.js",
    ]
    for asset in assets:
        html = html.replace(f"/static/{asset}", asset_url(asset))
    
    return HTMLResponse(content=html)
