"""LTI 1.3 OIDC login, launch, and JWKS routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pylti1p3.contrib.fastapi import FastAPILTIRequest, FastAPIOIDCLogin

from app.lti_config import tool_conf

logger = logging.getLogger("easylearn")
router = APIRouter(tags=["lti"])


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

    oidc_login = FastAPIOIDCLogin(request, tool_conf, request_data=request_data)
    target_link_uri = (
        request.query_params.get("target_link_uri")
        or request.headers.get("target_link_uri")
        or request_data.get("target_link_uri")
    )
    if not target_link_uri:
        raise HTTPException(status_code=400, detail="Missing target_link_uri")

    return oidc_login.enable_check_cookies().redirect(target_link_uri)


@router.get("/launch")
@router.post("/launch")
async def lti_launch(request: Request) -> RedirectResponse:
    """Handle the signed LTI 1.3 launch payload."""
    if request.method == "POST":
        try:
            form_data = await request.form()
            lti_request = FastAPILTIRequest(request, tool_conf, request_data=form_data)
            launch_data = lti_request.get_launch_data()

            custom_params = launch_data.get("https://purl.imsglobal.org/spec/lti/claim/custom", {})
            canvas_course_id = custom_params.get("canvas_course_id") or custom_params.get(
                "custom_canvas_course_id"
            )
            if not canvas_course_id:
                context = launch_data.get("https://purl.imsglobal.org/spec/lti/claim/context", {})
                canvas_course_id = context.get("id")

            if canvas_course_id:
                request.session["canvas_course_id"] = str(canvas_course_id)

            lti_sub = launch_data.get("sub")
            if lti_sub:
                request.session["canvas_user_id"] = str(lti_sub)

            context = launch_data.get("https://purl.imsglobal.org/spec/lti/claim/context", {})
            request.session["course_name"] = context.get("title", "Computer Science Principles")
            request.session["user_name"] = launch_data.get("name", "Instructor")
        except Exception as exc:
            logger.error("LTI validation failed, redirecting anyway: %s", exc)

    return RedirectResponse(url="/", status_code=303)
