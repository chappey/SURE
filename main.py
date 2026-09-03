"""EasyLearn FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import secrets
import sys
import time
from contextlib import asynccontextmanager
from urllib.parse import urlparse
# Register custom pylti1p3 FastAPI adapter before router modules import it.
from app import lti as pylti1p3_fastapi

sys.modules["pylti1p3.contrib.fastapi"] = pylti1p3_fastapi

from canvasapi.exceptions import InvalidAccessToken
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from app import config
from app.auth import easylearn_url, oauth_enabled
from app.config import STATIC_DIR
from app.exceptions import AppError
from app.logging_config import configure_logging
from app.ops.context import bind_request
from app.routers import api, lti_routes, oauth, ops, pages

logger = configure_logging()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.ops import ledger
    from app.ops.poll import poll_forever

    ledger.init()
    poll_task = asyncio.create_task(poll_forever())
    try:
        yield
    finally:
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="EasyLearn", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError):
    """Return a typed, user-facing error with a server-side log entry."""
    rid = getattr(request.state, "request_id", "???")
    course_id = request.session.get("canvas_course_id", "?")
    logger.log(
        exc.log_level,
        "[%s] course %s: %s",
        rid,
        course_id,
        exc.log_msg or exc.detail,
    )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def handle_unhandled(request: Request, exc: Exception):
    """Last-resort safety net for completely unexpected errors."""
    rid = getattr(request.state, "request_id", "???")
    course_id = request.session.get("canvas_course_id", "?")
    logger.exception(
        "[%s] course %s: unhandled exception on %s %s",
        rid,
        course_id,
        request.method,
        request.url.path,
    )
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


@app.middleware("http")
async def csrf_check(request: Request, call_next):
    """Validate Origin/Referer on state-changing API requests."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        origin = request.headers.get("origin", "")
        referer = request.headers.get("referer", "")
        public = urlparse(config.EASYLEARN_PUBLIC_URL)
        expected = f"{public.scheme}://{public.netloc}"
        origin_ok = origin == expected
        ref_ok = False
        if referer:
            ref_parsed = urlparse(referer)
            ref_origin = f"{ref_parsed.scheme}://{ref_parsed.netloc}"
            ref_ok = ref_origin == expected
        if not origin_ok and not ref_ok:
            rid = getattr(request.state, "request_id", "???")
            logger.warning(
                "[%s] CSRF check failed: origin=%s referer=%s expected=%s",
                rid, origin, referer, expected,
            )
            return JSONResponse(status_code=403, content={"detail": "Cross-site request denied."})
    return await call_next(request)


@app.middleware("http")
async def lti_public_url_redirect(request: Request, call_next):
    """Send LTI traffic to EASYLEARN_PUBLIC_URL (e.g. when Canvas sees a different hostname)."""
    if request.url.path not in ("/login", "/launch", "/jwks"):
        return await call_next(request)

    public = urlparse(config.EASYLEARN_PUBLIC_URL)
    if not public.hostname or request.url.hostname == public.hostname:
        return await call_next(request)

    if request.url.hostname in ("localhost", "127.0.0.1"):
        target = request.url.replace(scheme=public.scheme, netloc=public.netloc)
        return RedirectResponse(str(target), status_code=302)

    return await call_next(request)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log request metadata and duration.

    Exceptions are deliberately NOT caught here — ``handle_unhandled`` below is
    the single last-resort handler, so there's exactly one error body/log path.
    """
    start_time = time.perf_counter()
    path = request.url.path
    method = request.method
    rid = secrets.token_hex(4)
    request.state.request_id = rid
    bind_request(request)
    user = "-"
    try:
        user = str(request.session.get("canvas_user_id") or "-")
    except Exception:
        pass
    logger.info("[%s] → %s %s user=%s", rid, method, path, user)

    response = await call_next(request)

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "[%s] ← %s %s — %s (%.0fms)", rid, method, path, response.status_code, elapsed_ms
    )
    return response


app.add_middleware(
    SessionMiddleware,
    secret_key=config.SESSION_SECRET_KEY,
    same_site=config.SESSION_SAME_SITE,
    https_only=config.SESSION_HTTPS_ONLY,
)


@app.exception_handler(InvalidAccessToken)
async def handle_invalid_token(request: Request, exc: InvalidAccessToken):
    """Attempt a one-shot refresh; otherwise clear tokens and prompt for re-authorization."""
    from app.canvas_oauth import clear_tokens, try_refresh

    # The refresh is a blocking HTTP call — run it on a worker thread so the
    # event loop isn't stalled for up to the full requests timeout.
    refreshed = await run_in_threadpool(try_refresh, request)

    if refreshed:
        logger.info("Canvas token refreshed after 401; asking client to retry.")
        if request.url.path.startswith("/api/"):
            return JSONResponse(
                status_code=401,
                content={
                    "error": "token_refreshed",
                    "detail": "Your Canvas session was refreshed. Please retry.",
                },
            )
        return RedirectResponse(url=str(request.url), status_code=303)

    logger.warning("Canvas API token is invalid or expired. Clearing from session.")
    clear_tokens(request)

    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=401,
            content={
                "error": "token_expired",
                "detail": "Your Canvas session has expired. Please refresh the page to re-authorize.",
            },
        )
    return RedirectResponse(
        url=easylearn_url("/oauth/login") if oauth_enabled() else easylearn_url("/")
    )


@app.get("/healthz")
async def healthz():
    """Liveness: process is up. No dependency checks."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    """Readiness: keys, LTI config, and at least one AI provider are present."""
    from pathlib import Path

    checks: dict[str, bool] = {}
    reasons: list[str] = []

    private_key = Path(config.PROJECT_ROOT) / "keys" / "private.key"
    public_key = Path(config.PROJECT_ROOT) / "keys" / "public.key"
    checks["lti_keys"] = private_key.is_file() and public_key.is_file()
    if not checks["lti_keys"]:
        reasons.append("missing keys/private.key or keys/public.key")

    checks["lti_config"] = config.LTI_CONFIG_PATH.is_file()
    if not checks["lti_config"]:
        reasons.append(f"missing {config.LTI_CONFIG_PATH.name}")

    checks["canvas_api_url"] = bool((config.CANVAS_API_URL or "").strip())
    if not checks["canvas_api_url"]:
        reasons.append("CANVAS_API_URL not set")

    has_ai = bool((config.OPENROUTER_API_KEY or "").strip()) or bool(
        (config.GEMINI_API_KEY or "").strip()
    )
    checks["ai_provider"] = has_ai
    if not has_ai:
        reasons.append("no OPENROUTER_API_KEY or GEMINI_API_KEY")

    ready = all(checks.values())
    body = {"status": "ready" if ready else "not_ready", "checks": checks}
    if reasons:
        body["reasons"] = reasons
    return JSONResponse(status_code=200 if ready else 503, content=body)


app.include_router(pages.router)
app.include_router(oauth.router)
app.include_router(lti_routes.router)
app.include_router(api.router)
app.include_router(ops.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
