"""Operator dashboard: spend, per-user limits, model health, recent LLM calls."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app import config
from app.ops.auth import COOKIE_NAME, is_authed, ops_enabled, require_ops, tokens_match
from app.ops.snapshot import overview
from app.routers.pages import asset_url

router = APIRouter(tags=["ops"])


def _login_html(error: str = "") -> str:
    err = (
        f'<p class="ops-error">{error}</p>'
        if error
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EasyLearn ops</title>
    <link rel="icon" type="image/svg+xml" href="/static/logo.svg">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Lato:wght@400;600;700&amp;display=swap" rel="stylesheet">
    <link rel="stylesheet" href="{asset_url("css/ops.css")}">
</head>
<body class="ops-login-body">
    <form class="ops-login" method="post" action="/ops/login">
        <h1>EasyLearn ops</h1>
        <p>Operator token required. Set OPS_ADMIN_TOKEN in .env.</p>
        {err}
        <label for="token">Token</label>
        <input id="token" name="token" type="password" autocomplete="current-password" required>
        <button type="submit">Open dashboard</button>
    </form>
</body>
</html>
"""


def _dashboard_html() -> str:
    html = (config.TEMPLATES_DIR / "ops.html").read_text(encoding="utf-8")
    for asset in ("css/ops.css", "js/ops.js"):
        html = html.replace(f"/static/{asset}", asset_url(asset))
    return html


@router.get("/ops", response_model=None)
def ops_home(request: Request) -> Response:
    if not ops_enabled():
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    if not is_authed(request):
        return RedirectResponse("/ops/login", status_code=303)
    return HTMLResponse(_dashboard_html())


@router.get("/ops/login", response_model=None)
def ops_login_form() -> Response:
    if not ops_enabled():
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    return HTMLResponse(_login_html())


@router.post("/ops/login", response_model=None)
def ops_login(token: str = Form(...)) -> Response:
    expected = (config.OPS_ADMIN_TOKEN or "").strip()
    if not expected:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    if not tokens_match((token or "").strip(), expected):
        return HTMLResponse(_login_html("Invalid token."), status_code=401)
    response = RedirectResponse("/ops", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        expected,
        httponly=True,
        samesite="lax",
        secure=config.SESSION_HTTPS_ONLY,
        max_age=7 * 24 * 3600,
        path="/ops",
    )
    return response


@router.post("/ops/logout")
def ops_logout() -> RedirectResponse:
    response = RedirectResponse("/ops/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/ops")
    return response


@router.get("/ops/api/overview")
def ops_overview(_: None = Depends(require_ops)) -> dict:
    return overview()
