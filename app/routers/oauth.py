"""Canvas OAuth2 routes for multi-instructor mode."""

from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app import config
from app.auth import canvas_oauth_authorize_base, canvas_oauth_redirect_uri, easylearn_url, require_lti_launch
from app.canvas_oauth import exchange_code_for_token, fetch_users_self, store_token

logger = logging.getLogger("easylearn")
router = APIRouter(prefix="/oauth", tags=["oauth"])


@router.get("/login")
def oauth_login(request: Request) -> RedirectResponse:
    """Redirect the user to Canvas for OAuth2 authorization."""
    require_lti_launch(request)
    if not config.oauth_enabled():
        raise HTTPException(status_code=400, detail="OAuth2 client credentials are not configured.")

    state = secrets.token_hex(16)
    request.session["oauth_state"] = state

    query: dict[str, str] = {
        "client_id": config.CANVAS_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": canvas_oauth_redirect_uri(),
        "state": state,
    }
    scopes = config.CANVAS_OAUTH_SCOPES.strip()
    if scopes:
        # Canvas enforces these only when the Developer Key has "Enforce Scopes" on;
        # the value must be a subset of the key's allowed scopes or authorize fails.
        query["scope"] = scopes

    params = urlencode(query)
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
    require_lti_launch(request)
    if error:
        raise HTTPException(status_code=400, detail=f"Canvas authorization failed: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code.")

    saved_state = request.session.get("oauth_state")
    if not saved_state or state != saved_state:
        raise HTTPException(status_code=400, detail="Invalid state parameter. CSRF verification failed.")
    request.session.pop("oauth_state", None)

    redirect_uri = canvas_oauth_redirect_uri()

    try:
        data = exchange_code_for_token(code, redirect_uri)
        access_token = store_token(request, data)
        if not access_token:
            raise HTTPException(status_code=400, detail="Access token missing in token response.")

        user_info = data.get("user", {}) or {}
        # Token responses often only include {id}; fill name/email from /users/self.
        try:
            profile = fetch_users_self(access_token)
        except requests.RequestException:
            profile = {}
            logger.exception("Could not load Canvas /users/self after OAuth")

        oauth_id = str(profile.get("id") or user_info.get("id") or "")
        if oauth_id:
            request.session["canvas_user_id"] = oauth_id

        display_name = (
            profile.get("name")
            or user_info.get("name")
            or profile.get("short_name")
            or request.session.get("user_name")
        )
        if display_name:
            request.session["user_name"] = display_name

        email = profile.get("email") or profile.get("login_id") or request.session.get("user_email")
        if email:
            request.session["user_email"] = email

        lti_sub = request.session.get("lti_sub")
        if lti_sub and oauth_id and str(lti_sub) != oauth_id:
            logger.warning(
                "LTI sub (%s) differs from OAuth user id (%s) — OAuth id used for API calls",
                lti_sub,
                oauth_id,
            )

        return RedirectResponse(url=easylearn_url("/"), status_code=303)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.RequestException as exc:
        logger.exception("Network error during OAuth2 token exchange")
        raise HTTPException(status_code=502, detail="Could not reach Canvas for token exchange.") from exc
    except Exception as exc:
        logger.exception("Unexpected error during OAuth2 token exchange")
        raise HTTPException(status_code=500, detail="OAuth2 token exchange failed.") from exc
