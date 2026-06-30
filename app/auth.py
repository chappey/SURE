"""Authentication helpers: OAuth mode, session snapshot, public URLs."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from starlette.requests import Request

from app import config
from app.canvas_ids import normalize_canvas_course_id


def oauth_enabled() -> bool:
    return config.oauth_enabled()


def lti_launched(request: Request) -> bool:
    return bool(request.session.get("lti_launched"))


def require_lti_launch(request: Request) -> None:
    """Reject requests that did not originate from a validated LTI launch."""
    if lti_launched(request):
        return
    raise HTTPException(
        status_code=403,
        detail=(
            "EasyLearn must be launched from Canvas. "
            "Open your course and select the EasyLearn external tool."
        ),
    )


def require_oauth_configured() -> None:
    """Production requires OAuth so API calls use per-professor tokens."""
    if oauth_enabled():
        return
    raise HTTPException(
        status_code=503,
        detail=(
            "Canvas OAuth is not configured. Set CANVAS_CLIENT_ID and "
            "CANVAS_CLIENT_SECRET, or run utils/configure_oauth.py --write-env."
        ),
    )


def easylearn_url(path: str) -> str:
    """Absolute URL on EASYLEARN_PUBLIC_URL."""
    base = config.EASYLEARN_PUBLIC_URL.rstrip("/")
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


def canvas_oauth_redirect_uri() -> str:
    if config.CANVAS_OAUTH_REDIRECT_URI.strip():
        return config.CANVAS_OAUTH_REDIRECT_URI.rstrip("/")
    return easylearn_url("/oauth/callback")


def canvas_oauth_authorize_base() -> str:
    """Browser-facing Canvas base for OAuth authorize (not internal API URL)."""
    return config.CANVAS_PUBLIC_URL.rstrip("/")


def build_session_info(request: Request) -> dict[str, Any]:
    """Return auth snapshot for /api/session and dashboard UI."""
    session = request.session
    oauth_on = oauth_enabled()
    has_user_token = bool(session.get("canvas_user_token"))
    launched = bool(session.get("lti_launched"))
    course_id = normalize_canvas_course_id(session.get("canvas_course_id"))

    if oauth_on and has_user_token:
        auth_mode = "oauth"
        canvas_api_source = "user_token"
    elif oauth_on and launched and not has_user_token:
        auth_mode = "oauth_pending"
        canvas_api_source = "none"
    else:
        auth_mode = "anonymous"
        canvas_api_source = "none"

    return {
        "user_name": session.get("user_name"),
        "user_email": session.get("user_email"),
        "user_role": session.get("user_role"),
        "canvas_user_id": session.get("canvas_user_id"),
        "lti_sub": session.get("lti_sub"),
        "canvas_course_id": course_id,
        "course_name": session.get("course_name"),
        "launched_from_canvas": launched,
        "auth_mode": auth_mode,
        "canvas_api_source": canvas_api_source,
        "oauth_required": True,
        "oauth_connected": has_user_token,
        "lti_required": True,
    }


def needs_oauth_authorization(request: Request) -> bool:
    """True when OAuth is configured but the session has no user API token."""
    return oauth_enabled() and not request.session.get("canvas_user_token")
