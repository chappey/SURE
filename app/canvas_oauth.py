"""Canvas OAuth2 token exchange, refresh, and session storage helpers.

Keeps the per-professor token lifecycle out of the route handlers so
`app/routers/oauth.py` stays thin (see .cursor/rules/02-python-app.mdc).
The refresh token and expiry live in the encrypted session only -- never logged.
"""

from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

import requests
from starlette.requests import Request

from app import config

logger = logging.getLogger("easylearn")

# Refresh slightly before expiry to avoid racing a request against the deadline.
_REFRESH_LEEWAY_SECONDS = 120


def _token_url() -> str:
    return f"{config.CANVAS_API_URL.rstrip('/')}/login/oauth2/token"


def _token_request_headers() -> dict[str, str]:
    """For local HTTP Canvas (often behind a different internal hostname in Docker),
    some setups need a specific Host header on token requests.
    Set CANVAS_INTERNAL_HOST (e.g. canvas.docker) to enable the header.
    """
    headers: dict[str, str] = {}
    if config.LOCAL_HTTP_LTI:
        internal = (getattr(config, "CANVAS_INTERNAL_HOST", "") or "").strip()
        if not internal:
            # Heuristic: if the configured API hostname looks docker-ish, use it.
            try:
                h = urlparse(config.CANVAS_API_URL).hostname or ""
                if "docker" in h.lower():
                    internal = h
            except Exception:
                pass
        if internal:
            headers["Host"] = internal
    return headers


def exchange_code_for_token(code: str, redirect_uri: str) -> dict:
    """Exchange an authorization code for an access/refresh token pair."""
    payload = {
        "grant_type": "authorization_code",
        "client_id": config.CANVAS_CLIENT_ID,
        "client_secret": config.CANVAS_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "code": code,
    }
    response = requests.post(
        _token_url(), data=payload, headers=_token_request_headers(), timeout=30
    )
    if not response.ok:
        logger.warning(
            "OAuth token exchange failed: %s %s", response.status_code, response.text[:500]
        )
        raise ValueError("Failed to exchange authorization code with Canvas.")
    return response.json()


def refresh_access_token(refresh_token: str) -> dict:
    """Use a refresh token to obtain a fresh access token.

    Canvas omits ``refresh_token`` from refresh responses; the original stays valid.
    """
    payload = {
        "grant_type": "refresh_token",
        "client_id": config.CANVAS_CLIENT_ID,
        "client_secret": config.CANVAS_CLIENT_SECRET,
        "refresh_token": refresh_token,
    }
    response = requests.post(
        _token_url(), data=payload, headers=_token_request_headers(), timeout=30
    )
    if not response.ok:
        logger.warning(
            "OAuth token refresh failed: %s %s", response.status_code, response.text[:500]
        )
        raise ValueError("Failed to refresh Canvas access token.")
    return response.json()


def store_token(request: Request, data: dict) -> str | None:
    """Persist access token, refresh token, and expiry into the session.

    Returns the stored access token (or None when absent in the response).
    """
    access_token = data.get("access_token")
    if access_token:
        request.session["canvas_user_token"] = access_token

    # Canvas only returns refresh_token on the initial authorization_code exchange.
    refresh_token = data.get("refresh_token")
    if refresh_token:
        request.session["canvas_refresh_token"] = refresh_token

    expires_in = data.get("expires_in")
    if expires_in:
        try:
            request.session["canvas_token_expires_at"] = time.time() + int(expires_in)
        except (TypeError, ValueError):
            request.session.pop("canvas_token_expires_at", None)

    return access_token


def clear_tokens(request: Request) -> None:
    """Remove all Canvas OAuth token state from the session."""
    request.session.pop("canvas_user_token", None)
    request.session.pop("canvas_refresh_token", None)
    request.session.pop("canvas_token_expires_at", None)


def _token_is_expiring(request: Request) -> bool:
    """True when the access token is past (or near) its stored expiry."""
    expires_at = request.session.get("canvas_token_expires_at")
    if not expires_at:
        return False
    try:
        return time.time() >= float(expires_at) - _REFRESH_LEEWAY_SECONDS
    except (TypeError, ValueError):
        return False


def ensure_fresh_token(request: Request) -> None:
    """Proactively refresh the access token when it is expired or about to expire.

    No-op when OAuth is disabled, no refresh token is stored, or the token is still
    fresh. On refresh failure, clears tokens so the caller can re-trigger authorize.
    """
    if not config.oauth_enabled():
        return

    refresh_token = request.session.get("canvas_refresh_token")
    if not refresh_token:
        return

    if not request.session.get("canvas_user_token") or _token_is_expiring(request):
        try:
            data = refresh_access_token(refresh_token)
        except Exception:
            logger.warning("Proactive token refresh failed; clearing session tokens.")
            clear_tokens(request)
            return
        store_token(request, data)
        logger.info("Refreshed Canvas access token from refresh token.")


def try_refresh(request: Request) -> bool:
    """Attempt a one-shot refresh (used on an unexpected 401). Returns success."""
    if not config.oauth_enabled():
        return False
    refresh_token = request.session.get("canvas_refresh_token")
    if not refresh_token:
        return False
    try:
        data = refresh_access_token(refresh_token)
    except Exception:
        return False
    return bool(store_token(request, data))
