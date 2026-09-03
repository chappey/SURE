"""Token gate for the operator dashboard (separate from LTI sessions)."""

from __future__ import annotations

import hashlib
import hmac
from typing import Annotated

from fastapi import Cookie, Header, HTTPException, Request, status

from app import config

COOKIE_NAME = "easylearn_ops"


def ops_enabled() -> bool:
    return bool((config.OPS_ADMIN_TOKEN or "").strip())


def configured_token() -> str:
    return (config.OPS_ADMIN_TOKEN or "").strip()


def presented_token(
    request: Request,
    authorization: str | None = None,
    cookie: str | None = None,
) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    if cookie:
        return cookie
    return (request.cookies.get(COOKIE_NAME) or "").strip()


def tokens_match(presented: str, expected: str) -> bool:
    if not expected:
        return False
    return hmac.compare_digest(
        hashlib.sha256((presented or "").encode("utf-8")).digest(),
        hashlib.sha256(expected.encode("utf-8")).digest(),
    )


def is_authed(request: Request) -> bool:
    expected = configured_token()
    if not expected:
        return False
    auth = request.headers.get("authorization")
    return tokens_match(presented_token(request, authorization=auth), expected)


def require_ops(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    easylearn_ops: Annotated[str | None, Cookie()] = None,
) -> None:
    expected = configured_token()
    if not expected:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    presented = presented_token(request, authorization=authorization, cookie=easylearn_ops)
    if not tokens_match(presented, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Operator authentication required.",
        )
