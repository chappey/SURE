"""Canvas OAuth2 routes for multi-instructor mode."""

from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app import config
from app.auth import canvas_oauth_authorize_base, canvas_oauth_redirect_uri, easylearn_url

logger = logging.getLogger("easylearn")
router = APIRouter(prefix="/oauth", tags=["oauth"])


@router.get("/login")
def oauth_login(request: Request) -> RedirectResponse:
    """Redirect the user to Canvas for OAuth2 authorization."""
    if not config.oauth_enabled():
        raise HTTPException(status_code=400, detail="OAuth2 client credentials are not configured.")

    state = secrets.token_hex(16)
    request.session["oauth_state"] = state

    params = urlencode(
        {
            "client_id": config.CANVAS_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": canvas_oauth_redirect_uri(),
            "state": state,
        }
    )
    authorize_url = f"{canvas_oauth_authorize_base()}/login/oauth2/auth?{params}"
    return RedirectResponse(authorize_url)


@router.get("/callback", name="oauth_callback")
def oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Exchange the authorization code for a user access token."""
    if error:
        raise HTTPException(status_code=400, detail=f"Canvas authorization failed: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code.")

    saved_state = request.session.get("oauth_state")
    if not saved_state or state != saved_state:
        raise HTTPException(status_code=400, detail="Invalid state parameter. CSRF verification failed.")
    request.session.pop("oauth_state", None)

    redirect_uri = canvas_oauth_redirect_uri()
    token_url = f"{config.CANVAS_API_URL.rstrip('/')}/login/oauth2/token"
    payload = {
        "grant_type": "authorization_code",
        "client_id": config.CANVAS_CLIENT_ID,
        "client_secret": config.CANVAS_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "code": code,
    }

    headers = {}
    if "localhost" in config.CANVAS_API_URL or "127.0.0.1" in config.CANVAS_API_URL:
        headers["Host"] = "canvas.docker"

    try:
        response = requests.post(token_url, data=payload, headers=headers, timeout=30)
        if not response.ok:
            logger.error("OAuth token exchange failed: %s %s", response.status_code, response.text[:500])
            raise HTTPException(status_code=400, detail="Failed to exchange authorization code with Canvas.")

        data = response.json()
        access_token = data.get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="Access token missing in token response.")

        request.session["canvas_user_token"] = access_token
        user_info = data.get("user", {})
        if user_info.get("id"):
            request.session["canvas_user_id"] = str(user_info["id"])
        if user_info.get("name"):
            request.session["user_name"] = user_info["name"]

        lti_sub = request.session.get("lti_sub")
        oauth_id = str(user_info.get("id", ""))
        if lti_sub and oauth_id and lti_sub != oauth_id:
            logger.warning(
                "LTI sub (%s) differs from OAuth user id (%s) — OAuth id used for API calls",
                lti_sub,
                oauth_id,
            )

        return RedirectResponse(url=easylearn_url("/"), status_code=303)
    except HTTPException:
        raise
    except requests.RequestException as exc:
        logger.exception("Network error during OAuth2 token exchange")
        raise HTTPException(status_code=502, detail="Could not reach Canvas for token exchange.") from exc
    except Exception as exc:
        logger.exception("Unexpected error during OAuth2 token exchange")
        raise HTTPException(status_code=500, detail="OAuth2 token exchange failed.") from exc
