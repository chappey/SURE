"""LTI 1.3 OIDC login, launch, and JWKS routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pylti1p3.contrib.fastapi import FastAPILTIRequest

from app import config
from app.canvas_ids import extract_course_id_from_lti_launch
from app.lti import EasyLearnOIDCLogin
from app.lti_claims import extract_lti_user_fields
from app.lti_config import tool_conf

logger = logging.getLogger("easylearn")
router = APIRouter(tags=["lti"])


def _should_run_cookie_probe(request: Request) -> bool:
    """Run iframe cookie probe only when Canvas embeds us; skip for new-tab (_blank) launches."""
    from app import config

    if request.query_params.get("lti1p3_new_window"):
        return False
    dest = (request.headers.get("sec-fetch-dest") or "").lower()
    if dest == "iframe":
        return True
    # HTTP dev: _blank opens /login top-level — go straight to Canvas OIDC.
    if config.LOCAL_HTTP_LTI and dest in ("document", "nested-document", ""):
        return False
    return True


@router.get("/jwks")
def get_jwks() -> JSONResponse:
    """Expose the public JWK set so Canvas can authenticate the tool."""
    return JSONResponse(content=tool_conf.get_jwks())


@router.get("/login")
@router.post("/login")
async def lti_login(request: Request) -> RedirectResponse:
    """OIDC login initiation."""
    form_data = await request.form() if request.method == "POST" else {}
    request_data = {**request.query_params, **form_data}

    oidc_login = EasyLearnOIDCLogin(request, tool_conf, request_data=request_data)
    target_link_uri = (
        request.query_params.get("target_link_uri")
        or request.headers.get("target_link_uri")
        or request_data.get("target_link_uri")
    )
    if target_link_uri:
        from app import config as app_config

        target_link_uri = app_config.rewrite_tool_url(target_link_uri)
    if not target_link_uri:
        raise HTTPException(status_code=400, detail="Missing target_link_uri")

    if _should_run_cookie_probe(request):
        oidc_login.enable_check_cookies()
    return oidc_login.redirect(target_link_uri)


@router.get("/launch")
@router.post("/launch")
async def lti_launch(request: Request) -> RedirectResponse:
    """Handle the signed LTI 1.3 launch payload."""
    if request.method == "POST":
        try:
            form_data = await request.form()
            lti_request = FastAPILTIRequest(request, tool_conf, request_data=form_data)
            launch_data = lti_request.get_launch_data()

            request.session["lti_launched"] = True
            user_fields = extract_lti_user_fields(launch_data)
            if user_fields.get("user_name"):
                request.session["user_name"] = user_fields["user_name"]
            if user_fields.get("user_email"):
                request.session["user_email"] = user_fields["user_email"]
            if user_fields.get("user_role"):
                request.session["user_role"] = user_fields["user_role"]
            if user_fields.get("lti_sub"):
                request.session["lti_sub"] = user_fields["lti_sub"]

            course_id = extract_course_id_from_lti_launch(launch_data)
            if course_id is not None:
                request.session["canvas_course_id"] = str(course_id)
                logger.info(
                    "LTI launch: user=%r course_id=%s sub=%r host=%s",
                    request.session.get("user_name"),
                    course_id,
                    request.session.get("lti_sub"),
                    request.url.hostname,
                )
            else:
                logger.warning("LTI launch: no course id in launch claims")

            context = launch_data.get("https://purl.imsglobal.org/spec/lti/claim/context", {})
            if context.get("title"):
                request.session["course_name"] = context.get("title")
        except Exception as exc:
            logger.exception("LTI validation failed on /launch: %s", exc)

    return RedirectResponse(url=f"{config.EASYLEARN_PUBLIC_URL}/", status_code=303)
